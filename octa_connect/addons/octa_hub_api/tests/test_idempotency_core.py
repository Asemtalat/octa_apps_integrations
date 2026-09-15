"""
اختبارات RUN فعليًا (pytest، بدون Odoo) لمنطق منع التكرار والتزامن —
تطابق سطور القسم 14 من ملف Octa_Connect_Claude_Phase_1.md حرفيًا:
- إرسال الحدث نفسه 20 مرة متزامنة → طلب منطقي واحد، كل المحاولات قابلة للتتبع.
- نفس المفتاح بمحتوى مختلف → تعارض موثّق.
- POS يسجل ثم يقطع الرد → unknown صريح، لا إعادة عمياء.
- إلغاء قبل الإنشاء، وتحديث قديم بعد حالة نهائية → يُحترمان.

ملاحظة صادقة: هذا يختبر النواة (in-memory) لا الالتزام الذري داخل PostgreSQL
الفعلي عبر قيد UNIQUE في Odoo — ذاك يحتاج قاعدة بيانات حقيقية وهو NOT RUN
(مسجّل في docs/requirements-coverage.md وdocs/test-report.md).
"""
import concurrent.futures
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from idempotency import (
    InMemoryIdempotencyStore, IdempotencyOutcome, TransportState,
    CommercialState, content_hash,
)

ORDER_KEY = ("t1", "b1", "conn_hungerstation", "EXT-ORDER-9")
PAYLOAD = {"items": "liver x1", "total": 3000, "currency": "SAR"}


def test_20_concurrent_identical_events_yield_one_logical_order_all_attempts_tracked():
    store = InMemoryIdempotencyStore()

    def send():
        return store.register_event(ORDER_KEY, "evt-fixed-1", PAYLOAD)

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
        results = list(ex.map(lambda _: send(), range(20)))

    outcomes = [r[1] for r in results]
    assert outcomes.count(IdempotencyOutcome.NEW_LOGICAL_ORDER) == 1
    assert outcomes.count(IdempotencyOutcome.DUPLICATE_SAME_PAYLOAD) == 19

    order = store.get(ORDER_KEY)
    assert len(order.attempts) == 20  # كل المحاولات مسجّلة ومتتبَّعة
    assert len({a.attempt_id for a in order.attempts}) == 20  # لا attempt_id مكرر


def test_same_key_different_content_is_conflict_not_silent_success():
    store = InMemoryIdempotencyStore()
    store.register_event(ORDER_KEY, "evt-1", PAYLOAD)
    different_payload = {"items": "liver x2", "total": 6000, "currency": "SAR"}
    order, outcome = store.register_event(ORDER_KEY, "evt-2", different_payload)
    assert outcome == IdempotencyOutcome.CONFLICT_DIFFERENT_PAYLOAD
    # المخزَّن يبقى بالمحتوى الأول، لا كتابة صامتة فوقه:
    assert order.content_hash == content_hash(PAYLOAD)


def test_pos_registers_then_response_lost_yields_unknown_not_blind_retry():
    store = InMemoryIdempotencyStore()
    store.register_event(ORDER_KEY, "evt-1", PAYLOAD)
    store.mark_dispatching(ORDER_KEY)
    # الرد ضاع؛ لا استعلام متاح ولا idempotency key مدعوم من الطرف الآخر
    store.mark_unknown(ORDER_KEY)
    order = store.get(ORDER_KEY)
    assert order.transport_state == TransportState.UNKNOWN
    assert order.transport_state != TransportState.NEEDS_INTERVENTION  # unknown != فشل


def test_unknown_does_not_overwrite_confirmed_final_state():
    store = InMemoryIdempotencyStore()
    store.register_event(ORDER_KEY, "evt-1", PAYLOAD)
    store.mark_dispatching(ORDER_KEY)
    store.mark_registered_confirmed(ORDER_KEY)
    store.mark_unknown(ORDER_KEY)  # حدث متأخر يصل بعد التأكيد
    order = store.get(ORDER_KEY)
    assert order.transport_state == TransportState.REGISTERED_CONFIRMED  # لم يتراجع


def test_cancel_before_creation_is_recorded_not_dropped():
    store = InMemoryIdempotencyStore()
    result = store.apply_cancel(ORDER_KEY)  # لا يوجد طلب بعد
    assert result == "cancel_pending_no_order_yet"  # ليس خطأ صامتًا، بل حالة صريحة


def test_stale_reverse_update_after_final_state_is_rejected():
    store = InMemoryIdempotencyStore()
    store.register_event(ORDER_KEY, "evt-1", PAYLOAD)
    order = store.get(ORDER_KEY)
    order.commercial_state = CommercialState.CANCELLED
    last_seq = {}
    result = store.apply_stale_update(ORDER_KEY, CommercialState.IN_PREPARATION, incoming_seq=1, last_applied_seq=last_seq)
    assert result == "final_state_protected"
    assert store.get(ORDER_KEY).commercial_state == CommercialState.CANCELLED  # لم يرجع للتحضير


def test_out_of_order_sequence_is_ignored():
    store = InMemoryIdempotencyStore()
    store.register_event(ORDER_KEY, "evt-1", PAYLOAD)
    last_seq = {}
    store.apply_stale_update(ORDER_KEY, CommercialState.ACCEPTED, incoming_seq=5, last_applied_seq=last_seq)
    result = store.apply_stale_update(ORDER_KEY, CommercialState.NEW, incoming_seq=2, last_applied_seq=last_seq)
    assert result == "stale_update_ignored"
    assert store.get(ORDER_KEY).commercial_state == CommercialState.ACCEPTED


def test_200_concurrent_threads_across_5_keys_no_race(monkeypatch=None):
    """اختبار إجهاد إضافي (مراجعة سابعة): 10 أضعاف حد الـ20 thread المطلوب
    في الوثيقة، على 5 مفاتيح فريدة بينها. يتأكد أن القفل لا ينهار تحت حمل
    أعلى من الحد الأدنى المطلوب، وأن كل attempt_id فريد عالميًا حتى عبر
    مفاتيح مختلفة (لا تصادم في مولّد المعرفات نفسه تحت تزامن مرتفع)."""
    store = InMemoryIdempotencyStore()
    payload = {"x": 1}

    def hammer(i):
        key = ("t1", "b1", "conn", f"ORDER-{i % 5}")
        return store.register_event(key, f"evt-{i}", payload)

    with concurrent.futures.ThreadPoolExecutor(max_workers=200) as ex:
        results = list(ex.map(hammer, range(200)))

    outcomes = [r[1] for r in results]
    assert outcomes.count(IdempotencyOutcome.NEW_LOGICAL_ORDER) == 5
    assert outcomes.count(IdempotencyOutcome.DUPLICATE_SAME_PAYLOAD) == 195

    all_attempts = []
    for key_suffix in range(5):
        order = store.get(("t1", "b1", "conn", f"ORDER-{key_suffix}"))
        all_attempts.extend(a.attempt_id for a in order.attempts)
    assert len(all_attempts) == len(set(all_attempts)) == 200  # صفر تصادم معرفات
