"""
مواعيد التشغيل والتوقف (القسم 5، مراجعة بوابة هنقرستيشن) — Gate جديد.
لم يكن يوجد أي شيء لهذا إطلاقًا قبل هذه الجولة.

يفصل صراحة بين ثلاث حالات مختلفة تمامًا لا تُخلَط:
- مغلق حسب الجدول (desired=closed لأن الجدول يقول كذلك الآن)
- متوقف أثناء التشغيل (الجدول يقول مفتوح، لكن التاجر أوقفه يدويًا أو تعطّل)
- غير معروف (لا تأكيد وصل من التطبيق لحالة الفتح الفعلية)
"""
from __future__ import annotations

import dataclasses
import datetime
import enum


class DayStatus(str, enum.Enum):
    OPEN_SCHEDULED = "open_scheduled"          # الجدول يقول مفتوح، ومؤكَّد مفتوح فعليًا
    CLOSED_BY_SCHEDULE = "closed_by_schedule"  # الجدول يقول مغلق الآن — ليست حالة "توقف"
    STOPPED_DURING_HOURS = "stopped_during_hours"  # الجدول يقول مفتوح لكن مؤكَّد متوقف فعليًا
    UNKNOWN = "unknown"                        # الجدول يقول مفتوح، لا تأكيد وصل بعد


@dataclasses.dataclass(frozen=True)
class TimeWindow:
    """نافذة وقت واحدة — تدعم العبور عبر منتصف الليل صراحة عبر crosses_midnight."""
    start_minutes: int  # دقائق من منتصف الليل (0-1439)
    end_minutes: int
    crosses_midnight: bool = False

    def __post_init__(self):
        if not (0 <= self.start_minutes < 1440):
            raise ValueError(f"start_minutes خارج النطاق: {self.start_minutes}")
        if not (0 <= self.end_minutes < 1440):
            raise ValueError(f"end_minutes خارج النطاق: {self.end_minutes}")
        # crosses_midnight يجب أن يتطابق مع كون end <= start فعليًا، لا يُترك تناقضًا صامتًا
        implied_crossing = self.end_minutes <= self.start_minutes
        if implied_crossing != self.crosses_midnight:
            raise ValueError(
                f"crosses_midnight={self.crosses_midnight} لا يطابق start={self.start_minutes} "
                f"end={self.end_minutes} — اضبط العلم الصريح ليطابق الفعل"
            )

    def contains(self, minute_of_day: int) -> bool:
        if not self.crosses_midnight:
            return self.start_minutes <= minute_of_day < self.end_minutes
        return minute_of_day >= self.start_minutes or minute_of_day < self.end_minutes


@dataclasses.dataclass
class ExceptionSchedule:
    """جدول استثنائي لمناسبة أو تاريخ محدد — يتجاوز الجدول الأسبوعي العادي
    لذلك التاريخ بالذات فقط."""
    date: datetime.date
    windows: list[TimeWindow]  # فارغة = مغلق كامل اليوم استثنائيًا


@dataclasses.dataclass
class WeeklySchedule:
    windows_by_weekday: dict  # 0=الإثنين .. 6=الأحد -> list[TimeWindow]
    exceptions: list[ExceptionSchedule] = dataclasses.field(default_factory=list)

    def _windows_for(self, dt: datetime.datetime) -> list[TimeWindow]:
        for exc in self.exceptions:
            if exc.date == dt.date():
                return exc.windows
        return self.windows_by_weekday.get(dt.weekday(), [])

    def is_open_by_schedule(self, dt: datetime.datetime) -> bool:
        minute_of_day = dt.hour * 60 + dt.minute
        windows = self._windows_for(dt)
        # نافذة عابرة لمنتصف الليل من اليوم السابق قد تمتد لهذا اليوم أيضًا
        prev_day = dt - datetime.timedelta(days=1)
        prev_windows = self._windows_for(prev_day)
        for w in windows:
            if w.contains(minute_of_day):
                return True
        for w in prev_windows:
            if w.crosses_midnight and minute_of_day < w.end_minutes:
                return True
        return False


def compute_day_status(schedule: WeeklySchedule, now: datetime.datetime,
                        confirmed_open_from_app: bool | None) -> DayStatus:
    """confirmed_open_from_app: None = لا تأكيد وصل من التطبيق بعد (unknown
    ممكنة)؛ True/False = آخر تأكيد فعلي وصل. لا نخلط هذا بحالة الجدول."""
    scheduled_open = schedule.is_open_by_schedule(now)
    if not scheduled_open:
        return DayStatus.CLOSED_BY_SCHEDULE
    if confirmed_open_from_app is None:
        return DayStatus.UNKNOWN
    if confirmed_open_from_app:
        return DayStatus.OPEN_SCHEDULED
    return DayStatus.STOPPED_DURING_HOURS


def compute_uptime_ratio(scheduled_open_minutes: int, stopped_minutes_during_scheduled_open: int) -> float | None:
    """نسبة التوقف **داخل ساعات التشغيل المقررة فقط** — القسم 5 ينص على هذا
    صراحة، لا نسبة توقف عبر اليوم كله (وقت الإغلاق المجدول لا يُحتسَب توقفًا).
    None لو لا ساعات تشغيل مجدولة أصلًا (تفادي قسمة على صفر بلا معنى)."""
    if scheduled_open_minutes <= 0:
        return None
    stopped_minutes_during_scheduled_open = min(stopped_minutes_during_scheduled_open, scheduled_open_minutes)
    uptime_minutes = scheduled_open_minutes - stopped_minutes_during_scheduled_open
    return uptime_minutes / scheduled_open_minutes
