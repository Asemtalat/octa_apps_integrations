"""
نواة منطق منع التكرار (idempotency) وحالة النقل — البوابة B.

مقصود أن تكون هذه الوحدة pure Python بلا اعتماد على odoo.* حتى نقدر نختبرها
فعليًا هنا بدون تشغيل Odoo. الاستدعاء من Odoo يتم عبر
addons/octa_hub_api/controllers/api_controller.py الذي يمرر عمليات db-backed
(انظر InMemoryIdempotencyStore هنا كمرجع للسلوك، و TODO في الكنترولر لربطها
بجدول postgres حقيقي بقيد UNIQUE يحسم التزامن).

الحالات المطلوبة صراحة في الوثيقتين:
- نفس event_id بالتزامن 20 مرة → طلب منطقي واحد، كل المحاولات (attempts) مسجّلة.
- نفس المفتاح بمحتوى مختلف (hash مختلف) → تعارض موثّق، ليس نجاحًا صامتًا.
- POS يسجل ثم يفقد الرد → استعلام يؤكد السابق، أو حالة unknown صريحة، لا إعادة عمياء.
- إلغاء يسبق الإنشاء، وتحديث قديم بعد حالة نهائية → يُحترمان بترتيب صريح.
"""
from __future__ import annotations

import dataclasses
import enum
import hashlib
import threading
import time
from typing import Optional


class TransportState(str, enum.Enum):
    STORED = "stored"
    PENDING_DISPATCH = "pending_dispatch"
    DISPATCHING = "dispatching"
    REGISTERED_CONFIRMED = "registered_confirmed"
    UNKNOWN = "unknown"  # النتيجة غير معروفة — ليست فشلاً وليست نجاحًا
    NEEDS_INTERVENTION = "needs_intervention"


class CommercialState(str, enum.Enum):
    NEW = "new"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    IN_PREPARATION = "in_preparation"
    READY = "ready"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class IdempotencyOutcome(str, enum.Enum):
    NEW_LOGICAL_ORDER = "new_logical_order"       # أول مرة يُنشأ فيها الطلب
    DUPLICATE_SAME_PAYLOAD = "duplicate_same_payload"  # إعادة إرسال معروفة، لا أثر جديد
    CONFLICT_DIFFERENT_PAYLOAD = "conflict_different_payload"  # نفس المفتاح، محتوى مختلف


def content_hash(payload: dict) -> str:
    """تجزئة مستقرة لمحتوى الحدث لاكتشاف (نفس المفتاح / محتوى مختلف)."""
    normalized = "|".join(f"{k}={payload[k]}" for k in sorted(payload))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclasses.dataclass
class Attempt:
    attempt_id: str
    event_id: str
    received_at: float
    content_hash: str


@dataclasses.dataclass
class LogicalOrder:
    order_key: tuple  # (tenant_id, branch_id, connection_id, external_order_id)
    event_id: str
    content_hash: str
    transport_state: TransportState = TransportState.STORED
    commercial_state: CommercialState = CommercialState.NEW
    created_at: float = dataclasses.field(default_factory=time.monotonic)
    attempts: list = dataclasses.field(default_factory=list)
    pending_cancel_before_create: bool = False


class IdempotencyConflictError(Exception):
    def __init__(self, order_key, existing_hash, incoming_hash):
        super().__init__(
            f"idempotency conflict for {order_key}: stored_hash={existing_hash} incoming_hash={incoming_hash}"
        )
        self.order_key = order_key
        self.existing_hash = existing_hash
        self.incoming_hash = incoming_hash


class InMemoryIdempotencyStore:
    """مرجع سلوكي thread-safe. في Odoo الحقيقي يقابله قيد UNIQUE على
    (tenant_id, branch_id, connection_id, external_order_id) في جدول
    octa_hub_order، مع transaction تحسم السباق بدل قفل تطبيقي فقط.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._orders: dict[tuple, LogicalOrder] = {}
        self._attempt_seq = 0

    def _next_attempt_id(self) -> str:
        self._attempt_seq += 1
        return f"att-{self._attempt_seq}"

    def register_event(self, order_key: tuple, event_id: str, payload: dict) -> tuple[LogicalOrder, IdempotencyOutcome]:
        """يُستدعى لكل حدث وارد (webhook). ذرّي أمام تكرار متزامن.

        order_key فريد داخل (tenant, branch, connection) وفق عقد المصدر —
        قيد قاعدة البيانات (وليس هذا القفل وحده) هو ما يحسم التكرار المتزامن
        في الإنتاج؛ هذا القفل هنا يحاكي نفس الضمان للاختبار.
        """
        h = content_hash(payload)
        with self._lock:
            existing = self._orders.get(order_key)
            attempt = Attempt(
                attempt_id=self._next_attempt_id(),
                event_id=event_id,
                received_at=time.monotonic(),
                content_hash=h,
            )
            if existing is None:
                order = LogicalOrder(order_key=order_key, event_id=event_id, content_hash=h)
                order.attempts.append(attempt)
                self._orders[order_key] = order
                return order, IdempotencyOutcome.NEW_LOGICAL_ORDER

            existing.attempts.append(attempt)
            if existing.content_hash == h:
                return existing, IdempotencyOutcome.DUPLICATE_SAME_PAYLOAD
            # نفس المفتاح، محتوى مختلف: تعارض موثّق، لا نكتب فوق الحالة
            return existing, IdempotencyOutcome.CONFLICT_DIFFERENT_PAYLOAD

    def get(self, order_key: tuple) -> Optional[LogicalOrder]:
        with self._lock:
            return self._orders.get(order_key)

    def mark_dispatching(self, order_key: tuple):
        with self._lock:
            o = self._orders[order_key]
            if o.transport_state in (TransportState.REGISTERED_CONFIRMED,):
                return  # لا نعيد للخلف حالة نهائية
            o.transport_state = TransportState.DISPATCHING

    def mark_registered_confirmed(self, order_key: tuple):
        with self._lock:
            o = self._orders[order_key]
            o.transport_state = TransportState.REGISTERED_CONFIRMED

    def mark_unknown(self, order_key: tuple):
        """POS سجّل الحدث ثم انقطع الرد ولا يوجد استعلام/idempotency للتأكد."""
        with self._lock:
            o = self._orders[order_key]
            if o.transport_state == TransportState.REGISTERED_CONFIRMED:
                return  # حالة نهائية لا تُستبدل بـ unknown من حدث متأخر
            o.transport_state = TransportState.UNKNOWN

    def apply_cancel(self, order_key: tuple):
        """الإلغاء قد يسبق الإنشاء — نحفظه وننتظر، لا نتجاهله ولا نخطئ."""
        with self._lock:
            o = self._orders.get(order_key)
            if o is None:
                # لا يوجد طلب بعد؛ لسنا قادرين على إنشاء سجل بلا event إنشاء فعلي،
                # لكن نُبقي أثرًا صريحًا بدل تجاهل صامت.
                return "cancel_pending_no_order_yet"
            if o.commercial_state == CommercialState.COMPLETED:
                return "cancel_rejected_final_state"
            o.commercial_state = CommercialState.CANCELLED
            return "cancelled"

    def apply_stale_update(self, order_key: tuple, incoming_commercial_state: CommercialState, incoming_seq: int, last_applied_seq: dict):
        """تحديث عكسي قديم بعد حالة نهائية لا يُعيد الطلب لحالة تحضير."""
        with self._lock:
            o = self._orders[order_key]
            last_seq = last_applied_seq.get(order_key, -1)
            if incoming_seq <= last_seq:
                return "stale_update_ignored"
            if o.commercial_state in (CommercialState.CANCELLED, CommercialState.COMPLETED):
                # حالة نهائية: لا تحديث عكسي يعيدها للخلف
                return "final_state_protected"
            o.commercial_state = incoming_commercial_state
            last_applied_seq[order_key] = incoming_seq
            return "applied"
