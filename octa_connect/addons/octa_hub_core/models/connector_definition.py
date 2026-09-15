# -*- coding: utf-8 -*-
"""
octa.hub.connector.definition / .capability.line — تخزين دائم لقدرات كل
موصل (R12، Gate E). NOT RUN.

إصلاح بعد مراجعة V2 المستقلة: `_enforce_orders_capability` في
`api_controller.py` كانت تبني `ConnectorDefinition` **مؤقتًا داخل كل
استدعاء**، تفترض أن `Capability.ORDERS` مدعومة دائمًا بصرف النظر عن أي
بيانات فعلية — لا كان هذا يمثّل قدرات الموصل الحقيقية، بل افتراضًا ثابتًا.
هذا أول تخزين دائم فعلي لقدرات الموصلات، يعكس بنية
`lib/connector_capabilities.py` المُختبَرة (6/6 PASS) في نموذجي Odoo حقيقيين.
"""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

CAPABILITY_CHOICES = [
    ("orders", "الطلبات"), ("cancel", "الإلغاء"), ("status_updates", "تحديثات الحالة"),
    ("menu", "المنيو"), ("prices", "الأسعار"), ("availability", "التوفر"),
    ("pause", "الإيقاف المؤقت"), ("scheduling", "الجدولة"), ("query", "الاستعلام"),
    ("idempotency", "منع التكرار"), ("reconciliation", "المطابقة"),
]
STATUS_CHOICES = [
    ("supported", "مدعومة"), ("unsupported", "غير مدعومة"), ("not_verified", "غير مؤكَّدة"),
]


class OctaHubConnectorDefinition(models.Model):
    """تعريف الموصل نفسه — مشترك بين كل التجار الذين يستخدمونه، لا يُفرَّع
    الكود لكل تاجر (القسم 5)."""

    _name = "octa.hub.connector.definition"
    _description = "Connector definition with persisted capability matrix (R12)"

    connector_code = fields.Char(required=True, index=True)
    contract_version = fields.Char(required=True)
    capability_line_ids = fields.One2many(
        "octa.hub.connector.capability.line", "definition_id", string="القدرات")

    _uniq_connector_code = models.Constraint(
        "unique(connector_code)", "لا يمكن تكرار نفس رمز الموصل في أكثر من تعريف")

    def capability_status(self, capability_code):
        """يُرجع 'supported'/'unsupported'/'not_verified' — deny-by-default
        (غير مدعومة) لو القدرة غير مذكورة إطلاقًا في السطور، بدل افتراض
        الدعم صامتًا (نفس مبدأ lib/connector_capabilities.py المُختبَر)."""
        self.ensure_one()
        line = self.capability_line_ids.filtered(lambda l: l.capability == capability_code)
        return line.status if line else "unsupported"


class OctaHubConnectorCapabilityLine(models.Model):
    _name = "octa.hub.connector.capability.line"
    _description = "Single capability status for a connector definition (R12)"

    definition_id = fields.Many2one("octa.hub.connector.definition", required=True, ondelete="cascade", index=True)
    capability = fields.Selection(CAPABILITY_CHOICES, required=True)
    status = fields.Selection(STATUS_CHOICES, required=True, default="unsupported")

    _uniq_definition_capability = models.Constraint(
        "unique(definition_id, capability)", "نفس القدرة لا تتكرر لنفس تعريف الموصل")
