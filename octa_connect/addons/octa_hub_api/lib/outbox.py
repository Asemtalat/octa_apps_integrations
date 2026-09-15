"""
نمط Outbox حقيقي (R13، Gate B).

إصلاح حرج (طلب صريح: "أصلح أولًا النجاح الوهمي في العامل"): النسخة
السابقة كانت تعرّف `dispatch_fn` بعقد Boolean بسيط (`Callable[[dict], bool]`)
— هذا **لا يمثّل واقع الشبكة**: لا يوجد مكان فيه لتمثيل "أرسلنا فعليًا لكن
انقطع الاتصال قبل أن نستلم الرد، فلا نعرف هل استلم الطرف الآخر أم لا".
الكود المستدعي في Odoo (`models/outbox_item.py::run_worker_batch`) كان
يستغل هذا النقص فعليًا: كان يسجّل `done` **بلا أي استدعاء إرسال حقيقي
إطلاقًا** — نجاح وهمي حرفي، أسوأ من مجرد ثغرة نظرية.

الإصلاح: عقد ثلاثي الحالة (`DispatchOutcome`) + حالة outbox جديدة
(`AWAITING_CONFIRMATION`) + دورة استعلام منفصلة (`run_query_cycle`) تسأل
الطرف الآخر "هل استلمت هذا فعلًا؟" بدل إعادة الإرسال العمياء عند انقطاع
الاتصال بعد الاستلام المحتمل — بالضبط السيناريو الذي تختبره
`tools/mock_pos/test_mock_pos.py::test_pos_registers_then_drops_response...`
والذي يُعاد استخدامه هنا حرفيًا كدليل تكامل حقيقي (انظر
`test_outbox_with_real_mock_pos_http_server` أدناه) — لا محاكاة نظرية فقط.

منع التكرار: `dispatch_fn`/`query_fn` الحقيقيان (عند الربط بموصل فعلي)
يستخدمان idempotency-key حقيقيًا يمر عبر `lib/idempotency.py` المُختبَرة
(8/8 PASS) — هذا الملف لا يعيد تنفيذ ذلك المنطق، يفترض أن dispatch_fn/
query_fn المُمرَّرتين تلتزمان به.
"""
from __future__ import annotations

import dataclasses
import enum
import threading
import time
from typing import Callable, Optional


class OutboxStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    AWAITING_CONFIRMATION = "awaiting_confirmation"  # جديد: أُرسل فعليًا، لا تأكيد بعد
    DONE = "done"
    DEAD_LETTER = "dead_letter"


class DispatchOutcome(str, enum.Enum):
    CONFIRMED_SUCCESS = "confirmed_success"      # إرسال فعلي + تأكيد معتبر من الطرف الآخر
    CONFIRMED_FAILURE = "confirmed_failure"      # رفض صريح مؤكَّد من الطرف الآخر
    UNKNOWN_NEEDS_QUERY = "unknown_needs_query"  # انقطع الاتصال بعد إرسال محتمل — لا نعرف بعد


@dataclasses.dataclass(frozen=True)
class DispatchResult:
    outcome: DispatchOutcome
    external_reference: Optional[str] = None  # معرف العملية عند الطرف الآخر، لدعم الاستعلام لاحقًا
    detail: str = ""


@dataclasses.dataclass
class OutboxItem:
    item_id: str
    payload: dict
    status: OutboxStatus = OutboxStatus.PENDING
    attempt_count: int = 0
    max_attempts: int = 5
    query_attempt_count: int = 0
    max_query_attempts: int = 10  # سقف لمحاولات الاستعلام — لا انتظار لانهائي لتأكيد لن يصل أبدًا
    next_retry_at: float = 0.0
    next_query_at: float = 0.0
    external_reference: Optional[str] = None
    claimed_by: Optional[str] = None
    claimed_at: Optional[float] = None
    created_at: float = dataclasses.field(default_factory=time.monotonic)
    last_error: Optional[str] = None


def exponential_backoff_seconds(attempt_count: int, base: float = 1.0, cap: float = 300.0) -> float:
    """تأخير تصاعدي محدود بسقف أعلى — لا انتظار لانهائي التصاعد."""
    return min(base * (2 ** attempt_count), cap)


class Outbox:
    """مخزن Outbox — في Odoo الفعلي يقابله جدول `octa.hub.outbox.item` دائم
    (models/outbox_item.py)؛ هذا مرجع سلوكي thread-safe مُختبَر بمعزل عن Odoo."""

    def __init__(self, stuck_processing_timeout_seconds: float = 300.0):
        self._lock = threading.Lock()
        self._items: dict[str, OutboxItem] = {}
        self.stuck_processing_timeout_seconds = stuck_processing_timeout_seconds

    def enqueue(self, item_id: str, payload: dict) -> OutboxItem:
        with self._lock:
            if item_id in self._items:
                return self._items[item_id]  # idempotent enqueue — لا تكرار عنصر لنفس المعرف
            item = OutboxItem(item_id=item_id, payload=payload)
            self._items[item_id] = item
            return item

    def _reclaim_stuck_processing_items(self, now: float):
        """توقف العامل بعد claim وقبل تسجيل النتيجة — العنصر يبقى processing
        للأبد بلا هذا. **لا يشمل AWAITING_CONFIRMATION عمدًا** — عنصر
        بانتظار تأكيد ليس "عالقًا"، إنه ينتظر دورة استعلام مجدولة بوعي."""
        for item in self._items.values():
            if (item.status == OutboxStatus.PROCESSING and item.claimed_at is not None
                    and now - item.claimed_at > self.stuck_processing_timeout_seconds):
                item.status = OutboxStatus.PENDING
                item.claimed_by = None
                item.claimed_at = None

    def claim_batch(self, worker_id: str, batch_size: int, now: Optional[float] = None) -> list[OutboxItem]:
        """يحاكي `SELECT ... FOR UPDATE SKIP LOCKED` — للإرسال الأولي فقط
        (PENDING). لا يأخذ عناصر AWAITING_CONFIRMATION — تلك عبر
        `claim_for_query` المنفصلة."""
        now = now if now is not None else time.monotonic()
        with self._lock:
            self._reclaim_stuck_processing_items(now)
            eligible = [
                it for it in self._items.values()
                if it.status == OutboxStatus.PENDING and it.next_retry_at <= now
            ]
            eligible.sort(key=lambda it: it.created_at)
            claimed = eligible[:batch_size]
            for item in claimed:
                item.status = OutboxStatus.PROCESSING
                item.claimed_by = worker_id
                item.claimed_at = now
            return list(claimed)

    def claim_for_query(self, worker_id: str, batch_size: int, now: Optional[float] = None) -> list[OutboxItem]:
        """يطالب بعناصر AWAITING_CONFIRMATION المستحقة استعلامًا الآن."""
        now = now if now is not None else time.monotonic()
        with self._lock:
            eligible = [
                it for it in self._items.values()
                if it.status == OutboxStatus.AWAITING_CONFIRMATION and it.next_query_at <= now
            ]
            eligible.sort(key=lambda it: it.created_at)
            return eligible[:batch_size]

    def mark_done(self, item_id: str):
        """**لا يُستدعى إلا بعد `DispatchOutcome.CONFIRMED_SUCCESS` فعليًا**
        — هذا هو الإصلاح الجوهري: لا مسار آخر في هذا الملف يصل لـDONE."""
        with self._lock:
            item = self._items[item_id]
            item.status = OutboxStatus.DONE
            item.claimed_by = None

    def mark_awaiting_confirmation(self, item_id: str, external_reference: Optional[str],
                                    now: Optional[float] = None):
        now = now if now is not None else time.monotonic()
        with self._lock:
            item = self._items[item_id]
            item.status = OutboxStatus.AWAITING_CONFIRMATION
            item.external_reference = external_reference
            item.next_query_at = now + 5.0  # أول استعلام بعد فترة قصيرة، ثم تصاعدي
            item.claimed_by = None

    def mark_failed(self, item_id: str, now: Optional[float] = None, error: str = ""):
        now = now if now is not None else time.monotonic()
        with self._lock:
            item = self._items[item_id]
            item.attempt_count += 1
            item.last_error = error
            if item.attempt_count >= item.max_attempts:
                item.status = OutboxStatus.DEAD_LETTER
                item.claimed_by = None
                return
            item.status = OutboxStatus.PENDING
            item.next_retry_at = now + exponential_backoff_seconds(item.attempt_count)
            item.claimed_by = None

    def mark_query_inconclusive(self, item_id: str, now: Optional[float] = None, error: str = ""):
        """الاستعلام نفسه لم يحسم الأمر بعد (لا يزال unknown) — يُعاد جدولة
        استعلام لاحق بتأخير تصاعدي، مع سقف يمنع الانتظار الأبدي."""
        now = now if now is not None else time.monotonic()
        with self._lock:
            item = self._items[item_id]
            item.query_attempt_count += 1
            item.last_error = error
            if item.query_attempt_count >= item.max_query_attempts:
                item.status = OutboxStatus.DEAD_LETTER
                item.claimed_by = None
                return
            item.status = OutboxStatus.AWAITING_CONFIRMATION
            item.next_query_at = now + exponential_backoff_seconds(item.query_attempt_count)

    def get(self, item_id: str) -> Optional[OutboxItem]:
        with self._lock:
            return self._items.get(item_id)

    def counts_by_status(self) -> dict:
        with self._lock:
            out = {s.value: 0 for s in OutboxStatus}
            for it in self._items.values():
                out[it.status.value] += 1
            return out


def run_dispatch_cycle(outbox: Outbox, worker_id: str, batch_size: int,
                        dispatch_fn: Callable[[dict], DispatchResult],
                        now: Optional[float] = None) -> dict:
    """دورة إرسال أولي. **لا مسار هنا يصل لـDONE إلا عبر CONFIRMED_SUCCESS
    الصريحة من dispatch_fn** — هذا هو الإصلاح الجوهري المطلوب."""
    now = now if now is not None else time.monotonic()
    claimed = outbox.claim_batch(worker_id, batch_size, now)
    done, awaiting, failed = 0, 0, 0
    for item in claimed:
        try:
            result = dispatch_fn(item.payload)
        except Exception as e:
            outbox.mark_failed(item.item_id, now, error=str(e))
            failed += 1
            continue
        if result.outcome == DispatchOutcome.CONFIRMED_SUCCESS:
            outbox.mark_done(item.item_id)
            done += 1
        elif result.outcome == DispatchOutcome.CONFIRMED_FAILURE:
            outbox.mark_failed(item.item_id, now, error=result.detail)
            failed += 1
        else:  # UNKNOWN_NEEDS_QUERY — انقطاع اتصال بعد إرسال محتمل
            outbox.mark_awaiting_confirmation(item.item_id, result.external_reference, now)
            awaiting += 1
    return {"claimed": len(claimed), "done": done, "awaiting_confirmation": awaiting, "failed": failed}


def run_query_cycle(outbox: Outbox, worker_id: str, batch_size: int,
                     query_fn: Callable[[OutboxItem], DispatchResult],
                     now: Optional[float] = None) -> dict:
    """دورة استعلام منفصلة تمامًا عن الإرسال — **تسأل، لا ترسل مجددًا**.
    هذا يمنع تكرار الأثر الخارجي عند انقطاع الاتصال بعد استلام محتمل من
    الطرف الآخر (السيناريو المطلوب صراحة)."""
    now = now if now is not None else time.monotonic()
    claimed = outbox.claim_for_query(worker_id, batch_size, now)
    done, still_unknown, failed = 0, 0, 0
    for item in claimed:
        try:
            result = query_fn(item)
        except Exception as e:
            outbox.mark_query_inconclusive(item.item_id, now, error=str(e))
            still_unknown += 1
            continue
        if result.outcome == DispatchOutcome.CONFIRMED_SUCCESS:
            outbox.mark_done(item.item_id)
            done += 1
        elif result.outcome == DispatchOutcome.CONFIRMED_FAILURE:
            outbox.mark_failed(item.item_id, now, error=result.detail)
            failed += 1
        else:
            outbox.mark_query_inconclusive(item.item_id, now, error=result.detail)
            still_unknown += 1
    return {"claimed": len(claimed), "done": done, "still_unknown": still_unknown, "failed": failed}
