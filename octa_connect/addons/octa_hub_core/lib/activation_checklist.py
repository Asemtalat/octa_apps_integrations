"""
مركز تفعيل التاجر (OC05-03، P0) — Gate E.

كان `activation_wizard.py` (Gate D الأصلي) يحمل حقل `step` واحدًا فقط
(مؤشر الخطوة الحالية) — لا يطابق البند الجديد الذي يشترط أن **كل خطوة**
تحمل حالتها الخاصة ومالكها وعائقها ودليلها بشكل مستقل. هذا أول تنفيذ
لقائمة تحقق حقيقية بهذا الشكل.

الاتصال التقني والاعتماد الإنتاجي وجاهزية الفرع **ثلاثة أشياء مستقلة** —
لا يُساوى اختبار اتصال HTTP باختبار تسجيل طلب وتحديث عكسي فعلي.
"""
from __future__ import annotations

import dataclasses
import enum
import time


class StepState(str, enum.Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    WAITING_ON_PARTY = "waiting_on_party"
    FAILED = "failed"
    PASSED = "passed"
    NEEDS_RECHECK = "needs_recheck"


class OwnerParty(str, enum.Enum):
    OCTATECH = "octatech"
    MERCHANT = "merchant"
    PARTNER = "partner"
    APP = "app"  # التطبيق الخارجي نفسه (مثال: بانتظار موافقته)


STEPS_ORDER = [
    "admin_account_created",
    "branches_defined",
    "pos_connected",
    "import_and_match",
    "apps_authorized",
    "prices_and_capabilities_reviewed",
    "tested",
    "ready",
]


@dataclasses.dataclass
class ActivationStep:
    step_id: str
    state: StepState = StepState.NOT_STARTED
    owner_party: OwnerParty | None = None
    blocking_reason: str | None = None
    last_checked_at: float | None = None
    evidence_ref: str | None = None  # مرجع دليل (مثال: attempt_id لاختبار ناجح)


@dataclasses.dataclass
class ActivationChecklist:
    branch_id: str
    steps: dict = dataclasses.field(default_factory=lambda: {
        s: ActivationStep(s) for s in STEPS_ORDER
    })

    def mark(self, step_id: str, state: StepState, owner_party: OwnerParty | None = None,
              blocking_reason: str | None = None, evidence_ref: str | None = None, now: float | None = None):
        if step_id not in self.steps:
            raise KeyError(f"خطوة غير معروفة: {step_id}")
        step = self.steps[step_id]
        step.state = state
        step.owner_party = owner_party
        step.blocking_reason = blocking_reason if state == StepState.FAILED or state == StepState.WAITING_ON_PARTY else None
        step.evidence_ref = evidence_ref
        step.last_checked_at = now if now is not None else time.time()

    def is_branch_ready(self) -> bool:
        """فرع بلا مطابقة أو إضافة إلزامية مفقودة لا يصبح جاهزًا — القبول
        الحرفي: كل الخطوات يجب أن تكون PASSED، لا اكتفاء بمعظمها."""
        return all(s.state == StepState.PASSED for s in self.steps.values())

    def invalidate_step_and_downstream(self, step_id: str, reason: str, now: float | None = None):
        """تغيير فرع أو عقد موصل أو إعداد مؤثر يبطل أدلة الجاهزية **المتأثرة
        فقط** — لا يعيد كل الخطوات إلى الصفر، فقط الخطوة المتأثرة وما بعدها
        في الترتيب."""
        if step_id not in STEPS_ORDER:
            raise KeyError(step_id)
        idx = STEPS_ORDER.index(step_id)
        for later_step_id in STEPS_ORDER[idx:]:
            step = self.steps[later_step_id]
            if step.state == StepState.PASSED:
                step.state = StepState.NEEDS_RECHECK
                step.blocking_reason = reason
                step.last_checked_at = now if now is not None else time.time()

    def resume_without_repeating_completed_work(self) -> list:
        """العودة للمعالج تستكمل نفس المهمة دون تكرار استيراد أو اتصال —
        يُرجع فقط الخطوات التي لم تكتمل بعد."""
        return [sid for sid, s in self.steps.items() if s.state != StepState.PASSED]


def technical_connection_is_not_production_approval(technically_connected: bool,
                                                      production_approved: bool,
                                                      branch_ready: bool) -> None:
    """القبول: لا يُساوى اختبار اتصال HTTP باختبار تسجيل طلب وتحديث عكسي —
    ثلاث حقول منفصلة تمامًا، لا يُشتق أحدها تلقائيًا من الآخر."""
    # هذه الدالة توثّق القاعدة كفحص صريح: لا استدلال آلي بينها، فقط تمنع
    # الخلط لو استُدعيت خطأً بفرضية "لو متصل تقنيًا إذن جاهز"
    if technically_connected and branch_ready and not production_approved:
        raise ValueError(
            "اتصال تقني + جاهزية فرع لا يعنيان اعتمادًا إنتاجيًا — الثلاثة مستقلة، "
            "production_approved يحتاج فحصه بشكل منفصل صراحة"
        )
