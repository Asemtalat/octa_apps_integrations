# -*- coding: utf-8 -*-
"""octa.hub.audit.log — سجل تدقيق أساسي (القسم 6: الوصول الاستثنائي له سبب
وصلاحية ومدة وتدقيق). NOT RUN."""
from odoo import fields, models


class OctaHubAuditLog(models.Model):
    _name = "octa.hub.audit.log"
    _description = "Audit trail for sensitive actions"
    _order = "create_date desc"

    actor_user_id = fields.Many2one("res.users", required=True, index=True)
    organization_id = fields.Many2one("octa.hub.organization", index=True)
    action_code = fields.Char(required=True)
    target_model = fields.Char()
    target_res_id = fields.Integer()
    reason = fields.Char(help="سبب الوصول الاستثنائي، إن وجد")
    exceptional_access = fields.Boolean(default=False)
    exceptional_access_expires_at = fields.Datetime()
    metadata_json = fields.Char(help="سياق إضافي غير حساس فقط — لا أسرار ولا OTP ولا Authorization headers هنا")

    @staticmethod
    def redact(payload: dict) -> dict:
        """يزيل الحقول الحساسة قبل أي تخزين/تصدير للسجل — القسم 8:
        'لا أسرار أو OTP أو Authorization headers أو أجسام شخصية كاملة
        في السجلات والتقارير'."""
        blocked_keys = {"password", "otp", "authorization", "token", "secret", "api_key"}
        return {k: v for k, v in payload.items() if k.lower() not in blocked_keys}
