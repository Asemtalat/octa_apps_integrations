"""اختبارات RUN فعليًا لقواعد انتقال الحالة (الحركات)."""
import pytest
from state_machine import (
    validate_transport_transition, validate_commercial_transition,
    IllegalTransitionError, is_final_commercial_state,
)


def test_legal_commercial_forward_path():
    validate_commercial_transition("new", "accepted")
    validate_commercial_transition("accepted", "in_preparation")
    validate_commercial_transition("in_preparation", "ready")
    validate_commercial_transition("ready", "completed")  # لا استثناء = نجاح


def test_completed_cannot_go_back_to_new():
    """مطابق حرفيًا لمثال الوثيقة: تحديث قديم لا يعيد الطلب لحالة تحضير."""
    with pytest.raises(IllegalTransitionError) as exc:
        validate_commercial_transition("completed", "new")
    assert exc.value.old_state == "completed"


def test_cancelled_cannot_move_to_in_preparation():
    with pytest.raises(IllegalTransitionError):
        validate_commercial_transition("cancelled", "in_preparation")


def test_new_cannot_jump_directly_to_completed():
    """يجب المرور بالمراحل الوسيطة — لا قفز مباشر."""
    with pytest.raises(IllegalTransitionError):
        validate_commercial_transition("new", "completed")


def test_same_state_write_is_always_allowed_idempotent():
    validate_commercial_transition("accepted", "accepted")
    validate_transport_transition("dispatching", "dispatching")


def test_stale_event_into_final_state_is_rejected():
    validate_commercial_transition("ready", "completed")
    with pytest.raises(IllegalTransitionError):
        validate_commercial_transition("completed", "accepted", is_stale_event=True)


def test_transport_cannot_go_backward_from_registered_confirmed():
    with pytest.raises(IllegalTransitionError):
        validate_transport_transition("registered_confirmed", "stored")


def test_transport_unknown_can_recover_to_confirmed():
    """POS يسجل ثم ينقطع الرد (unknown)، ثم الاستعلام يؤكد التسجيل لاحقًا."""
    validate_transport_transition("unknown", "registered_confirmed")


def test_transport_needs_intervention_cannot_silently_become_stored():
    with pytest.raises(IllegalTransitionError):
        validate_transport_transition("needs_intervention", "stored")


def test_rejected_is_final_no_further_transition():
    with pytest.raises(IllegalTransitionError):
        validate_commercial_transition("rejected", "accepted")


def test_is_final_commercial_state_helper():
    assert is_final_commercial_state("completed")
    assert is_final_commercial_state("cancelled")
    assert not is_final_commercial_state("new")


def test_correction_without_reason_is_rejected():
    """القبول حرفيًا: التصحيح يتطلب حدثًا موثوقًا — سبب فارغ يعني عدم توثيق."""
    from state_machine import apply_trusted_correction
    with pytest.raises(ValueError):
        apply_trusted_correction("completed", "cancelled", reason="")
    with pytest.raises(ValueError):
        apply_trusted_correction("completed", "cancelled", reason="   ")


def test_correction_from_non_final_state_is_rejected_use_ordinary_path():
    """التصحيح مخصص لما بعد حالة نهائية فقط — ليس بديلًا عامًا للانتقال العادي."""
    from state_machine import apply_trusted_correction
    with pytest.raises(ValueError):
        apply_trusted_correction("new", "accepted", reason="سبب ما")


def test_correction_to_unknown_state_name_is_rejected():
    from state_machine import apply_trusted_correction
    with pytest.raises(ValueError):
        apply_trusted_correction("completed", "not_a_real_state", reason="سبب حقيقي")


def test_valid_correction_after_final_state_succeeds_and_is_labeled():
    """السيناريو المطلوب حرفيًا: تصحيح من التطبيق بعد حالة نهائية بحدث موثوق
    (سبب مكتوب) — ينجح، ويُعلَّم كتصحيح صراحة، ويمنع تكرار أثر POS بنيويًا."""
    from state_machine import apply_trusted_correction
    correction = apply_trusted_correction(
        "completed", "cancelled",
        reason="التطبيق أبلغ لاحقًا أن العميل ألغى الطلب فعليًا قبل التحضير؛ خطأ مزامنة سابق")
    assert correction.is_correction is True
    assert correction.old_state == "completed"
    assert correction.new_state == "cancelled"
    assert correction.suppress_pos_side_effect is True  # يمنع تكرار الأثر على الـPOS بنيويًا


def test_ordinary_path_still_rejects_final_state_exit_unaffected_by_correction_feature():
    """يثبت أن إضافة مسار التصحيح لم تُخفِّف القيد الأصلي إطلاقًا — لا يزال
    محتوى دقيقًا حتى لو نفس (old_state, new_state) الذي نجح كتصحيح أعلاه."""
    from state_machine import ordinary_update_after_final_is_still_rejected
    with pytest.raises(IllegalTransitionError):
        ordinary_update_after_final_is_still_rejected("completed", "cancelled")


def test_correction_on_transport_state_is_out_of_scope_by_design():
    """المسار الحالي مبني لمحور الحالة التجارية فقط (القسم 3.3 يتحدث عن
    "حالة الطلب" من منظور التطبيق، وهذا يقابل commercial_state في هذا
    التصميم — لا transport_state الذي هو تقني بحت). موثَّق كقرار نطاق، لا نقص."""
    from state_machine import ALL_COMMERCIAL_STATES
    assert "registered_confirmed" not in ALL_COMMERCIAL_STATES  # حالة نقل، ليست تجارية
