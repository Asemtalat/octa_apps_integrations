"""اختبارات RUN فعليًا لمركز تفعيل التاجر (OC05-03)."""
import pytest
from activation_checklist import (
    ActivationChecklist, StepState, OwnerParty, STEPS_ORDER,
    technical_connection_is_not_production_approval,
)


def test_branch_with_unmatched_or_missing_mandatory_item_is_not_ready():
    """القبول حرفيًا: فرع بلا مطابقة أو إضافة إلزامية مفقودة لا يصبح جاهزًا."""
    checklist = ActivationChecklist("BR-1")
    for step_id in STEPS_ORDER[:-1]:  # كل الخطوات ما عدا الأخيرة
        checklist.mark(step_id, StepState.PASSED)
    checklist.mark("ready", StepState.FAILED, owner_party=OwnerParty.MERCHANT,
                    blocking_reason="إضافة إلزامية غير مربوطة لصنف واحد")
    assert checklist.is_branch_ready() is False


def test_all_steps_passed_means_ready():
    checklist = ActivationChecklist("BR-1")
    for step_id in STEPS_ORDER:
        checklist.mark(step_id, StepState.PASSED)
    assert checklist.is_branch_ready() is True


def test_each_step_has_independent_owner_and_blocking_reason():
    checklist = ActivationChecklist("BR-1")
    checklist.mark("pos_connected", StepState.WAITING_ON_PARTY, owner_party=OwnerParty.PARTNER,
                    blocking_reason="بانتظار الشريك التقني لإكمال ربط POS")
    step = checklist.steps["pos_connected"]
    assert step.owner_party == OwnerParty.PARTNER
    assert "الشريك" in step.blocking_reason
    assert step.last_checked_at is not None


def test_invalidating_a_step_only_invalidates_that_step_and_downstream():
    """القبول حرفيًا: تغيير مؤثر يبطل الأدلة المتأثرة فقط، لا كل شيء."""
    checklist = ActivationChecklist("BR-1")
    for step_id in STEPS_ORDER:
        checklist.mark(step_id, StepState.PASSED)

    checklist.invalidate_step_and_downstream("apps_authorized", reason="تغيير عقد الموصل")

    # الخطوات القبل ما زالت PASSED (غير متأثرة)
    assert checklist.steps["admin_account_created"].state == StepState.PASSED
    assert checklist.steps["pos_connected"].state == StepState.PASSED
    # الخطوة المتأثرة وما بعدها تحتاج إعادة تحقق
    assert checklist.steps["apps_authorized"].state == StepState.NEEDS_RECHECK
    assert checklist.steps["ready"].state == StepState.NEEDS_RECHECK


def test_resume_does_not_repeat_completed_steps():
    """القبول حرفيًا: العودة للمعالج تستكمل نفس المهمة دون تكرار استيراد أو اتصال."""
    checklist = ActivationChecklist("BR-1")
    checklist.mark("admin_account_created", StepState.PASSED)
    checklist.mark("branches_defined", StepState.PASSED)
    checklist.mark("pos_connected", StepState.IN_PROGRESS)
    remaining = checklist.resume_without_repeating_completed_work()
    assert "admin_account_created" not in remaining
    assert "branches_defined" not in remaining
    assert "pos_connected" in remaining


def test_technical_connection_alone_does_not_imply_production_approval():
    """القبول حرفيًا: لا يُساوى اختبار اتصال HTTP باختبار تسجيل طلب وتحديث عكسي."""
    with pytest.raises(ValueError):
        technical_connection_is_not_production_approval(
            technically_connected=True, production_approved=False, branch_ready=True)
    # لا استثناء لو production_approved صراحة True (فُحص بشكل منفصل فعلاً)
    technical_connection_is_not_production_approval(
        technically_connected=True, production_approved=True, branch_ready=True)


def test_unknown_step_id_rejected():
    checklist = ActivationChecklist("BR-1")
    with pytest.raises(KeyError):
        checklist.mark("not_a_real_step", StepState.PASSED)
