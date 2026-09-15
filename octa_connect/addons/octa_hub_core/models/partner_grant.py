# -*- coding: utf-8 -*-
"""
octa.hub.partner.grant — تفويض الشريك التقني: "لا يختار العملاء بنفسه،
لا يرى ماليات أو بيانات شخصية افتراضيًا، وتفويضه محدد بالعميل والفروع
والأفعال والمدة" (القسم 6). NOT RUN.
"""
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


class OctaHubPartnerGrant(models.Model):
    _name = "octa.hub.partner.grant"
    _description = "Scoped, time-bound delegation of a technical partner to a merchant"
    _order = "expires_at desc"

    partner_membership_id = fields.Many2one("octa.hub.membership", required=True, ondelete="cascade",
                                              domain=[("party_type", "=", "partner")])
    organization_id = fields.Many2one("octa.hub.organization", required=True, ondelete="cascade", index=True,
                                       help="العميل يمنح هذا التفويض؛ الشريك لا يختاره بنفسه")
    branch_ids = fields.Many2many("octa.hub.branch", string="الفروع المسموحة (فارغ = كل فروع العميل)")
    allowed_action_codes = fields.Char(help="قائمة أفعال مفصولة بفواصل، تُقيَّد صراحة")
    granted_by_user_id = fields.Many2one("res.users", required=True, readonly=True,
                                          help="التاجر هو من يمنح التفويض، لا الشريك")
    granted_at = fields.Datetime(default=fields.Datetime.now, readonly=True)
    expires_at = fields.Datetime(required=True, help="لا تفويض بلا مدة")
    revoked_at = fields.Datetime(readonly=True)
    is_currently_valid = fields.Boolean(
        default=True, store=True, index=True,
        help="إصلاح بعد مراجعة V2 المستقلة (R04): ir.rule.domain_force في "
             "Odoo 19 لا يملك 'datetime' في سياق التقييم (مُتحقَّق من "
             "odoo/addons/base/models/ir_rule.py::_eval_context — يوفر فقط "
             "user/company_ids/company_id) — فلا يمكن كتابة "
             "'expires_at > now()' مباشرة داخل نص القاعدة. هذا الحقل "
             "المخزَّن يُحسب صراحة عند الإنشاء/التعديل ليكون قابلًا للاستخدام "
             "في domain_force كحقل عادي. **قيد حقيقي متبقٍّ**: لا يتحدّث "
             "تلقائيًا لمجرد مرور الوقت على سجل لم يُكتب فيه — يحتاج cron "
             "دوريًا (مرتبط ببند R13، لا queue/worker حقيقي بعد) يستدعي "
             "refresh_validity() على كل سجل قارب على الانتهاء. NOT_STARTED "
             "لهذا الـcron تحديدًا.")

    @api.model_create_multi
    def create(self, vals_list):
        """يضبط is_currently_valid صراحة عند الإنشاء — الحقل ليس compute
        حقيقيًا (لتفادي تعقيد compute+store+inverse في Odoo لحقل يحتاج
        كتابة يدوية أيضًا من revoke())، بل يُحدَّث صراحة من نقاط الكتابة
        المعروفة (هنا وrevoke()) بالإضافة لـrefresh_validity() الدوري."""
        records = super().create(vals_list)
        records._recompute_is_currently_valid()
        return records

    def _recompute_is_currently_valid(self):
        now = fields.Datetime.now()
        for rec in self:
            rec.is_currently_valid = bool(rec.expires_at and rec.expires_at > now and not rec.revoked_at)

    def refresh_validity(self):
        """يُستدعى دوريًا (يحتاج cron حقيقي، NOT_STARTED) لالتقاط انتهاء
        الصلاحية الذي يحدث بمرور الوقت وحده بلا أي تعديل آخر على السجل."""
        self._recompute_is_currently_valid()

    def is_active_now(self):
        self.ensure_one()
        now = fields.Datetime.now()
        return bool(self.expires_at and self.expires_at > now and not self.revoked_at)

    def revoke(self):
        """سحب صلاحية/تفويض أثناء جلسة قائمة يطبق فور الطلب التالي (القسم 14).
        يبطل بيانات الوصول المرتبطة به (القسم 7: 'سحب تفويض شريك يبطل بيانات
        الوصول المرتبطة به')."""
        for rec in self:
            rec.revoked_at = fields.Datetime.now()
            rec._recompute_is_currently_valid()  # يُحدَّث فورًا، لا ينتظر cron
            rec.partner_membership_id._invalidate_permission_cache()

    @api.constrains("expires_at")
    def _check_expiry_required(self):
        # إصلاح بعد مراجعة قبول نهائية: كانت ترفع ValueError عادية — أُصلح
        # لاتساق مع بقية قيود @api.constrains في المشروع (انظر نفس الإصلاح
        # في membership.py::_check_role_matches_party_type).
        for rec in self:
            if not rec.expires_at:
                raise ValidationError(_("تفويض الشريك يجب أن يحمل تاريخ انتهاء صريح"))

    def check_access_or_raise(self, action_code, branch=None):
        self.ensure_one()
        if not self.is_active_now():
            raise AccessError(_("تفويض الشريك منتهٍ أو مسحوب"))
        allowed = (self.allowed_action_codes or "").split(",")
        if action_code not in allowed:
            raise AccessError(_("هذا الفعل خارج نطاق تفويض الشريك"))
        if branch and self.branch_ids and branch not in self.branch_ids:
            raise AccessError(_("هذا الفرع خارج نطاق تفويض الشريك"))
        if branch and branch.organization_id != self.organization_id:
            raise AccessError(_("الفرع لا ينتمي لعميل هذا التفويض"))
