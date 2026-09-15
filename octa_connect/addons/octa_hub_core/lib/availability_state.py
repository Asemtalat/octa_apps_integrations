"""
التوفر المطلوب والمؤكد (OC05-11، P0) — Gate E.

الفرق الجوهري الذي يشترطه البند: desired_state (ما نريده) منفصل عن
confirmed_state (ما أكّده الطرف الخارجي فعليًا) — حالة قديمة ناجحة لا تثبت
نجاح طلب جديد. partial تعني اختلاف نتائج بين وجهات متعددة، وليست مجرد قيمة
Boolean ثالثة.
"""
from __future__ import annotations

import dataclasses
import enum
import time


class DisplayAvailability(str, enum.Enum):
    AVAILABLE_CONFIRMED = "available_confirmed"
    STOPPED_CONFIRMED = "stopped_confirmed"
    PENDING_CONFIRMATION = "pending_confirmation"
    FAILED = "failed"
    UNKNOWN = "unknown"
    STALE = "stale"
    UNSUPPORTED = "unsupported"


@dataclasses.dataclass
class AvailabilityRecord:
    branch_id: str
    channel_id: str
    item_id: str
    desired_state: bool  # True = متاح مطلوب، False = متوقف مطلوب
    confirmed_state: bool | None = None  # None = لم يتأكد بعد
    confirmation_source: str | None = None
    requested_at: float | None = None
    confirmed_at: float | None = None
    last_attempt_at: float | None = None
    expires_at: float | None = None  # لتوقف مؤقت له مدة صلاحية
    version: int = 1
    supported: bool = True


def display_state(record: AvailabilityRecord, now: float | None = None) -> DisplayAvailability:
    """يحسب حالة العرض وفق القواعد الحرفية في البند — لا Boolean ثالث بسيط."""
    now = now if now is not None else time.time()

    if not record.supported:
        return DisplayAvailability.UNSUPPORTED

    if record.confirmed_state is None:
        return DisplayAvailability.PENDING_CONFIRMATION

    # توقف مؤقت منتهي الصلاحية دون سياسة تجديد صريحة = بيانات قديمة، لا
    # نفترض إتاحة تلقائية اعتمادًا على انقضاء الوقت وحده (القبول ينص عليه)
    if record.expires_at is not None and now > record.expires_at:
        return DisplayAvailability.STALE

    if record.confirmed_state == record.desired_state:
        return DisplayAvailability.AVAILABLE_CONFIRMED if record.confirmed_state else DisplayAvailability.STOPPED_CONFIRMED

    return DisplayAvailability.FAILED  # أُكِّد بحالة مخالفة لما طُلب


def apply_confirmation(record: AvailabilityRecord, confirmed_state: bool, source: str,
                        confirmed_at: float, incoming_version: int) -> AvailabilityRecord:
    """يطبّق تأكيدًا واردًا مع حماية من الكتابة فوق نسخة أحدث (stale update).
    القبول: حدث تأكيد قديم لا يكتب فوق نسخة أحدث."""
    if incoming_version <= record.version:
        return record  # تجاهل صامت للتحديث القديم — سيناريو طبيعي شائع (تأخر شبكي)، لا استثناء
    return dataclasses.replace(
        record, confirmed_state=confirmed_state, confirmation_source=source,
        confirmed_at=confirmed_at, version=incoming_version,
    )


def aggregate_across_destinations(records: list) -> str:
    """partial تعني اختلاف النتائج بين وجهات — وليست Boolean ثالث. القبول:
    نجاح وجهة وانقطاع الأخرى ينتج partial وpending/unknown للثانية."""
    states = {display_state(r) for r in records}
    confirmed_states = {s for s in states if s in (DisplayAvailability.AVAILABLE_CONFIRMED, DisplayAvailability.STOPPED_CONFIRMED)}
    pending_or_unknown = {s for s in states if s in (DisplayAvailability.PENDING_CONFIRMATION, DisplayAvailability.UNKNOWN, DisplayAvailability.FAILED)}
    if confirmed_states and pending_or_unknown:
        return "partial"
    if len(states) == 1:
        return next(iter(states)).value
    return "partial"  # حالات متعددة مختلطة = partial أيضًا، لا نختار واحدة عشوائيًا
