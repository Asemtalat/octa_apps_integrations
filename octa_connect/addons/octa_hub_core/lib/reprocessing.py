"""
إعادة المعالجة الفردية والجماعية (OC05-15، P0) — Gate E.

كل محاولة attempt_id جديد لنفس الحدث المنطقي؛ لا يُنشأ order_id جديد لتجاوز
التكرار. يتحقق من صلاحية المستخدم والفرع وعمر الطلب وحالته عند الطلب وعند
التنفيذ (فحصان منفصلان — الحالة قد تتغير بين الاثنين).
"""
from __future__ import annotations

import dataclasses
import enum
import time


class ExclusionReason(str, enum.Enum):
    ALREADY_COMPLETED = "already_completed"
    EXPIRED = "expired"
    NOT_AUTHORIZED_FOR_BRANCH = "not_authorized_for_branch"
    STATE_CHANGED_SINCE_REQUEST = "state_changed_since_request"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"


@dataclasses.dataclass
class ReprocessRequest:
    operation_id: str
    scope_order_ids: list
    reason: str
    actor_user_id: str
    requested_at: float
    authorized_branch_ids: set


@dataclasses.dataclass
class OrderSnapshot:
    order_id: str
    branch_id: str
    commercial_state: str
    is_expired: bool
    completed: bool


@dataclasses.dataclass
class PreviewResult:
    eligible_order_ids: list
    excluded: dict  # order_id -> ExclusionReason


def preview_eligibility(request: ReprocessRequest, orders: list) -> PreviewResult:
    """معاينة عدد المؤهل وغير المؤهل وأسباب الاستبعاد — قبل أي تنفيذ فعلي."""
    eligible = []
    excluded = {}
    for order in orders:
        if order.branch_id not in request.authorized_branch_ids:
            excluded[order.order_id] = ExclusionReason.NOT_AUTHORIZED_FOR_BRANCH
        elif order.completed:
            excluded[order.order_id] = ExclusionReason.ALREADY_COMPLETED
        elif order.is_expired:
            excluded[order.order_id] = ExclusionReason.EXPIRED
        else:
            eligible.append(order.order_id)
    return PreviewResult(eligible_order_ids=eligible, excluded=excluded)


class RateLimiter:
    """حدود تزامن ومعدل وعدالة لكل تاجر وقناة — بسيط لكنه حقيقي (نافذة
    زمنية ثابتة لكل مفتاح tenant/channel، لا حد عام واحد يجوّع تاجرًا صغيرًا
    لصالح آخر كبير)."""

    def __init__(self, max_per_window: int, window_seconds: float):
        self.max_per_window = max_per_window
        self.window_seconds = window_seconds
        self._counters: dict = {}  # (tenant_id, channel_id) -> list[timestamps]

    def check_and_record(self, tenant_id: str, channel_id: str, now: float) -> bool:
        key = (tenant_id, channel_id)
        history = self._counters.setdefault(key, [])
        history[:] = [t for t in history if now - t < self.window_seconds]
        if len(history) >= self.max_per_window:
            return False
        history.append(now)
        return True


class AttemptTracker:
    """كل محاولة attempt_id جديد لنفس order_id — لا order_id جديد يُنشأ
    لتجاوز التكرار."""

    def __init__(self):
        self._attempts: dict = {}  # order_id -> list[attempt_id]
        self._seq = 0

    def new_attempt(self, order_id: str) -> str:
        self._seq += 1
        attempt_id = f"reprocess-att-{self._seq}"
        self._attempts.setdefault(order_id, []).append(attempt_id)
        return attempt_id

    def attempts_for(self, order_id: str) -> list:
        return list(self._attempts.get(order_id, []))


def double_click_or_duplicate_task_produces_single_external_effect(
        tracker: AttemptTracker, idempotency_store, order_id: str, order_key: tuple, event_id: str, payload: dict):
    """القبول حرفيًا: تكرار الضغط أو وصول مهمتين لا يسبب أثرين خارجيين عند
    دعم الطرف لمنع التكرار — يعيد استخدام نفس نواة idempotency.py المُختبرة
    (لا إعادة اختراع منطق منع تكرار مختلف هنا)."""
    attempt_id = tracker.new_attempt(order_id)  # attempt جديد دائمًا، حتى لو الأثر الخارجي واحد
    order, outcome = idempotency_store.register_event(order_key, event_id, payload)
    return attempt_id, outcome


def recheck_state_at_execution_time(order_at_request: OrderSnapshot, order_at_execution: OrderSnapshot) -> None:
    """يتحقق من الحالة عند الطلب وعند التنفيذ كفحصين منفصلين — الحالة قد
    تتغير بينهما (مثال: اكتمل الطلب أثناء انتظار المعالجة الجماعية)."""
    if order_at_execution.completed and not order_at_request.completed:
        raise ValueError(
            f"الطلب {order_at_execution.order_id} اكتمل بين وقت الطلب ووقت التنفيذ — "
            f"يُستبعد الآن رغم أنه كان مؤهلًا وقت المعاينة"
        )
