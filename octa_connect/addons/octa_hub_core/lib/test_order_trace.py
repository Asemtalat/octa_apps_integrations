"""اختبارات RUN فعليًا لرحلة الطلب وإثبات التسجيل (OC05-14)."""
import os
from order_trace import (
    OrderTrace, ForwardEvent, ReverseEvent, TracedTimestamp, TimestampConfidence,
    record_http_ack, assert_pos_registration_requires_explicit_event,
    missing_event_is_unavailable_not_zero, snapshot_amounts_unaffected_by_later_catalog_change,
    FORWARD_EVENT_TO_ORDER_EVENT_TYPE, REVERSE_EVENT_TO_ORDER_EVENT_TYPE,
)


def _new_trace():
    return OrderTrace(provider_order_id="PROV-1", hub_order_id="HUB-1",
                       pos_order_id=None, correlation_id="corr-1")


def test_http_200_ack_does_not_create_pos_registered_event():
    """القبول حرفيًا: HTTP 200 الذي يعني قبول الطابور لا يظهر كتسجيل POS."""
    trace = _new_trace()
    record_http_ack(trace, http_status=200, at=1000.0)
    assert assert_pos_registration_requires_explicit_event(trace) is True
    assert ForwardEvent.POS_REGISTERED not in trace.forward_events


def test_pos_registered_requires_its_own_explicit_event():
    trace = _new_trace()
    record_http_ack(trace, http_status=200, at=1000.0)
    # التسجيل الفعلي يصل كحدث منفصل من مصدر مختلف (رد POS الحقيقي)
    trace.forward_events[ForwardEvent.POS_REGISTERED] = TracedTimestamp(
        ForwardEvent.POS_REGISTERED, source="pos_webhook", received_at=1005.0,
        confidence=TimestampConfidence.HIGH, value=1005.0,
    )
    assert ForwardEvent.POS_REGISTERED in trace.forward_events


def test_missing_event_is_unavailable_not_zero():
    """القسم 10 حرفيًا: غياب الحدث يعني unavailable لا صفرًا."""
    trace = _new_trace()
    confidence = missing_event_is_unavailable_not_zero(trace, ForwardEvent.CASHIER_DISPLAYED)
    assert confidence == TimestampConfidence.UNAVAILABLE


def test_forward_and_reverse_events_are_separate_namespaces():
    """HUB_RECEIVED موجود في كلا الاتجاهين بنفس الاسم لكن كمساحتين منفصلتين تمامًا."""
    trace = _new_trace()
    trace.forward_events[ForwardEvent.HUB_RECEIVED] = TracedTimestamp(
        ForwardEvent.HUB_RECEIVED, "app", 100.0, TimestampConfidence.HIGH, 100.0)
    trace.reverse_events[ReverseEvent.HUB_RECEIVED] = TracedTimestamp(
        ReverseEvent.HUB_RECEIVED, "pos", 200.0, TimestampConfidence.HIGH, 200.0)
    assert trace.forward_events[ForwardEvent.HUB_RECEIVED].value == 100.0
    assert trace.reverse_events[ReverseEvent.HUB_RECEIVED].value == 200.0  # لا تصادم


def test_snapshot_amount_ignores_current_catalog_price():
    """القبول حرفيًا: Snapshot المبالغ لا يتغير بتعديل الكتالوج لاحقًا."""
    original_total = 8500  # 85.00 SAR بوحدات صغرى وقت الطلب
    catalog_changed_later_to = 9000  # السعر تغيّر لاحقًا في الكتالوج
    assert snapshot_amounts_unaffected_by_later_catalog_change(original_total, catalog_changed_later_to) == 8500


def test_correlation_id_ties_provider_hub_and_pos_ids_together():
    trace = OrderTrace(provider_order_id="PROV-99", hub_order_id="HUB-42",
                        pos_order_id="POS-7", correlation_id="corr-xyz")
    assert trace.correlation_id == "corr-xyz"
    assert {trace.provider_order_id, trace.hub_order_id, trace.pos_order_id} == {"PROV-99", "HUB-42", "POS-7"}


def test_every_forward_and_reverse_event_has_documented_odoo_mapping():
    """اختبار جديد (مراجعة عاشرة): يثبت آليًا أن كل ForwardEvent/ReverseEvent
    له تطابق موثّق في order_event_type_equivalent — لا حدث بلا مقابل."""
    from order_trace import order_event_type_equivalent, ForwardEvent, ReverseEvent
    for event in ForwardEvent:
        assert order_event_type_equivalent(event)  # لا يرفع KeyError
    for event in ReverseEvent:
        assert order_event_type_equivalent(event)


def test_mapping_values_actually_match_order_py_odoo_field_choices():
    """يقرأ models/order.py الفعلي ويتأكد أن كل قيمة في الخريطة موجودة
    فعليًا كسلسلة نصية داخل تعريف event_type — يمنع انحراف الخريطة عن
    الحقل الحقيقي بصمت لو تغيّر أحدهما مستقبلًا دون تحديث الآخر."""
    order_py_path = os.path.join(os.path.dirname(__file__), "..", "models", "order.py")
    order_py_source = open(order_py_path, encoding="utf-8").read()
    for odoo_key in list(FORWARD_EVENT_TO_ORDER_EVENT_TYPE.values()) + list(REVERSE_EVENT_TO_ORDER_EVENT_TYPE.values()):
        assert f'"{odoo_key}"' in order_py_source, f"{odoo_key!r} غير موجود حرفيًا في order.py — الخريطة انحرفت عن الحقل الفعلي"
