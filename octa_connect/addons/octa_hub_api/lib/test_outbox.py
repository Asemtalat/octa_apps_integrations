"""
اختبارات RUN فعليًا لنمط Outbox (R13) — تغطي سيناريوهات §14 الإلزامية
وإصلاح النجاح الوهمي في العامل (طلب صريح لاحق).

test_outbox_with_real_mock_pos_http_server أدناه هو الدليل الأهم: تكامل
حقيقي فعلي (لا محاكاة نظرية) بين outbox والخادم التجريبي الحقيقي
(tools/mock_pos)، يثبت أن "انقطاع الاتصال بعد الاستلام" يُعالَج بالاستعلام
لا بإعادة الإرسال، وأن النتيجة النهائية "done" لا تصل إلا بتأكيد حقيقي.
"""
import concurrent.futures
import os
import sys
import time

import pytest

from outbox import (
    Outbox, OutboxStatus, DispatchOutcome, DispatchResult,
    run_dispatch_cycle, run_query_cycle, exponential_backoff_seconds,
)

_MOCK_POS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "tools", "mock_pos")
if _MOCK_POS_DIR not in sys.path:
    sys.path.insert(0, _MOCK_POS_DIR)


def test_enqueue_is_idempotent_same_item_id_not_duplicated():
    outbox = Outbox()
    outbox.enqueue("order-1", {"x": 1})
    outbox.enqueue("order-1", {"x": 1})  # نفس المعرف مرتين
    assert outbox.counts_by_status()[OutboxStatus.PENDING.value] == 1


def test_happy_path_confirmed_success_reaches_done():
    """القبول: 'لا تُسجّل done إلا بعد إرسال فعلي وتأكيد معتبر'."""
    outbox = Outbox()
    outbox.enqueue("order-1", {"amount": 100})
    dispatched = []

    def dispatch(payload):
        dispatched.append(payload)
        return DispatchResult(DispatchOutcome.CONFIRMED_SUCCESS, external_reference="pos-ref-1")

    result = run_dispatch_cycle(outbox, "worker-1", batch_size=10, dispatch_fn=dispatch)
    assert result == {"claimed": 1, "done": 1, "awaiting_confirmation": 0, "failed": 0}
    assert outbox.get("order-1").status == OutboxStatus.DONE
    assert dispatched == [{"amount": 100}]


def test_confirmed_failure_does_not_reach_done_goes_to_retry():
    outbox = Outbox()
    outbox.enqueue("order-1", {"x": 1})

    def dispatch(payload):
        return DispatchResult(DispatchOutcome.CONFIRMED_FAILURE, detail="rejected by POS: item out of stock")

    result = run_dispatch_cycle(outbox, "worker-1", batch_size=10, dispatch_fn=dispatch)
    assert result["failed"] == 1
    assert outbox.get("order-1").status != OutboxStatus.DONE
    assert outbox.get("order-1").status == OutboxStatus.PENDING  # سيُعاد المحاولة


def test_connection_drop_after_send_does_not_mark_done_goes_to_awaiting_confirmation():
    """القبول حرفيًا: 'معالجة انقطاع الاتصال بعد الاستلام' — إرسال محتمل
    نجح فعليًا عند الطرف الآخر لكن الرد ضاع. **لا يُسجَّل done صامتًا هنا
    ولا يُصنَّف فشلًا يستحق إعادة إرسال أعمى** — حالة ثالثة صريحة."""
    outbox = Outbox()
    outbox.enqueue("order-1", {"x": 1})

    def dispatch(payload):
        return DispatchResult(DispatchOutcome.UNKNOWN_NEEDS_QUERY, external_reference="pos-ref-unknown")

    result = run_dispatch_cycle(outbox, "worker-1", batch_size=10, dispatch_fn=dispatch)
    assert result["awaiting_confirmation"] == 1
    assert result["done"] == 0  # الأهم: صفر نجاح صامت
    item = outbox.get("order-1")
    assert item.status == OutboxStatus.AWAITING_CONFIRMATION
    assert item.external_reference == "pos-ref-unknown"


def test_query_cycle_resolves_awaiting_confirmation_to_done_without_resending():
    """يثبت أن حل حالة awaiting_confirmation يتم بالاستعلام (query_fn) لا
    بإعادة استدعاء dispatch_fn — منع تكرار الأثر الخارجي بنيويًا (dispatch_fn
    غير مُمرَّرة لهذه الدورة إطلاقًا، فلا يمكن استدعاؤها بالخطأ)."""
    outbox = Outbox()
    outbox.enqueue("order-1", {"x": 1})
    run_dispatch_cycle(outbox, "worker-1", 10, lambda p: DispatchResult(
        DispatchOutcome.UNKNOWN_NEEDS_QUERY, external_reference="ref-1"), now=0.0)

    def query(item):
        assert item.external_reference == "ref-1"  # الاستعلام يستخدم المرجع المحفوظ
        return DispatchResult(DispatchOutcome.CONFIRMED_SUCCESS)

    result = run_query_cycle(outbox, "worker-1", 10, query_fn=query, now=10.0)
    assert result["done"] == 1
    assert outbox.get("order-1").status == OutboxStatus.DONE


def test_query_cycle_still_inconclusive_reschedules_with_backoff_then_dead_letters():
    """استعلام متكرر لا يحسم الأمر — إعادة جدولة بتأخير تصاعدي، ثم فشل
    نهائي بعد سقف محاولات الاستعلام (لا انتظار أبدي لتأكيد لن يصل)."""
    outbox = Outbox()
    item = outbox.enqueue("order-1", {"x": 1})
    item.max_query_attempts = 3
    run_dispatch_cycle(outbox, "worker-1", 10, lambda p: DispatchResult(
        DispatchOutcome.UNKNOWN_NEEDS_QUERY, external_reference="ref-1"), now=0.0)

    now = 10.0
    for _ in range(3):
        run_query_cycle(outbox, "worker-1", 10, lambda item: DispatchResult(DispatchOutcome.UNKNOWN_NEEDS_QUERY),
                         now=now)
        now = outbox.get("order-1").next_query_at + 1

    assert outbox.get("order-1").status == OutboxStatus.DEAD_LETTER


def test_query_cycle_never_calls_dispatch_fn_type_signature_isolation():
    """تأكيد إضافي: run_query_cycle لا يقبل dispatch_fn أصلًا كمعامل —
    استحالة بنيوية لاستدعاء إرسال جديد بالخطأ أثناء استعلام."""
    import inspect
    sig = inspect.signature(run_query_cycle)
    assert "dispatch_fn" not in sig.parameters
    assert "query_fn" in sig.parameters


def test_worker_stops_after_claim_before_ack_item_becomes_reclaimable_after_timeout():
    """القبول حرفيًا: توقف العامل قبل الإرسال وبعده واستئنافه."""
    outbox = Outbox(stuck_processing_timeout_seconds=10.0)
    outbox.enqueue("order-1", {"x": 1})
    outbox.claim_batch("crashed-worker", batch_size=10, now=0.0)
    assert outbox.get("order-1").status == OutboxStatus.PROCESSING

    still_stuck = outbox.claim_batch("worker-2", batch_size=10, now=5.0)
    assert still_stuck == []

    recovered = outbox.claim_batch("worker-2", batch_size=10, now=20.0)
    assert recovered == []
    assert outbox.get("order-1").status == OutboxStatus.AWAITING_CONFIRMATION
    assert outbox.claim_for_query("query-worker", 10, now=20.0)[0].item_id == "order-1"


def test_dispatch_failure_retries_with_backoff_then_dead_letters():
    outbox = Outbox()
    item = outbox.enqueue("order-1", {"x": 1})
    item.max_attempts = 3
    now = 0.0

    def always_fails(payload):
        return DispatchResult(DispatchOutcome.CONFIRMED_FAILURE, detail="always fails")

    for _ in range(3):
        result = run_dispatch_cycle(outbox, "worker-1", batch_size=10, dispatch_fn=always_fails, now=now)
        assert result["claimed"] == 1
        now = outbox.get("order-1").next_retry_at if outbox.get("order-1").next_retry_at else now + 1000

    assert outbox.get("order-1").status == OutboxStatus.DEAD_LETTER
    assert outbox.get("order-1").attempt_count == 3


def test_exception_in_dispatch_fn_requires_query_not_resend():
    outbox = Outbox()
    outbox.enqueue("order-1", {"x": 1})

    def raises(payload):
        raise ConnectionError("network down")

    result = run_dispatch_cycle(outbox, "worker-1", batch_size=10, dispatch_fn=raises)
    assert result["awaiting_confirmation"] == 1
    assert result["failed"] == 0
    assert outbox.get("order-1").status == OutboxStatus.AWAITING_CONFIRMATION
    assert outbox.claim_batch("another-worker", 10) == []


def test_invalid_dispatch_result_never_triggers_blind_retry():
    outbox = Outbox()
    outbox.enqueue("invalid-result", {})
    result = run_dispatch_cycle(outbox, "worker", 10, lambda payload: None)
    assert result["awaiting_confirmation"] == 1
    assert outbox.claim_batch("retry-worker", 10) == []


def test_20_concurrent_workers_never_claim_the_same_item_twice():
    outbox = Outbox()
    for i in range(20):
        outbox.enqueue(f"order-{i}", {"n": i})

    def worker(worker_num):
        claimed = outbox.claim_batch(f"worker-{worker_num}", batch_size=5)
        return [it.item_id for it in claimed]

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
        results = list(ex.map(worker, range(20)))

    all_claimed = [item_id for batch in results for item_id in batch]
    assert len(all_claimed) == len(set(all_claimed)) == 20


def test_backoff_grows_and_is_capped():
    assert exponential_backoff_seconds(0) == 1.0
    assert exponential_backoff_seconds(1) == 2.0
    assert exponential_backoff_seconds(2) == 4.0
    assert exponential_backoff_seconds(20) == 300.0


def test_batch_size_limits_how_many_are_claimed_at_once():
    outbox = Outbox()
    for i in range(10):
        outbox.enqueue(f"order-{i}", {})
    claimed = outbox.claim_batch("worker-1", batch_size=3)
    assert len(claimed) == 3
    assert outbox.counts_by_status()[OutboxStatus.PENDING.value] == 7


# ---------------------------------------------------------------------------
# الدليل الأهم: تكامل حقيقي فعلي مع خادم HTTP حقيقي (لا محاكاة نظرية)
# ---------------------------------------------------------------------------

def test_outbox_with_real_mock_pos_http_server_register_then_drop_response():
    """يعيد إنتاج بالضبط سيناريو
    tools/mock_pos/test_mock_pos.py::test_pos_registers_then_drops_response_client_must_query_not_blind_retry
    لكن **عبر دورة Outbox الكاملة** (dispatch → awaiting_confirmation →
    query → done)، ضد خادم HTTP حقيقي فعليًا يعمل على منفذ عشوائي حقيقي —
    ليس محاكاة، اتصال TCP حقيقي بقطع اتصال حقيقي بعد كتابة الاستجابة."""
    import threading
    import urllib.request
    import urllib.error
    import json as json_mod
    from mock_pos_service import make_server, reset_state

    reset_state()
    srv = make_server()
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    try:
        outbox = Outbox()
        outbox.enqueue("order-1", {"external_order_id": "EXT-OUTBOX-1", "total_minor_units": 500})

        def dispatch_to_real_pos(payload):
            """يحاكي عميل حقيقي يرسل، ثم "يفقد" الاتصال بالرد (نفس ما
            تختبره mock_pos_service.py عبر /_test/drop_next_response) —
            النتيجة الحقيقية: الطلب سُجِّل فعليًا عند POS، لكن العميل لا
            يعرف ذلك. إصلاح ذاتي أثناء الكتابة: drop_next_response ليست
            دالة بايثون قابلة للاستيراد كما افترضت مسودة أولى من هذا
            الاختبار — هي نقطة HTTP فعلية (POST /_test/drop_next_response)،
            صححتها هنا لتطابق الواجهة الحقيقية فعليًا كما في
            tools/mock_pos/test_mock_pos.py."""
            drop_req = urllib.request.Request(base + "/_test/drop_next_response", data=b"{}", method="POST")
            urllib.request.urlopen(drop_req, timeout=2)
            data = json_mod.dumps(payload).encode()
            req = urllib.request.Request(base + "/orders", data=data, method="POST",
                                          headers={"Content-Type": "application/json",
                                                   "Idempotency-Key": "outbox-key-1"})
            try:
                urllib.request.urlopen(req, timeout=2)
                return DispatchResult(DispatchOutcome.CONFIRMED_SUCCESS)
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                # الاتصال انقطع فعليًا — لا نعرف هل سجّل الطرف الآخر أم لا
                return DispatchResult(DispatchOutcome.UNKNOWN_NEEDS_QUERY,
                                       external_reference=payload["external_order_id"])

        dispatch_result = run_dispatch_cycle(outbox, "worker-1", 10, dispatch_fn=dispatch_to_real_pos, now=0.0)
        assert dispatch_result["done"] == 0  # لم يُسجَّل نجاح بلا تأكيد حقيقي
        assert dispatch_result["awaiting_confirmation"] == 1
        assert outbox.get("order-1").status == OutboxStatus.AWAITING_CONFIRMATION

        def query_real_pos(item):
            """الاستعلام الحقيقي — لا إعادة إرسال، فقط GET للتحقق."""
            ext_id = item.external_reference
            try:
                with urllib.request.urlopen(base + f"/orders/{ext_id}", timeout=2) as resp:
                    if resp.status == 200:
                        return DispatchResult(DispatchOutcome.CONFIRMED_SUCCESS)
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return DispatchResult(DispatchOutcome.UNKNOWN_NEEDS_QUERY, detail="not found yet")
            return DispatchResult(DispatchOutcome.UNKNOWN_NEEDS_QUERY)

        query_result = run_query_cycle(outbox, "worker-1", 10, query_fn=query_real_pos, now=100.0)
        assert query_result["done"] == 1  # الاستعلام أثبت أن POS سجّل الطلب فعليًا
        assert outbox.get("order-1").status == OutboxStatus.DONE
    finally:
        srv.shutdown()
