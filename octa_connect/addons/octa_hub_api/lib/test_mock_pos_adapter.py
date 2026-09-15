"""اختبارات RUN فعليًا لمحوِّل mock_pos الحقيقي — خادم HTTP فعلي، لا محاكاة."""
import os
import sys
import threading

import pytest

from mock_pos_adapter import make_mock_pos_dispatch_fn, make_mock_pos_query_fn

_MOCK_POS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "tools", "mock_pos")
if _MOCK_POS_DIR not in sys.path:
    sys.path.insert(0, _MOCK_POS_DIR)


@pytest.fixture()
def live_server():
    from mock_pos_service import make_server, reset_state
    reset_state()
    srv = make_server()
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


class _FakeOutboxItem:
    """يحاكي حقول octa.hub.outbox.item التي تحتاجها query_fn فقط — لا Odoo هنا."""
    def __init__(self, external_reference):
        self.external_reference = external_reference


def test_dispatch_fn_real_success_against_live_server(live_server):
    dispatch = make_mock_pos_dispatch_fn(live_server)
    result = dispatch({"external_order_id": "EXT-ADAPTER-1", "total_minor_units": 1000})
    assert result["outcome"] == "confirmed_success"
    assert result["external_reference"] == "EXT-ADAPTER-1"


def test_dispatch_fn_missing_external_order_id_is_confirmed_failure(live_server):
    dispatch = make_mock_pos_dispatch_fn(live_server)
    result = dispatch({"total_minor_units": 500})  # بلا external_order_id
    assert result["outcome"] == "confirmed_failure"


def test_dispatch_fn_connection_drop_returns_unknown_needs_query(live_server):
    """الدليل المباشر لإصلاح 'النجاح الوهمي': محوِّل حقيقي يواجه انقطاع
    اتصال فعليًا يُرجع unknown_needs_query، لا نجاحًا ولا فشلًا مباشرين."""
    import urllib.request
    urllib.request.urlopen(live_server + "/_test/drop_next_response", data=b"{}", timeout=2)
    dispatch = make_mock_pos_dispatch_fn(live_server)
    result = dispatch({"external_order_id": "EXT-ADAPTER-DROP", "total_minor_units": 750})
    assert result["outcome"] == "unknown_needs_query"
    assert result["external_reference"] == "EXT-ADAPTER-DROP"


def test_query_fn_confirms_success_for_order_that_was_actually_registered(live_server):
    """يثبت المسار الكامل: إرسال ينقطع رده → استعلام لاحق يكتشف أن الطرف
    الآخر سجّل الطلب فعليًا رغم ضياع الرد الأول."""
    import urllib.request
    urllib.request.urlopen(live_server + "/_test/drop_next_response", data=b"{}", timeout=2)
    dispatch = make_mock_pos_dispatch_fn(live_server)
    dispatch_result = dispatch({"external_order_id": "EXT-ADAPTER-2", "total_minor_units": 900})
    assert dispatch_result["outcome"] == "unknown_needs_query"

    query = make_mock_pos_query_fn(live_server)
    fake_item = _FakeOutboxItem(external_reference=dispatch_result["external_reference"])
    query_result = query(fake_item)
    assert query_result["outcome"] == "confirmed_success"


def test_query_fn_for_order_that_never_registered_stays_unknown_not_false_failure(live_server):
    """طلب لم يُرسَل فعليًا أبدًا — 404 يعني 'غير موجود بعد'، ليس فشلًا
    مؤكَّدًا صريحًا (قد يصل لاحقًا لو كان هناك تأخر شبكي حقيقي)."""
    query = make_mock_pos_query_fn(live_server)
    fake_item = _FakeOutboxItem(external_reference="EXT-NEVER-SENT")
    result = query(fake_item)
    assert result["outcome"] == "unknown_needs_query"


def test_full_outbox_cycle_with_real_adapter_end_to_end(live_server):
    """الدليل الأشمل: يربط lib/outbox.py الحقيقية (لا Odoo) بالمحوِّل
    الحقيقي هنا، ضد خادم حقيقي، من الإدراج حتى done — إثبات كامل أن
    البنية بأكملها (لا أجزاء منعزلة فقط) تعمل صحيحًا معًا.

    إصلاح ذاتي أثناء الكتابة: مسودة أولى حمّلت outbox.py يدويًا عبر
    importlib.util.spec_from_file_location باسم وحدة مختلف ("outbox_e2e")
    بلا تسجيله في sys.modules — فشل فعليًا عند التشغيل (dataclasses تبحث
    عن الوحدة في sys.modules عبر cls.__module__ لحل تلميحات الأنواع).
    صُحِّح بالاستيراد العادي المباشر (outbox.py على نفس sys.path أصلًا،
    بنفس نمط كل ملفات هذا المشروع الأخرى) بدل إعادة اختراع تحميل الوحدات.
    """
    import outbox as outbox_mod

    ob = outbox_mod.Outbox()
    ob.enqueue("order-e2e-1", {"external_order_id": "EXT-E2E-1", "total_minor_units": 1200})

    import urllib.request
    urllib.request.urlopen(live_server + "/_test/drop_next_response", data=b"{}", timeout=2)
    raw_dispatch = make_mock_pos_dispatch_fn(live_server)
    raw_query = make_mock_pos_query_fn(live_server)

    def dispatch_fn_adapted(payload):
        r = raw_dispatch(payload)
        outcome_map = {
            "confirmed_success": outbox_mod.DispatchOutcome.CONFIRMED_SUCCESS,
            "confirmed_failure": outbox_mod.DispatchOutcome.CONFIRMED_FAILURE,
            "unknown_needs_query": outbox_mod.DispatchOutcome.UNKNOWN_NEEDS_QUERY,
        }
        return outbox_mod.DispatchResult(outcome_map[r["outcome"]], r.get("external_reference"), r.get("detail", ""))

    def query_fn_adapted(item):
        r = raw_query(item)
        outcome_map = {
            "confirmed_success": outbox_mod.DispatchOutcome.CONFIRMED_SUCCESS,
            "confirmed_failure": outbox_mod.DispatchOutcome.CONFIRMED_FAILURE,
            "unknown_needs_query": outbox_mod.DispatchOutcome.UNKNOWN_NEEDS_QUERY,
        }
        return outbox_mod.DispatchResult(outcome_map[r["outcome"]], detail=r.get("detail", ""))

    dispatch_result = outbox_mod.run_dispatch_cycle(ob, "worker-1", 10, dispatch_fn_adapted, now=0.0)
    assert dispatch_result["awaiting_confirmation"] == 1
    assert dispatch_result["done"] == 0

    query_result = outbox_mod.run_query_cycle(ob, "worker-1", 10, query_fn_adapted, now=100.0)
    assert query_result["done"] == 1
    assert ob.get("order-e2e-1").status == outbox_mod.OutboxStatus.DONE
