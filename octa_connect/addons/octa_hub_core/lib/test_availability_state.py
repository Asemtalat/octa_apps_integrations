"""اختبارات RUN فعليًا لحالة التوفر المطلوب/المؤكد (OC05-11)."""
from availability_state import (
    AvailabilityRecord, DisplayAvailability, display_state, apply_confirmation,
    aggregate_across_destinations,
)


def test_unconfirmed_new_item_is_pending_not_available():
    rec = AvailabilityRecord("b1", "ch1", "item1", desired_state=True)
    assert display_state(rec) == DisplayAvailability.PENDING_CONFIRMATION


def test_confirmed_matching_desired_is_available():
    rec = AvailabilityRecord("b1", "ch1", "item1", desired_state=True, confirmed_state=True, version=2)
    assert display_state(rec) == DisplayAvailability.AVAILABLE_CONFIRMED


def test_confirmed_mismatching_desired_is_failed():
    """طلبنا التوقف لكن التأكيد الوارد يقول ما زال متاحًا — فشل، لا نجاح صامت."""
    rec = AvailabilityRecord("b1", "ch1", "item1", desired_state=False, confirmed_state=True, version=2)
    assert display_state(rec) == DisplayAvailability.FAILED


def test_expired_temporary_stop_without_renewal_is_stale_not_auto_available():
    """القبول حرفيًا: لا إعادة إتاحة تلقائية اعتمادًا على انقضاء الوقت وحده."""
    rec = AvailabilityRecord("b1", "ch1", "item1", desired_state=False, confirmed_state=False,
                             version=2, expires_at=1000.0)
    assert display_state(rec, now=2000.0) == DisplayAvailability.STALE


def test_old_confirmation_does_not_overwrite_newer_version():
    """القبول حرفيًا: حدث تأكيد قديم لا يكتب فوق نسخة أحدث."""
    rec = AvailabilityRecord("b1", "ch1", "item1", desired_state=True, confirmed_state=True, version=5)
    result = apply_confirmation(rec, confirmed_state=False, source="webhook", confirmed_at=100.0, incoming_version=3)
    assert result.confirmed_state is True  # لم يتغير
    assert result.version == 5


def test_newer_confirmation_does_update():
    rec = AvailabilityRecord("b1", "ch1", "item1", desired_state=True, confirmed_state=True, version=3)
    result = apply_confirmation(rec, confirmed_state=False, source="webhook", confirmed_at=100.0, incoming_version=7)
    assert result.confirmed_state is False
    assert result.version == 7


def test_stale_success_does_not_prove_new_request_success():
    """حالة قديمة ناجحة لا تثبت نجاح طلب جديد — كل استدعاء جديد يبدأ
    confirmed_state=None حتى تصل تأكيدات فعلية جديدة."""
    old_success = AvailabilityRecord("b1", "ch1", "item1", desired_state=True, confirmed_state=True, version=1)
    new_request = AvailabilityRecord("b1", "ch1", "item1", desired_state=False)  # طلب جديد، لا يرث تأكيد القديم
    assert display_state(new_request) == DisplayAvailability.PENDING_CONFIRMATION
    assert old_success is not new_request  # كيانان منفصلان صراحة


def test_partial_when_one_destination_confirmed_and_other_pending():
    """القبول حرفيًا: نجاح وجهة وانقطاع الأخرى ينتج partial."""
    confirmed = AvailabilityRecord("b1", "ch1", "item1", desired_state=True, confirmed_state=True, version=1)
    pending = AvailabilityRecord("b1", "ch2", "item1", desired_state=True, confirmed_state=None)
    assert aggregate_across_destinations([confirmed, pending]) == "partial"


def test_all_confirmed_same_state_is_not_partial():
    a = AvailabilityRecord("b1", "ch1", "item1", desired_state=True, confirmed_state=True, version=1)
    b = AvailabilityRecord("b1", "ch2", "item1", desired_state=True, confirmed_state=True, version=1)
    assert aggregate_across_destinations([a, b]) == DisplayAvailability.AVAILABLE_CONFIRMED.value


def test_unsupported_capability_shows_as_unsupported_not_failed():
    rec = AvailabilityRecord("b1", "ch1", "item1", desired_state=True, supported=False)
    assert display_state(rec) == DisplayAvailability.UNSUPPORTED
