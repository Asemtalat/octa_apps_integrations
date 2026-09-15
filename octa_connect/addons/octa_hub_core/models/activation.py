# -*- coding: utf-8 -*-
"""
octa.hub.activation.checklist / .step — تخزين دائم لتقدّم تفعيل الفرع
(OC05-03). NOT RUN.

إصلاح حرج بعد Gate E: النسخة القديمة (`wizards/activation_wizard.py` في
Gate D الأصلي) كانت تخزّن كل تقدّم المعالج على `TransientModel` — وهذه
النماذج في Odoo تُحذف تلقائيًا بعد فترة (عادة حوالي يوم) بواسطة
`ir.autovacuum`. هذا يخالف مباشرة القبول الصريح لهذا البند: "الحفظ
والاستكمال آمنان" و"العودة للمعالج تستكمل نفس المهمة دون تكرار استيراد أو
اتصال" — تقدّم مخزَّن على TransientModel **غير آمن للاستكمال** لأنه قد
يُحذف قبل أن يعود التاجر لإكمال التفعيل. الإصلاح: نموذج دائم منفصل هنا؛
الـwizard (TransientModel) يبقى فقط واجهة تشغيل مؤقتة تشير إلى السجل الدائم.

منطق القرارات (هل الفرع جاهز، إبطال خطوة متأخرة فقط) مُختبَر فعليًا بمعزل
عن Odoo في lib/activation_checklist.py (7/7 PASS)؛ هذه النماذج فقط تخزّنه.
"""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

STEP_IDS = [
    "admin_account_created", "branches_defined", "pos_connected", "import_and_match",
    "apps_authorized", "prices_and_capabilities_reviewed", "tested", "ready",
]
STEP_LABELS = {
    "admin_account_created": "حساب منشأ إداريًا",
    "branches_defined": "تعريف الفروع",
    "pos_connected": "اتصال POS",
    "import_and_match": "استيراد ومطابقة",
    "apps_authorized": "تفويض التطبيقات",
    "prices_and_capabilities_reviewed": "مراجعة الأسعار والقدرات",
    "tested": "اختبار",
    "ready": "جاهزية",
}


class OctaHubActivationChecklist(models.Model):
    """سجل دائم واحد لكل فرع — لا TransientModel (انظر التوثيق أعلاه)."""

    _name = "octa.hub.activation.checklist"
    _description = "Persistent per-branch activation progress (OC05-03)"

    branch_id = fields.Many2one("octa.hub.branch", required=True, ondelete="cascade", index=True)
    step_ids = fields.One2many("octa.hub.activation.step", "checklist_id", string="الخطوات")

    _uniq_branch_checklist = models.Constraint("unique(branch_id)", "سجل تفعيل واحد فقط لكل فرع")

    @api.model
    def get_or_create_for_branch(self, branch_id):
        existing = self.search([("branch_id", "=", branch_id)], limit=1)
        if existing:
            return existing
        checklist = self.create({"branch_id": branch_id})
        checklist.step_ids = [
            (0, 0, {"step_id": sid, "state": "not_started"}) for sid in STEP_IDS
        ]
        return checklist

    def is_branch_ready(self):
        """فرع بلا مطابقة أو إضافة إلزامية مفقودة لا يصبح جاهزًا — كل خطوة
        يجب أن تكون 'passed'، لا اكتفاء بمعظمها."""
        self.ensure_one()
        return all(s.state == "passed" for s in self.step_ids)

    def resume_steps_not_yet_completed(self):
        """العودة للمعالج تستكمل نفس المهمة دون تكرار — يُرجع فقط ما لم يكتمل."""
        self.ensure_one()
        return self.step_ids.filtered(lambda s: s.state != "passed")

    def invalidate_step_and_downstream(self, step_id, reason):
        """تغيير مؤثر يبطل الخطوة المتأثرة وما بعدها فقط في الترتيب، لا كل شيء."""
        self.ensure_one()
        if step_id not in STEP_IDS:
            raise ValidationError(_("خطوة غير معروفة: %s") % step_id)
        idx = STEP_IDS.index(step_id)
        affected_ids = set(STEP_IDS[idx:])
        for step in self.step_ids.filtered(lambda s: s.step_id in affected_ids and s.state == "passed"):
            step.write({"state": "needs_recheck", "blocking_reason": reason,
                        "last_checked_at": fields.Datetime.now()})


class OctaHubActivationStep(models.Model):
    _name = "octa.hub.activation.step"
    _description = "Single activation step with independent state/owner/evidence (OC05-03)"
    _order = "sequence"

    checklist_id = fields.Many2one("octa.hub.activation.checklist", required=True, ondelete="cascade", index=True)
    step_id = fields.Selection([(sid, STEP_LABELS[sid]) for sid in STEP_IDS], required=True)
    sequence = fields.Integer(compute="_compute_sequence", store=True)
    state = fields.Selection([
        ("not_started", "لم يبدأ"), ("in_progress", "جارٍ"),
        ("waiting_on_party", "ينتظر طرفًا"), ("failed", "فشل"),
        ("passed", "اجتاز"), ("needs_recheck", "يحتاج إعادة تحقق"),
    ], default="not_started", required=True)
    owner_party = fields.Selection([
        ("octatech", "أوكتاتيك"), ("merchant", "التاجر"),
        ("partner", "الشريك"), ("app", "التطبيق الخارجي"),
    ])
    blocking_reason = fields.Char()
    last_checked_at = fields.Datetime()
    evidence_ref = fields.Char(help="مرجع دليل، مثال: attempt_id لاختبار ناجح — يحمل رقم نسخة الإعداد والعقد وتاريخ التنفيذ")

    _uniq_checklist_step = models.Constraint("unique(checklist_id, step_id)", "نفس الخطوة لا تتكرر لنفس السجل")

    @api.depends("step_id")
    def _compute_sequence(self):
        for rec in self:
            rec.sequence = STEP_IDS.index(rec.step_id) if rec.step_id in STEP_IDS else 999

    def mark(self, state, owner_party=None, blocking_reason=None, evidence_ref=None):
        self.ensure_one()
        self.write({
            "state": state,
            "owner_party": owner_party,
            "blocking_reason": blocking_reason if state in ("failed", "waiting_on_party") else False,
            "evidence_ref": evidence_ref,
            "last_checked_at": fields.Datetime.now(),
        })
