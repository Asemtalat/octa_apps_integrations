# -*- coding: utf-8 -*-
"""
octa.hub.storefront — "متجر تطبيق" (Storefront/Virtual Brand Presence)،
القسم 1 من مراجعة بوابة هنقرستيشن. NOT RUN.

يحل فجوة حقيقية: `octa.hub.branch` كان يملك `brand_id` بعلاقة Many2one
مباشرة (فرع واحد = براند واحد على الأكثر) — لا يدعم "أكثر من براند أو
مطعم افتراضي داخل موقع واحد" (مطبخ سحابي يقدّم عدة براندات من نفس الموقع
الفعلي، شائع جدًا في تطبيقات التوصيل). الـStorefront نموذج وسيط: (فرع
فعلي × براند) — يمكن لنفس الفرع أن يملك عدة Storefronts ببراندات مختلفة،
وكل Storefront له اتصالاته الخاصة بمتاجر التطبيقات (أسعار/توفر/معرّف
مستقلين لكل تطبيق، ووجهة POS صحيحة).

`octa.hub.connection` أصبح يرتبط بـstorefront_id (لا branch_id مباشرة) —
`branch_id` على الاتصال أصبح حقل related محسوبًا من storefront_id.branch_id
للحفاظ على توافق كل الكود القائم (controller/tests) دون تغيير.
"""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class OctaHubStorefront(models.Model):
    """"متجر تطبيق" — تمثيل براند معيّن كما يُعرَض في موقع فعلي معيّن.
    نفس الفرع الفعلي (kitchen واحد) قد يملك عدة Storefronts ببراندات
    مختلفة — هذا بالضبط ما يسمح بدعم "مطعم افتراضي" (virtual brand)."""

    _name = "octa.hub.storefront"
    _description = "Brand presence at a physical branch (supports multi-brand per location)"

    name = fields.Char(required=True, help="اسم العرض لهذا المتجر الافتراضي، قد يختلف عن اسم البراند نفسه")
    branch_id = fields.Many2one("octa.hub.branch", required=True, ondelete="cascade", index=True,
                                 help="الموقع الفعلي (kitchen/store) — قد يستضيف عدة storefronts")
    brand_id = fields.Many2one("octa.hub.brand", required=True, ondelete="restrict", index=True)
    organization_id = fields.Many2one(related="branch_id.organization_id", store=True, index=True)
    connection_ids = fields.One2many("octa.hub.connection", "storefront_id", string="اتصالات متاجر التطبيقات")
    active = fields.Boolean(default=True)

    _uniq_branch_brand = models.Constraint(
        "unique(branch_id, brand_id)",
        "نفس البراند لا يتكرر أكثر من مرة لنفس الفرع — أنشئ اسم عرض مختلف بدل ذلك لو أردت تمييزًا آخر")

    @api.constrains("brand_id", "branch_id")
    def _check_brand_same_tenant(self):
        """نفس قاعدة العزل الموجودة في branch.py::brand_id سابقًا، منقولة
        هنا الآن لأن storefront هو حامل العلاقة الفعلي بين الفرع والبراند."""
        for rec in self:
            if rec.brand_id.organization_id != rec.branch_id.organization_id:
                raise ValidationError(_("البراند المرتبط يجب أن ينتمي لنفس عميل هذا الفرع"))
