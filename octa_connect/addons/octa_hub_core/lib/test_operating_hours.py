"""اختبارات RUN فعليًا لمواعيد التشغيل والتوقف (القسم 5)."""
import datetime
import pytest
from operating_hours import (
    TimeWindow, WeeklySchedule, ExceptionSchedule, DayStatus,
    compute_day_status, compute_uptime_ratio,
)


def test_normal_window_same_day():
    w = TimeWindow(start_minutes=9 * 60, end_minutes=22 * 60)  # 9ص-10م
    assert w.contains(12 * 60) is True
    assert w.contains(23 * 60) is False


def test_midnight_crossing_window_required_scenario():
    """القبول حرفيًا: فترات تعبر منتصف الليل. مطعم يفتح 6م ويقفل 2ص."""
    w = TimeWindow(start_minutes=18 * 60, end_minutes=2 * 60, crosses_midnight=True)
    assert w.contains(23 * 60) is True   # 11م — داخل الفترة
    assert w.contains(1 * 60) is True    # 1ص اليوم التالي — لا تزال داخل الفترة
    assert w.contains(10 * 60) is False  # 10ص — خارجها


def test_midnight_crossing_flag_must_match_actual_times():
    """لا تناقض صامت بين العلم الصريح والأوقات الفعلية."""
    with pytest.raises(ValueError):
        TimeWindow(start_minutes=9 * 60, end_minutes=22 * 60, crosses_midnight=True)  # لا يعبر فعليًا
    with pytest.raises(ValueError):
        TimeWindow(start_minutes=22 * 60, end_minutes=9 * 60, crosses_midnight=False)  # يعبر فعليًا لكن العلم False


def test_schedule_open_across_midnight_from_previous_day():
    """نفس السيناريو لكن عبر WeeklySchedule كامل — الساعة 1ص الثلاثاء يجب
    أن تُعتبَر ضمن فترة الإثنين الليلية العابرة لمنتصف الليل."""
    monday_night = TimeWindow(18 * 60, 2 * 60, crosses_midnight=True)
    schedule = WeeklySchedule(windows_by_weekday={0: [monday_night]})  # 0 = الإثنين
    tuesday_1am = datetime.datetime(2026, 1, 6, 1, 0)  # الثلاثاء 1ص (2026-01-05 كان إثنين)
    assert schedule.is_open_by_schedule(tuesday_1am) is True
    tuesday_3am = datetime.datetime(2026, 1, 6, 3, 0)
    assert schedule.is_open_by_schedule(tuesday_3am) is False


def test_exception_schedule_overrides_weekly_for_that_date_only():
    """جدول استثنائي لمناسبة يتجاوز الجدول الأسبوعي العادي لذلك التاريخ فقط."""
    normal_monday = TimeWindow(9 * 60, 22 * 60)
    schedule = WeeklySchedule(
        windows_by_weekday={0: [normal_monday]},
        exceptions=[ExceptionSchedule(date=datetime.date(2026, 1, 5), windows=[])],  # عطلة، مغلق كامل اليوم
    )
    holiday_monday = datetime.datetime(2026, 1, 5, 12, 0)
    assert schedule.is_open_by_schedule(holiday_monday) is False  # الاستثناء يغلب الجدول العادي
    normal_monday_next_week = datetime.datetime(2026, 1, 12, 12, 0)
    assert schedule.is_open_by_schedule(normal_monday_next_week) is True  # الأسبوع التالي عادي


def test_three_way_status_closed_by_schedule_vs_stopped_vs_unknown():
    """القبول حرفيًا: مغلق حسب الجدول / متوقف أثناء التشغيل / غير معروف —
    ثلاث حالات منفصلة، لا تُخلَط."""
    open_hours = TimeWindow(9 * 60, 22 * 60)
    schedule = WeeklySchedule(windows_by_weekday={i: [open_hours] for i in range(7)})

    outside_hours = datetime.datetime(2026, 1, 5, 23, 0)
    assert compute_day_status(schedule, outside_hours, confirmed_open_from_app=True) == DayStatus.CLOSED_BY_SCHEDULE

    during_hours_confirmed_stopped = datetime.datetime(2026, 1, 5, 14, 0)
    assert compute_day_status(schedule, during_hours_confirmed_stopped,
                               confirmed_open_from_app=False) == DayStatus.STOPPED_DURING_HOURS

    during_hours_no_confirmation = datetime.datetime(2026, 1, 5, 14, 0)
    assert compute_day_status(schedule, during_hours_no_confirmation,
                               confirmed_open_from_app=None) == DayStatus.UNKNOWN

    during_hours_confirmed_open = datetime.datetime(2026, 1, 5, 14, 0)
    assert compute_day_status(schedule, during_hours_confirmed_open,
                               confirmed_open_from_app=True) == DayStatus.OPEN_SCHEDULED


def test_uptime_ratio_only_within_scheduled_open_hours():
    """القبول حرفيًا: نسبة التوقف داخل ساعات التشغيل المقررة فقط — إغلاق
    مجدول لا يُحتسَب توقفًا."""
    ratio = compute_uptime_ratio(scheduled_open_minutes=600, stopped_minutes_during_scheduled_open=60)
    assert ratio == pytest.approx(0.9)


def test_uptime_ratio_none_when_no_scheduled_hours():
    assert compute_uptime_ratio(scheduled_open_minutes=0, stopped_minutes_during_scheduled_open=0) is None


def test_stopped_minutes_cannot_exceed_scheduled_minutes_clamped():
    """بيانات غير متسقة (توقف أكثر من ساعات التشغيل نفسها) لا تنتج نسبة سالبة."""
    ratio = compute_uptime_ratio(scheduled_open_minutes=100, stopped_minutes_during_scheduled_open=500)
    assert ratio == 0.0
