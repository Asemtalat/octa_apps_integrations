"""
رحلة الطلب وإثبات التسجيل (OC05-14، P0) — Gate E.

يفصل الاتجاه الأمامي (من التطبيق إلى نظام المطعم) عن العكسي (من نظام
المطعم رجوعًا للتطبيق) بمجموعتي أحداث مختلفتين تمامًا، بدل قائمة أحداث
واحدة مسطحة. كل توقيت له مصدر ودقة/ثقة صريحة — لا افتراض أن كل الأوقات
بنفس درجة الموثوقية.
"""
from __future__ import annotations

import dataclasses
import enum


class ForwardEvent(str, enum.Enum):
    SOURCE_CREATED = "source_created"
    HUB_RECEIVED = "hub_received"
    DURABLY_SAVED = "durably_saved"
    DISPATCH_STARTED = "dispatch_started"
    POS_RECEIVED = "pos_received"
    POS_REGISTERED = "pos_registered"
    CASHIER_DISPLAYED = "cashier_displayed"
    HUMAN_DECISION = "human_decision"


class ReverseEvent(str, enum.Enum):
    STATUS_SOURCE_AT = "status_source_at"
    HUB_RECEIVED = "hub_received"
    DISPATCH_STARTED = "dispatch_started"
    PROVIDER_ACKNOWLEDGED = "provider_acknowledged"


class TimestampConfidence(str, enum.Enum):
    HIGH = "high"          # مصدره الطرف المباشر، دقة موثقة
    MEDIUM = "medium"      # مُشتق أو مقارب
    LOW = "low"            # غير موثوق، يُعرض بتحذير
    UNAVAILABLE = "unavailable"  # لا يوجد — القسم 10: "غياب الحدث يعني unavailable لا صفرًا"


@dataclasses.dataclass(frozen=True)
class TracedTimestamp:
    event: object  # ForwardEvent أو ReverseEvent
    source: str
    received_at: float
    confidence: TimestampConfidence
    value: float | None = None  # None = unavailable فعليًا، ليس صفرًا


@dataclasses.dataclass
class OrderTrace:
    provider_order_id: str | None
    hub_order_id: str
    pos_order_id: str | None
    correlation_id: str
    forward_events: dict = dataclasses.field(default_factory=dict)   # ForwardEvent -> TracedTimestamp
    reverse_events: dict = dataclasses.field(default_factory=dict)   # ReverseEvent -> TracedTimestamp


class Http200IsNotPosRegistrationError(Exception):
    """القبول حرفيًا: HTTP 200 الذي يعني قبول الطابور لا يظهر كتسجيل POS."""


def record_http_ack(trace: OrderTrace, http_status: int, at: float) -> None:
    """يسجل قبول HTTP فقط — لا يضيف pos_registered أبدًا من هذا الحدث وحده،
    مهما كان http_status ناجحًا. القبول يجب أن يصل كحدث ForwardEvent.POS_REGISTERED
    منفصل من مصدر مختلف (استجابة POS الفعلية)."""
    if http_status not in (200, 201, 202):
        return
    # نتعمّد عدم كتابة أي شيء في forward_events هنا متعلق بـPOS —
    # ACK الطابور وتسجيل POS مفهومان منفصلان تمامًا؛ الدالة التالية توضح الفرق
    trace.forward_events.setdefault(
        ForwardEvent.HUB_RECEIVED,
        TracedTimestamp(ForwardEvent.HUB_RECEIVED, source="hub_queue_ack", received_at=at,
                         confidence=TimestampConfidence.HIGH, value=at),
    )


def assert_pos_registration_requires_explicit_event(trace: OrderTrace) -> bool:
    """يثبت أن قبول HTTP وحده (المسجَّل أعلاه) لا يجعل ForwardEvent.POS_REGISTERED
    موجودًا تلقائيًا — يجب أن يصل كحدث منفصل صريح."""
    return ForwardEvent.POS_REGISTERED not in trace.forward_events


def missing_event_is_unavailable_not_zero(trace: OrderTrace, event) -> TimestampConfidence:
    ts = trace.forward_events.get(event) or trace.reverse_events.get(event)
    if ts is None:
        return TimestampConfidence.UNAVAILABLE
    return ts.confidence


def snapshot_amounts_unaffected_by_later_catalog_change(order_snapshot_total: int,
                                                          current_catalog_price: int) -> int:
    """القبول حرفيًا: Snapشot المبالغ والأصناف لا يتغير بتعديل الكتالوج.
    يُرجع دائمًا snapshot المحفوظ وقت الطلب، بصرف النظر عن التغيير الحالي."""
    return order_snapshot_total  # current_catalog_price متعمَّد تجاهله — يوثّق القاعدة، لا يستخدمها


# إصلاح بعد مراجعة عاشرة (فحص تعارض الحقول/الحالات بين الموديولات):
# `octa_hub_core/models/order.py::OctaHubOrderEvent.event_type` (Gate A/B،
# حقل Odoo Selection فعلي بقيم مختلفة) وForwardEvent/ReverseEvent هنا
# (Gate E) يمثلان **نفس مفهوم أحداث دورة حياة الطلب** بمفردتين مختلفتين لم
# تُوحَّدا. OC05-21 ينص صراحة: "أعد استخدام الحقول المكافئة السليمة مع
# توثيق المطابقة بدل ازدواجها" — لذلك لا نُعيد تسمية حقل Odoo القائم (قد
# تكون له بيانات/migrations قائمة)، بل نوثّق التطابق هنا بشكل قابل للفحص
# الآلي بدل نثر تعليقات نثرية فقط.
FORWARD_EVENT_TO_ORDER_EVENT_TYPE = {
    ForwardEvent.SOURCE_CREATED: "app_created",
    ForwardEvent.HUB_RECEIVED: "hub_received",
    ForwardEvent.DURABLY_SAVED: "stored",
    ForwardEvent.DISPATCH_STARTED: "pos_dispatch_started",
    ForwardEvent.POS_RECEIVED: "pos_dispatch_started",  # لا مقابل منفصل حاليًا — نفس حقل الإرسال؛ فجوة موثّقة
    ForwardEvent.POS_REGISTERED: "pos_registration_confirmed",
    ForwardEvent.CASHIER_DISPLAYED: "cashier_seen",
    ForwardEvent.HUMAN_DECISION: "accepted_or_rejected",
}
REVERSE_EVENT_TO_ORDER_EVENT_TYPE = {
    ReverseEvent.STATUS_SOURCE_AT: "pos_update_received",
    ReverseEvent.HUB_RECEIVED: "pos_update_received",  # نفس الفجوة: لا حقل Odoo منفصل للاستقبال العكسي بعد
    ReverseEvent.DISPATCH_STARTED: "app_update_sent",
    ReverseEvent.PROVIDER_ACKNOWLEDGED: "external_confirmed",
}


def order_event_type_equivalent(event) -> str:
    """يُرجع قيمة `order.py::event_type` المكافئة — يُستخدم عند الربط
    الفعلي بدل اختراع قيم Odoo جديدة تكرر نفس المعنى."""
    if isinstance(event, ForwardEvent):
        return FORWARD_EVENT_TO_ORDER_EVENT_TYPE[event]
    if isinstance(event, ReverseEvent):
        return REVERSE_EVENT_TO_ORDER_EVENT_TYPE[event]
    raise TypeError(f"نوع حدث غير معروف: {type(event)}")
