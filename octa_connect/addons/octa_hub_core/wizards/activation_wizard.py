# -*- coding: utf-8 -*-
"""
octa.hub.activation.wizard — معالج التفعيل المبسط (القسم 12/13):
إنشاء إداري → توصيل POS → اختيار تطبيق وتفويض → مطابقة فروع → استيراد
ومطابقة كتالوج → اختبار → مراجعة جاهزية → تشغيل فرع.

في المرحلة الأولى: بالمحاكيات فقط، مع "real-channel capability
placeholders غير نشطة وموسومة تحتاج توثيقًا واعتمادًا" (القسم 12).

NOT RUN — لا Odoo متاح. منطق التسوية الفعلي (upsert/dedup) مُختبَر فعليًا
بمعزل عن Odoo في tools/catalog_reconcile/reconcile.py (8/8 PASSED)؛ هذا
الملف فقط يربطه بنماذج octa.hub.* عبر استدعاء الدوال الجاهزة، ولا يعيد
كتابة القواعد.
"""
import sys
import os

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

# نستورد منطق التسوية المُختبَر فعليًا بدل إعادة كتابته هنا (DRY + لأنه
# الجزء الوحيد المُثبَت بالأدلة). المسار النسبي يفترض وضع reconcile.py في
# نفس بنية المستودع (tools/catalog_reconcile) — يحتاج ضبط PYTHONPATH أو نقل
# reconcile.py داخل الموديول عند التوزيع الفعلي (مسجّل في docs/decisions.md).
_TOOLS_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", "tools", "catalog_reconcile")
if _TOOLS_PATH not in sys.path:
    sys.path.insert(0, _TOOLS_PATH)


class OctaHubActivationWizard(models.TransientModel):
    """المعالج نفسه يبقى TransientModel (واجهة تشغيل مؤقتة فقط) — لكن كل
    التقدّم الفعلي مخزَّن الآن في octa.hub.activation.checklist الدائم
    (انظر models/activation.py والتوثيق هناك لسبب هذا الإصلاح)."""

    _name = "octa.hub.activation.wizard"
    _description = "Activation wizard UI flow (state lives in octa.hub.activation.checklist)"

    organization_id = fields.Many2one("octa.hub.organization", required=True)
    branch_id = fields.Many2one("octa.hub.branch", required=True)
    checklist_id = fields.Many2one("octa.hub.activation.checklist", readonly=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        return res

    def action_open_or_resume(self):
        """يفتح سجل التفعيل الدائم لهذا الفرع (ينشئه إن لم يوجد) — هذا هو
        الإصلاح: قبل ذلك لم يكن هناك سجل دائم يُستأنف منه إطلاقًا."""
        self.ensure_one()
        Checklist = self.env["octa.hub.activation.checklist"]
        checklist = Checklist.get_or_create_for_branch(self.branch_id.id)
        self.checklist_id = checklist.id
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
                "view_mode": "form", "target": "current"}

    def action_run_catalog_import_preview(self, staged_items):
        """يشغّل معاينة الفروق (جديد/معدل/متعارض/ناقص) عبر نواة reconcile.py
        المُختبَرة، ثم يعرضها للمستخدم قبل الاعتماد (القسم 12: 'اقرأ إلى
        staging ثم تحقق واعرض جديد/معدل/متعارض/ناقص ثم اعتمد')."""
        from reconcile import CatalogStore, CatalogKey, CatalogRecord, reconcile_batch  # noqa

        # NOT VERIFIED: تحميل/حفظ CatalogStore الفعلي من/إلى جداول Odoo
        # (octa.hub.catalog.item) غير موصول بعد؛ هنا نستخدم store مؤقت
        # داخل الذاكرة لكل استدعاء فقط لإثبات ربط الاستدعاء بشكل صحيح.
        store = CatalogStore()
        records = [
            CatalogRecord(
                key=CatalogKey(str(self.organization_id.id), str(self.branch_id.id),
                                "pos:demo", "item", item["external_id"]),
                sku=item.get("sku"), name_ar=item.get("name_ar", ""), name_en=item.get("name_en", ""),
                price_minor_units=item.get("price_minor_units", 0), currency="SAR",
                version=item.get("version", 1),
            )
            for item in staged_items
        ]
        result = reconcile_batch(store, f"wizard-{self.id}", records,
                                  str(self.organization_id.id), str(self.branch_id.id), "pos:demo", "item")
        if self.checklist_id:
            import_step = self.checklist_id.step_ids.filtered(lambda s: s.step_id == "import_and_match")
            if import_step and not result.counts().get("conflict"):
                import_step.mark("passed", evidence_ref=f"wizard-{self.id}")
        return result.counts()  # {"new": N, "updated": N, "conflict": N, ...}

    def action_go_live(self):
        """التشغيل الفعلي — الآن يتحقق عبر السجل الدائم أن **كل** خطوة
        اجتازت (is_branch_ready)، لا حقل missing_fields_json نصي حر كما كان
        سابقًا (كان يمكن نسيان تحديثه ليعكس واقع الخطوات فعليًا)."""
        self.ensure_one()
        if not self.checklist_id or not self.checklist_id.is_branch_ready():
            remaining = self.checklist_id.resume_steps_not_yet_completed() if self.checklist_id else None
            names = ", ".join(remaining.mapped("step_id")) if remaining else "لم يبدأ التفعيل بعد"
            raise ValidationError(_("لا يمكن التشغيل قبل اجتياز كل الخطوات. المتبقي: %s") % names)
        self.branch_id.write({"active": True})
