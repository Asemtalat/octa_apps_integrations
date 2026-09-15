"""اختبارات RUN فعليًا لإعادة المعالجة الفردية والجماعية (OC05-15)."""
import os
import sys
import concurrent.futures

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "octa_hub_api", "lib"))
from idempotency import InMemoryIdempotencyStore, IdempotencyOutcome  # noqa: E402

from reprocessing import (
    ReprocessRequest, OrderSnapshot, preview_eligibility, RateLimiter, AttemptTracker,
    double_click_or_duplicate_task_produces_single_external_effect,
    recheck_state_at_execution_time, ExclusionReason,
)


def test_preview_separates_eligible_from_excluded_with_reasons():
    request = ReprocessRequest("op-1", ["o1", "o2", "o3"], reason="stuck", actor_user_id="u1",
                                requested_at=1000.0, authorized_branch_ids={"BR-A"})
    orders = [
        OrderSnapshot("o1", "BR-A", "in_preparation", is_expired=False, completed=False),  # مؤهل
        OrderSnapshot("o2", "BR-A", "completed", is_expired=False, completed=True),          # مكتمل بالفعل
        OrderSnapshot("o3", "BR-B", "in_preparation", is_expired=False, completed=False),   # فرع غير مخوَّل
    ]
    result = preview_eligibility(request, orders)
    assert result.eligible_order_ids == ["o1"]
    assert result.excluded["o2"] == ExclusionReason.ALREADY_COMPLETED
    assert result.excluded["o3"] == ExclusionReason.NOT_AUTHORIZED_FOR_BRANCH


def test_expired_order_is_excluded():
    request = ReprocessRequest("op-1", ["o1"], "stuck", "u1", 1000.0, {"BR-A"})
    orders = [OrderSnapshot("o1", "BR-A", "new", is_expired=True, completed=False)]
    result = preview_eligibility(request, orders)
    assert result.eligible_order_ids == []
    assert result.excluded["o1"] == ExclusionReason.EXPIRED


def test_new_attempt_id_created_each_time_not_new_order_id():
    """القبول حرفيًا: كل محاولة attempt_id جديد؛ لا تنشئ order_id جديدًا."""
    tracker = AttemptTracker()
    a1 = tracker.new_attempt("order-1")
    a2 = tracker.new_attempt("order-1")
    assert a1 != a2  # محاولتان مختلفتان
    assert tracker.attempts_for("order-1") == [a1, a2]  # لنفس order_id، لم يتغيّر


def test_double_click_produces_single_external_effect_via_real_idempotency_core():
    """القبول حرفيًا: تكرار الضغط أو وصول مهمتين لا يسبب أثرين خارجيين —
    يُختبر هنا فعليًا عبر إعادة استخدام lib/idempotency.py الحقيقي (7/8
    اختبارًا سابقًا PASS)، لا محاكاة جديدة منفصلة."""
    tracker = AttemptTracker()
    store = InMemoryIdempotencyStore()
    order_key = ("t1", "b1", "conn", "ORDER-REPROCESS-1")
    payload = {"action": "reprocess"}

    def click(_):
        return double_click_or_duplicate_task_produces_single_external_effect(
            tracker, store, "order-1", order_key, "reprocess-evt-fixed", payload)

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        results = list(ex.map(click, range(10)))

    attempt_ids = [r[0] for r in results]
    outcomes = [r[1] for r in results]
    assert len(set(attempt_ids)) == 10  # 10 محاولات مختلفة (attempt_id فريد لكل ضغطة)
    assert outcomes.count(IdempotencyOutcome.NEW_LOGICAL_ORDER) == 1  # لكن أثر خارجي واحد فقط
    assert outcomes.count(IdempotencyOutcome.DUPLICATE_SAME_PAYLOAD) == 9


def test_state_rechecked_at_execution_time_not_only_at_request_time():
    """القبول حرفيًا: التحقق من الحالة عند الطلب وعند التنفيذ — قد تتغيران."""
    at_request = OrderSnapshot("o1", "BR-A", "in_preparation", is_expired=False, completed=False)
    at_execution = OrderSnapshot("o1", "BR-A", "completed", is_expired=False, completed=True)
    try:
        recheck_state_at_execution_time(at_request, at_execution)
        assert False, "كان يجب رفع استثناء"
    except ValueError as e:
        assert "اكتمل" in str(e)


def test_rate_limiter_is_per_tenant_channel_not_global():
    """حدود عدالة لكل تاجر وقناة — تاجر صغير لا يُجوَّع بسبب تاجر كبير."""
    limiter = RateLimiter(max_per_window=2, window_seconds=60)
    # تاجر A يستهلك حصته بالكامل
    assert limiter.check_and_record("tenant_a", "ch1", now=0) is True
    assert limiter.check_and_record("tenant_a", "ch1", now=1) is True
    assert limiter.check_and_record("tenant_a", "ch1", now=2) is False  # تجاوز الحد
    # تاجر B غير متأثر إطلاقًا بحصة تاجر A
    assert limiter.check_and_record("tenant_b", "ch1", now=2) is True


def test_rate_limiter_window_resets_over_time():
    limiter = RateLimiter(max_per_window=1, window_seconds=10)
    assert limiter.check_and_record("t1", "ch1", now=0) is True
    assert limiter.check_and_record("t1", "ch1", now=5) is False  # لا يزال داخل النافذة
    assert limiter.check_and_record("t1", "ch1", now=11) is True  # النافذة انتهت، مسموح تاني
