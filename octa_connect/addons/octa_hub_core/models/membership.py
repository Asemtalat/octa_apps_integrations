# -*- coding: utf-8 -*-
"""
octa.hub.membership — عضوية مستخدم داخل هيئة (تاجر/شريك/أوكتاتيك) وسياقها.

يطبّق القسم 6: "لا تجمع امتيازات هيئات مختلفة عند تعدد العضوية؛ اختر سياقًا
صريحًا وافحصه في السيرفر". لهذا active_context_membership_id على المستخدم
هو ما يُفحص في كل طلب سيرفري، لا اتحاد كل عضويات المستخدم. NOT RUN.
"""
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError

# إصلاح بعد المراجعة السادسة: نفس إصلاح order.py — استيراد مرة واحدة عند
# تحميل الموديل، لا داخل كل نداء لدالة.
import sys as _sys
import os as _os
_LIB_DIR = _os.path.join(_os.path.dirname(__file__), "..", "lib")
if _LIB_DIR not in _sys.path:
    _sys.path.insert(0, _LIB_DIR)
from authority_context import (
    check_single_authority_or_raise, DualAuthorityError,
    check_single_role_within_authority_or_raise, MixedRoleWithinAuthorityError,
)


class OctaHubMembership(models.Model):
    _name = "octa.hub.membership"
    _description = "Membership of a user in an Organization/Party with an explicit Role"
    _order = "id"

    user_id = fields.Many2one("res.users", required=True, index=True, ondelete="restrict")
    party_type = fields.Selection([
        ("merchant", "التاجر"),
        ("partner", "الشريك التقني"),
        ("octatech", "أوكتاتيك"),
    ], required=True)
    organization_id = fields.Many2one("octa.hub.organization", index=True,
                                       help="مطلوب لـ merchant، فارغ لأوكتاتيك، غير مباشر للشريك (عبر partner_grant)")
    role_code = fields.Selection([
        # Merchant roles
        ("merchant_owner", "مالك"),
        ("merchant_accountant", "محاسب"),
        ("merchant_branch_manager", "مسؤول فرع"),
        ("merchant_internal_tech", "تقني داخلي"),
        # Partner roles
        ("partner_tech", "شريك تقني"),
        # Octa-Tech internal roles — منفصلة عمدًا (القسم 6)
        ("octatech_identity_admin", "مدير الهوية"),
        ("octatech_support", "الدعم"),
        ("octatech_integration", "التكامل"),
        ("octatech_finance", "المالية"),
        ("octatech_security", "الأمن"),
    ], required=True)
    branch_ids = fields.Many2many("octa.hub.branch", string="الفروع المسموحة (فارغ = كل فروع العميل)")
    active = fields.Boolean(default=True)
    granted_by_user_id = fields.Many2one("res.users", required=True, readonly=True,
                                          help="فقط مستخدم أوكتاتيك مخوّل يمنح هذا (القسم 6)")
    granted_at = fields.Datetime(default=fields.Datetime.now, readonly=True)

    _uniq_user_org_role = models.Constraint(
        "unique(user_id, organization_id, role_code)",
        "نفس المستخدم لا يحصل على نفس الدور مرتين لنفس العميل",
    )

    @api.constrains("party_type", "organization_id", "role_code")
    def _check_role_matches_party_type(self):
        merchant_roles = {"merchant_owner", "merchant_accountant", "merchant_branch_manager", "merchant_internal_tech"}
        octatech_roles = {"octatech_identity_admin", "octatech_support", "octatech_integration",
                           "octatech_finance", "octatech_security"}
        for rec in self:
            # إصلاح بعد مراجعة قبول نهائية (فحص ملف-بملف): كانت هذه القيود
            # الأربعة ترفع ValueError عادية بدل ValidationError — قيود
            # @api.constrains في Odoo يجب أن ترفع ValidationError/UserError
            # ليتعامل معها ORM بعرض رسالة نظيفة للمستخدم، لا traceback خام.
            # نفس الملف نفسه كان يستخدم ValidationError بشكل صحيح في قيد آخر
            # (_check_single_authority_per_user) — تعارض اتساق داخل نفس
            # الملف، أُصلح الآن ليتطابق الاثنان.
            if rec.role_code in merchant_roles and rec.party_type != "merchant":
                raise ValidationError(_("دور تاجر لا يُمنح إلا لعضوية من نوع merchant"))
            if rec.role_code == "partner_tech" and rec.party_type != "partner":
                raise ValidationError(_("دور شريك تقني لا يُمنح إلا لعضوية من نوع partner"))
            if rec.role_code in octatech_roles and rec.party_type != "octatech":
                raise ValidationError(_("أدوار أوكتاتيك لا تُمنح إلا لعضوية من نوع octatech"))
            if rec.party_type == "merchant" and not rec.organization_id:
                raise ValidationError(_("عضوية تاجر يجب أن ترتبط بعميل (organization_id)"))

    def _invalidate_permission_cache(self):
        """يبطل أي cache صلاحيات مرتبط بجلسة مفتوحة (القسم 6: 'تغيير الدور
        أو الفرع يطبق في الطلبات التالية مع إبطال أي cache للصلاحيات').
        التنفيذ الفعلي يعتمد على آلية أودو 19 الدقيقة لإبطال
        ir.model.access cache لكل مستخدم (self.env.registry.clear_cache
        أو ما يعادلها) — يحتاج تحققًا مباشرًا على نسخة أودو المثبتة فعليًا؛
        غير مؤكد بعد (NOT VERIFIED، مسجّل في docs/decisions.md).
        """
        for rec in self:
            rec.user_id.env.registry.clear_cache()
            # إصلاح بعد المراجعة الرابعة: لو العضوية دي هي active_membership_id
            # الحالي للمستخدم وبقت غير فعالة، لازم نمسح المرجع ده — وإلا
            # الواجهة هتفضل تشاور على سياق ميت. كان ده bug حقيقي (مرجع معلّق
            # ماكانش بيتنضف أبدًا).
            if not rec.active and rec.user_id.active_membership_id.id == rec.id:
                rec.user_id.active_membership_id = False

    @api.constrains("party_type", "active", "user_id", "role_code")
    def _check_single_authority_per_user(self):
        """القسم 6: 'لا تجمع امتيازات هيئات مختلفة عند تعدد العضوية'.

        إصلاح بعد المراجعة الرابعة: هذا القيد **لم يكن موجودًا إطلاقًا** رغم
        أن التعليقات في هذا الملف كانت تدّعي أن 'السياق النشط' يحل هذه
        المشكلة — لكن لا شيء كان يفحص active_membership_id فعليًا (لا
        record_rules.xml ولا has_permission). الإصلاح الجذري: منع وجود
        party_type مختلف فعّال لنفس المستخدم من الأساس، بدل الاعتماد على
        فحص سياق لم يكن يحدث. المنطق المكافئ مُختبَر فعليًا بمعزل عن Odoo في
        lib/authority_context.py (6/6 PASS) — هذا فقط يستدعيه.

        إصلاح ثانٍ بعد مراجعة V2 المستقلة: نفس هذا القيد امتدّ الآن ليمنع
        أيضًا **تعدد الأدوار داخل نفس الهيئة** (مثال: merchant_owner
        وmerchant_branch_manager معًا لنفس المستخدم) — اكتُشف أن هذا يسبب
        اتساع صلاحيات حقيقي عبر آلية OR بين قواعد Odoo (مُتحقَّق من
        odoo/addons/base/models/ir_rule.py الحقيقي، انظر audit-findings.md
        وlib/authority_context.py::MixedRoleWithinAuthorityError للتفاصيل
        الكاملة). نفس الدور مكررًا عبر عملاء مختلفين (محاسب يخدم عميلين)
        يبقى مسموحًا صراحة — لا يسبب هذا الاتساع.
        """
        for rec in self:
            if not rec.active or not rec.user_id:
                continue
            # sudo() هنا مقصود: فحص أمني كهذا يجب أن يرى الحقيقة الكاملة
            # لعضويات المستخدم بغض النظر عن قواعد رؤية الصفوف الخاصة بمن
            # يكتب — وإلا قد يُقلّل عدد النتائج فيسمح خطأً بازدواج هيئة
            # (self.sudo() لا يمنح صلاحية كتابة إضافية، فقط رؤية للفحص).
            other_active = self.sudo().search([
                ("user_id", "=", rec.user_id.id), ("active", "=", True), ("id", "!=", rec.id),
            ])
            existing_types = set(other_active.mapped("party_type"))
            try:
                check_single_authority_or_raise(rec.user_id.id, existing_types, rec.party_type)
            except DualAuthorityError as e:
                # نلفّها بـValidationError الحقيقية حتى تظهر برسالة مفهومة في
                # واجهة Odoo بدل خطأ بايثون عام (NOT VERIFIED: شكل رسالة
                # الخطأ الفعلي في Odoo 19 يحتاج مراجعة بصرية حقيقية)
                raise ValidationError(str(e)) from e

            other_roles_same_authority = set(
                other_active.filtered(lambda m: m.party_type == rec.party_type).mapped("role_code")
            )
            try:
                check_single_role_within_authority_or_raise(
                    rec.user_id.id, rec.party_type, other_roles_same_authority, rec.role_code)
            except MixedRoleWithinAuthorityError as e:
                raise ValidationError(str(e)) from e

    # إصلاح حرج مكتشف بتشغيل فعلي حقيقي لأول مرة عبر 20 جولة (لم تكتشفه
    # قراءة كود ولا مراجعتان مستقلتان خارجيتان دقيقتان جدًا): **لم يكن يوجد
    # أي ربط بين إنشاء octa.hub.membership وبين إضافة المستخدم فعليًا
    # لمجموعة res.groups المقابلة** — يعني إنشاء عضوية "مسؤول فرع" مثلًا
    # كان يسجّل الدور في هذا الموديل المخصص فقط، بلا أي أثر فعلي على نظام
    # صلاحيات Odoo الحقيقي (ACL/record rules) الذي يعتمد كليًا على
    # `res.groups`. عمليًا: كل التوثيق عبر هذا المشروع بأكمله كان يصف
    # "إنشاء عضوية" كأنه يمنح صلاحيات فعلية — لم يكن يفعل ذلك إطلاقًا بلا
    # هذا الربط. اكتُشف بفشل اختبار حقيقي (`test_branch_manager_cannot_see_
    # other_branch`) حين لم يظهر أي فرع للمستخدم رغم منحه عضوية "مسؤول فرع".
    #
    # الإصلاح: مطابقة 1:1 مباشرة بين role_code وxmlid المجموعة المقابلة
    # (`octa_hub_core.group_<role_code>`، تحقَّقت أن كل الأدوار العشرة في
    # الـSelection أعلاه لها مجموعة بنفس الاسم بالضبط في security_groups.xml).
    # عند التفعيل: إضافة المجموعة. عند الإلغاء/التعطيل: **إعادة حساب كامل**
    # لمجموعات octa_hub_core على المستخدم من عضوياته الفعالة المتبقية فقط
    # (لا حذف مجموعة قد تكون لا تزال مستحقة من عضوية فعالة أخرى بنفس الدور
    # لمنظمة مختلفة).
    _OCTA_GROUP_XMLID_PREFIX = "octa_hub_core.group_"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_security_group()
        return records

    def write(self, vals):
        result = super().write(vals)
        if "active" in vals or "role_code" in vals or "user_id" in vals:
            self._sync_security_group()
        return result

    def unlink(self):
        users = self.mapped("user_id")
        result = super().unlink()
        users._recompute_octa_security_groups_from_active_memberships()
        return result

    def _sync_security_group(self):
        for rec in self:
            if rec.active:
                group = self.env.ref(f"{self._OCTA_GROUP_XMLID_PREFIX}{rec.role_code}", raise_if_not_found=False)
                if group:
                    rec.user_id.write({"group_ids": [(4, group.id)]})
        self.mapped("user_id")._recompute_octa_security_groups_from_active_memberships()


class ResUsersOctaContext(models.Model):
    """يضيف حقل 'السياق النشط' على res.users بدل افتراض اتحاد كل العضويات."""

    _inherit = "res.users"

    active_membership_id = fields.Many2one(
        "octa.hub.membership", string="السياق النشط الحالي",
        domain="[('user_id', '=', id), ('active', '=', True)]",
        help="يُفحص صراحة في كل طلب سيرفري بدل اتحاد كل عضويات المستخدم (القسم 6)")

    def _recompute_octa_security_groups_from_active_memberships(self):
        """يعيد حساب مجموعات octa_hub_core.* على المستخدم من الصفر بناءً
        على عضوياته الفعالة الحالية فقط — يضيف الناقص ويزيل غير المستحق.
        هذا ما يجعل **إلغاء أو تعطيل عضوية يزيل الصلاحية الفعلية فعليًا**،
        لا مجرد تحديث حقل تتبّع داخلي بلا أثر أمني حقيقي."""
        all_role_codes = [
            "merchant_owner", "merchant_accountant", "merchant_branch_manager", "merchant_internal_tech",
            "partner_tech", "octatech_identity_admin", "octatech_support",
            "octatech_integration", "octatech_finance", "octatech_security",
        ]
        all_octa_groups = self.env["res.groups"]
        for role_code in all_role_codes:
            group = self.env.ref(f"octa_hub_core.group_{role_code}", raise_if_not_found=False)
            if group:
                all_octa_groups |= group
        for user in self:
            justified_role_codes = set(self.env["octa.hub.membership"].sudo().search([
                ("user_id", "=", user.id), ("active", "=", True),
            ]).mapped("role_code"))
            justified_groups = self.env["res.groups"]
            for role_code in justified_role_codes:
                group = self.env.ref(f"octa_hub_core.group_{role_code}", raise_if_not_found=False)
                if group:
                    justified_groups |= group
            groups_to_remove = (user.group_ids & all_octa_groups) - justified_groups
            groups_to_add = justified_groups - user.group_ids
            if groups_to_remove:
                user.write({"group_ids": [(3, g.id) for g in groups_to_remove]})
            if groups_to_add:
                user.write({"group_ids": [(4, g.id) for g in groups_to_add]})

    def switch_active_context(self, membership_id):
        self.ensure_one()
        membership = self.env["octa.hub.membership"].browse(membership_id)
        if membership.user_id.id != self.id or not membership.active:
            raise AccessError(_("لا يمكنك التبديل إلى عضوية لا تخصك أو غير فعالة"))
        self.active_membership_id = membership.id
        membership._invalidate_permission_cache()

    def _octa_revoke_sessions(self):
        """إبطال أفضل-جهد لجلسات المستخدم المفتوحة عند إيقاف حسابه.

        NOT VERIFIED صراحة: لا يوجد Odoo 19 حقيقي في بيئة التطوير لأتحقق من
        الاستدعاء الصحيح فعليًا. الاستدعاء التالي (`_invalidate_session`) هو
        أفضل تخمين مبني على معرفتي بمعمارية Odoo (تدوير session_token يُبطل
        الجلسات المرتبطة بالتوكن القديم) — **يجب التحقق منه على تثبيت Odoo
        19 فعلي قبل الاعتماد عليه لإغلاق أي اختبار قبول أمني**. إن لم توجد
        الطريقة بهذا الاسم، البديل الموثق في مصادر Odoo هو تغيير كلمة مرور
        المستخدم قسريًا (يُبطل الجلسات كأثر جانبي) — كلاهما غير مُختبَر هنا.
        """
        for user in self:
            try:
                user.sudo()._invalidate_session()
            except AttributeError:
                # الطريقة غير موجودة بهذا الاسم في هذا الإصدار — نُسجّل ولا
                # نتظاهر بنجاح لم يحدث
                import logging
                logging.getLogger(__name__).warning(
                    "_invalidate_session غير متاحة — إبطال الجلسة الفعلي غير مؤكد لهذا المستخدم (NOT VERIFIED)"
                )
