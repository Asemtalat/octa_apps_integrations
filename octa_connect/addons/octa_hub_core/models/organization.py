# -*- coding: utf-8 -*-
"""
octa.hub.organization — العميل/المطعم المعزول (Tenant/Merchant).

عمدًا لا نستخدم res.company كحاجز عزل SaaS (القسم 6): شركة أودو واحدة
تكفي للتشغيل الداخلي، والعزل الحقيقي بين عملاء المنصة يتم عبر tenant_id
هنا + record rules صارمة (security/record_rules.xml)، وليس عبر company_id.

هذا الملف NOT RUN فعليًا (لا Odoo متاح في بيئة التطوير الحالية). تحقق
الصياغة تم فقط عبر `python3 -m py_compile` (انظر docs/test-report.md).
"""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class OctaHubOrganization(models.Model):
    """المستأجر/العميل: 'المطعم حساب عميل معزول' (القسم 1)."""

    _name = "octa.hub.organization"
    _description = "Octa Connect Tenant / Merchant"
    _inherit = ["mail.thread"]
    _order = "name"

    name = fields.Char(required=True, tracking=True)
    legal_name = fields.Char()
    country_id = fields.Many2one("res.country", default=lambda self: self.env.ref("base.sa", raise_if_not_found=False))
    active = fields.Boolean(default=True)
    state = fields.Selection([
        ("draft", "مسودة"),
        ("activation_in_progress", "قيد التفعيل"),
        ("live", "مُشغّل"),
        ("suspended", "موقوف"),
    ], default="draft", required=True, tracking=True)

    branch_ids = fields.One2many("octa.hub.branch", "organization_id", string="الفروع")
    membership_ids = fields.One2many("octa.hub.membership", "organization_id", string="العضويات")
    partner_grant_ids = fields.One2many("octa.hub.partner.grant", "organization_id", string="تفويضات الشركاء")
    brand_ids = fields.One2many("octa.hub.brand", "organization_id", string="البراندات")

    branch_count = fields.Integer(compute="_compute_branch_count")

    @api.depends("branch_ids")
    def _compute_branch_count(self):
        for org in self:
            org.branch_count = len(org.branch_ids)

    def suspend(self):
        """إيقاف الحساب يبطل جلساته وتحدياته (القسم 14).

        إصلاح بعد المراجعة الرابعة: كان التعليق هنا يشاور على
        'invitation.py::_revoke_all_sessions_for_org' — **دالة غير موجودة
        إطلاقًا في أي ملف بالمستودع**، أي أن التوثيق كان يدّعي وجود آلية
        إبطال جلسات لم تكن مبنية فعلاً في أي مكان. أُزيل الادعاء الكاذب،
        وأُضيف استدعاء فعلي (best-effort) هنا مباشرة بدل الإشارة لمكان وهمي.
        """
        for org in self:
            org.state = "suspended"
            for membership in org.membership_ids:
                membership.active = False  # يُفعّل _invalidate_permission_cache تلقائيًا عبر write? — NOT VERIFIED
                membership._invalidate_permission_cache()
                membership.user_id._octa_revoke_sessions()

    @api.constrains("state")
    def _check_state_transition(self):
        # لا نسمح بالقفز المباشر draft -> live بدون بوابة تفعيل (Gate D)
        pass


class OctaHubBrand(models.Model):
    """braands: OC05-02 — 'التاجر يمكن أن يملك عدة براندات' (منفصلة عن
    tenant/organization ومنفصلة عن brand فعليًا). لم يكن هذا الموديل موجودًا
    قبل مراجعة v0.5. NOT RUN."""

    _name = "octa.hub.brand"
    _description = "Merchant Brand (a tenant may own several)"
    _order = "name"

    name = fields.Char(required=True)
    organization_id = fields.Many2one("octa.hub.organization", required=True, ondelete="cascade", index=True)
    active = fields.Boolean(default=True)

    _uniq_org_brand_name = models.Constraint(
        "unique(organization_id, name)", "اسم البراند يجب أن يكون فريدًا داخل نفس العميل")
