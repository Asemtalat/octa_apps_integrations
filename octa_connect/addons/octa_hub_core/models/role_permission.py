# -*- coding: utf-8 -*-
"""
octa.hub.permission — فصل أذونات القراءة والتعديل والتصدير والنشر وتدوير
مفاتيح API وفصل الاتصال وإعادة المعالجة (القسم 6). NOT RUN.

هذا جدول صلاحيات دقيق إضافي فوق مجموعات أودو (security/security_groups.xml)،
لأن مجموعات أودو وحدها خشنة الحبيبات لتمييز "نشر" عن "قراءة" لنفس النموذج.
"""
from odoo import fields, models


class OctaHubPermission(models.Model):
    _name = "octa.hub.permission"
    _description = "Fine-grained action permission grant"

    membership_id = fields.Many2one("octa.hub.membership", required=True, ondelete="cascade", index=True)
    action_code = fields.Selection([
        ("read", "قراءة"),
        ("write", "تعديل"),
        ("export", "تصدير"),
        ("publish_catalog", "نشر كتالوج"),
        ("rotate_api_key", "تدوير مفتاح API"),
        ("disconnect_connection", "فصل اتصال"),
        ("reprocess_order", "إعادة معالجة طلب"),
    ], required=True)
    resource_model = fields.Char(help="اسم النموذج المستهدف، فارغ = كل نطاق العضوية")

    _uniq_membership_action_model = models.Constraint(
        "unique(membership_id, action_code, resource_model)",
        "نفس الإذن لا يُمنح مرتين لنفس العضوية",
    )

    def has_permission(self, membership, action_code, resource_model=None):
        """يُستدعى من الـ controllers/services قبل أي فعل حساس. لا تعتمد
        الواجهة وحدها على إخفاء الزر (القسم 6: 'إخفاء الواجهة ليس حماية').

        إصلاح بعد المراجعة الرابعة: النسخة السابقة كانت تفحص فقط وجود سطر
        إذن مطابق لـmembership_id المُمرَّر — **بلا التحقق من أن العضوية
        نفسها لا تزال فعّالة (active)، ولا من أنها تخص المستخدم الحالي
        فعلاً**. هذا يعني: (أ) عضوية مُوقَفة (revoked) كانت لا تزال تمنح
        صلاحياتها القديمة طالما سجلات octa.hub.permission لم تُحذف — يخالف
        صراحة 'سحب صلاحية أثناء جلسة قائمة يطبق فور الطلب التالي' (القسم
        14)؛ (ب) لو مرّر كود مستدعٍ خطأً (أو بتلاعب) membership تخص شخصًا
        آخر، كانت الدالة تثق فيه بلا تحقق هوية إضافي. أُصلح الاثنان هنا.
        """
        if not membership or not membership.active:
            return False
        if membership.user_id.id != self.env.user.id:
            # دفاع بعمق (defense-in-depth): حتى لو الكود المستدعي مرّر
            # عضوية خطأ، الدالة نفسها لا تثق إلا بعضوية المستخدم الحالي
            return False
        domain = [("membership_id", "=", membership.id), ("action_code", "=", action_code)]
        if resource_model:
            domain.append(("resource_model", "in", (resource_model, False)))
        return bool(self.sudo().search_count(domain))
