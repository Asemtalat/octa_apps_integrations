# -*- coding: utf-8 -*-
"""
octa.hub.catalog.item / .modifier.group / .modifier / .price.override —
أول نماذج Odoo فعلية للمنيو والإضافات (القسم 2، مراجعة بوابة هنقرستيشن).
NOT RUN.

كان القسم 2 بالكامل منطقًا معزولًا فقط (lib/price_resolution.py،
lib/modifier_rules.py، tools/catalog_reconcile/reconcile.py) بلا أي نموذج
Odoo فعلي يخزّن منتجًا أو إضافة حقيقية. هذا أول ربط فعلي — النماذج هنا
تخزّن البيانات، والمنطق المُختبَر بمعزل عن Odoo (22 اختبار PASS عبر
الوحدتين) يبقى مصدر الحقيقة للقرارات (حل السعر، قواعد الاختيار)، تُستدعى
من هنا لا تُعاد كتابتها.

كل صنف مرتبط بـstorefront (لا بفرع مباشرة) — لأن قوائم البراندات المختلفة
لنفس الموقع الفعلي (مطبخ سحابي) مختلفة تمامًا عادة، لا مشتركة.
"""
import os
import sys
from decimal import Decimal

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_LIB_DIR = os.path.join(os.path.dirname(__file__), "..", "lib")
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)


class OctaHubCatalogItem(models.Model):
    """صنف منيو — القسم 2: أسماء/أوصاف مترجمة، صور، SKU، معرّفات خارجية
    مستقرة، معلومات غذائية/حساسية **من التاجر فقط** (لا حقل محسوب أو
    مولَّد تلقائيًا — القسم 2 ينص صراحة: 'دون توليدها أو افتراض صحتها')."""

    _name = "octa.hub.catalog.item"
    _description = "Menu item (product) scoped to a storefront (brand-at-location)"
    _order = "name_ar"

    storefront_id = fields.Many2one("octa.hub.storefront", required=True, ondelete="cascade", index=True)
    organization_id = fields.Many2one(related="storefront_id.organization_id", store=True, index=True)
    name_ar = fields.Char(required=True)
    name_en = fields.Char()
    description_ar = fields.Text()
    description_en = fields.Text()
    sku = fields.Char(index=True)
    external_id = fields.Char(required=True, index=True, help="معرّف خارجي مستقر من نظام POS — مفتاح التسوية، لا الاسم")
    external_version = fields.Integer(default=1, help="يُستخدَم مع reconcile.py لمنع كتابة نسخة أقدم فوق أحدث")
    image_url = fields.Char(help="NOT VERIFIED: تخزين كصورة Binary حقيقية أفضل لبيئة إنتاج؛ رابط مؤقتًا")
    category = fields.Char()
    base_price_minor_units = fields.Integer(required=True, help="السعر الأساسي — القنوات تُخصَّص عبر price.override لا بالكتابة فوق هذا الحقل")
    currency_id = fields.Many2one("res.currency", required=True)
    # القسم 2.5 حرفيًا: "احتفظ بالمعلومات الغذائية والحساسية التي يقدمها
    # التاجر، دون توليدها أو افتراض صحتها" — نص حر يدخله التاجر، لا حساب.
    nutrition_info = fields.Text(help="نص حر يُدخله التاجر — لا يُولَّد أو يُشتق آليًا بأي شكل")
    allergen_info = fields.Text(help="نص حر يُدخله التاجر — لا يُولَّد أو يُشتق آليًا بأي شكل")
    modifier_group_ids = fields.Many2many(
        "octa.hub.modifier.group", "octa_hub_item_modifier_group_rel",
        "item_id", "group_id", string="مجموعات الإضافات",
        help="Many2many فعلي — نفس مجموعة الإضافات قابلة للربط بعدة أصناف، كما ينص القسم 2")
    price_override_ids = fields.One2many("octa.hub.price.override", "item_id")
    active = fields.Boolean(default=True)

    _uniq_storefront_external_id = models.Constraint(
        "unique(storefront_id, external_id)",
        "external_id هو مفتاح التسوية الحقيقي — لا الاسم (القسم 2: 'لا تستخدم الاسم مفتاحًا لمنع التكرار')")

    def resolve_price(self, channel_code, requested_currency=None):
        """يستدعي lib/price_resolution.py المُختبَرة (13/13 PASS) — لا يعيد
        كتابة منطق الحل هنا. NOT VERIFIED: لم يُشغَّل هذا الاستدعاء فعليًا
        ضد Odoo (لا Odoo متاح)."""
        from price_resolution import PriceOverride, resolve_price as _resolve_price
        self.ensure_one()
        currency_code = requested_currency or self.currency_id.name
        overrides = [PriceOverride(
            product_id=str(self.id), branch_id=None, channel_id=None,
            amount=Decimal(self.base_price_minor_units) / 100,
            currency=self.currency_id.name, tax_inclusive=True, version=self.external_version, source="base",
        )]
        for po in self.price_override_ids:
            overrides.append(PriceOverride(
                product_id=str(self.id), branch_id=None, channel_id=po.channel_code,
                amount=Decimal(po.amount_minor_units) / 100,
                currency=po.currency_id.name, tax_inclusive=True, version=po.version, source="channel_override",
                # إصلاح حرج (طلب صريح: "أصلح تمرير allow_zero"): كانت هذه
                # القيمة **تُسقَط صامتًا** هنا — po.allow_zero لم يكن يصل
                # إطلاقًا لكائن PriceOverride المُمرَّر لمنطق الحل، فيرث
                # القيمة الافتراضية False دائمًا بصرف النظر عمّا خزَّنه
                # المستخدم فعليًا. أي تخصيص سعر بصفر فعلي (allow_zero=True
                # مخزَّنة) كان سيُرفَض خطأً بـZeroPriceNotAllowedError رغم
                # سماح المستخدم الصريح به.
                allow_zero=po.allow_zero,
            ))
        return _resolve_price(overrides, branch_id="n/a", channel_id=channel_code,
                               base_currency=currency_code, base_tax_inclusive=True)

    @api.constrains("base_price_minor_units")
    def _check_base_price_not_negative(self):
        """إصلاح: لا شيء كان يمنع سعرًا أساسيًا سالبًا. صفر منفصل تمامًا عن
        السالب — allow_zero (على price.override) يخص الصفر فقط، لا يُستخدَم
        أبدًا لتبرير قيمة سالبة، والسعر الأساسي هنا لا allow_zero له إطلاقًا
        (القاعدة: السعر الأساسي دائمًا > 0؛ الصفر يُعبَّر عنه فقط عبر
        تخصيص قناة صريح بـallow_zero=True، لا كسعر أساسي)."""
        for rec in self:
            if rec.base_price_minor_units < 0:
                raise ValidationError(_("السعر الأساسي لا يمكن أن يكون سالبًا"))


class OctaHubModifierGroup(models.Model):
    """مجموعة إضافات — القسم 2 ينص حرفيًا: 'لا تستخدم الاسم مفتاحًا لمنع
    التكرار؛ قد توجد مجموعات مختلفة تحمل الاسم نفسه' — **عمدًا لا يوجد أي
    قيد تفرّد على name أدناه**."""

    _name = "octa.hub.modifier.group"
    _description = "Reusable modifier group, linkable to multiple items"

    name = fields.Char(required=True)  # عمدًا بلا unique — راجع التوثيق أعلاه
    organization_id = fields.Many2one("octa.hub.organization", required=True, ondelete="cascade", index=True)
    # إصلاح (طلب صريح: "أكمل هوية مجموعات الإضافات"): لم يكن للمجموعة
    # نفسها أي معرّف خارجي مستقر إطلاقًا — فقط الخيارات الفردية (modifier)
    # كانت تملك external_id. بلا هوية للمجموعة نفسها، لا توجد طريقة موثوقة
    # لمطابقة "نفس المجموعة" عند إعادة استيراد من POS (فقط الأسماء، والقسم
    # 2 يمنع صراحة استخدام الاسم كمفتاح). external_id هنا اختياري (بعض
    # المجموعات قد تُنشأ يدويًا من الواجهة بلا مصدر POS خارجي)، لكن حين
    # يُذكر يجب أن يكون فريدًا ضمن نفس المنظمة (نطاق المصدر الصحيح — لا
    # عبر كل المنظمات، منظمات مختلفة قد تستورد من نفس نظام POS بمعرّفات
    # متشابهة مصادفةً بلا تعارض حقيقي).
    external_id = fields.Char(index=True, help="معرّف خارجي مستقر من POS لمطابقة المجموعة نفسها عبر إعادة الاستيراد — اختياري لمجموعات مُنشأة يدويًا")
    min_select = fields.Integer(default=0, required=True)
    max_select = fields.Integer(default=1, required=True)
    mandatory = fields.Boolean(default=False)
    allow_repeat = fields.Boolean(default=False)
    modifier_ids = fields.One2many("octa.hub.modifier", "group_id")
    item_ids = fields.Many2many("octa.hub.catalog.item", "octa_hub_item_modifier_group_rel", "group_id", "item_id")

    _uniq_org_external_id = models.Constraint(
        "unique(organization_id, external_id)",
        "external_id (حين يُذكر) يجب أن يكون فريدًا داخل نفس المنظمة — النطاق الصحيح للمصدر، لا عبر كل المنظمات")

    @api.constrains("min_select", "max_select", "mandatory")
    def _check_selection_bounds(self):
        """يطابق فحص lib/modifier_rules.py::ModifierGroup.__post_init__
        المُختبَر (9/9 PASS) — نفس القاعدة، مُطبَّقة هنا كقيد Odoo حقيقي."""
        for rec in self:
            if rec.min_select > rec.max_select:
                raise ValidationError(_("الحد الأدنى (%s) أكبر من الحد الأقصى (%s)") % (rec.min_select, rec.max_select))
            if rec.mandatory and rec.min_select < 1:
                raise ValidationError(_("مجموعة إلزامية يجب أن يكون حدها الأدنى 1 على الأقل"))

    @api.constrains("item_ids", "organization_id")
    def _check_items_same_tenant(self):
        """إصلاح (طلب صريح: "قيود اتساق التاجر بين العلاقات"): كان
        Many2many بين modifier.group وcatalog.item **بلا أي تحقق تطابق
        منظمة** — تاجر A كان يقدر نظريًا (عبر واجهة إدارية أو RPC) يربط
        مجموعة إضافاته الخاصة بصنف يخص تاجرًا B تمامًا، طالما مرّر معرّف
        الصنف الصحيح. القسم 6/الدرس المتكرر عبر المشروع كله: "كل العلاقات
        بين السجلات تتحقق من تطابق tenant، لا تكتفِ بقواعد البحث" — record
        rules تُقيِّد ما يُعرَض في القوائم، لا ما يُمكن ربطه فعليًا عبر M2M
        بمعرّف مباشر؛ هذا القيد يسدّ تلك الفجوة تحديدًا."""
        for rec in self:
            mismatched = rec.item_ids.filtered(lambda i: i.organization_id != rec.organization_id)
            if mismatched:
                raise ValidationError(_(
                    "لا يمكن ربط مجموعة إضافات بصنف يخص منظمة مختلفة — الأصناف: %s"
                ) % ", ".join(mismatched.mapped("name_ar")))


class OctaHubModifier(models.Model):
    _name = "octa.hub.modifier"
    _description = "Single modifier option within a group"
    _order = "sequence"

    group_id = fields.Many2one("octa.hub.modifier.group", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    name_ar = fields.Char(required=True)
    name_en = fields.Char()
    external_id = fields.Char(index=True, help="معرّف خارجي للتسوية — لا الاسم (نفس مبدأ catalog.item)")
    price_minor_units = fields.Integer(default=0)
    allow_repeat = fields.Boolean(default=False, help="يمكن أن يختلف عن allow_repeat على مستوى المجموعة")
    active = fields.Boolean(default=True)

    # إصلاح (طلب صريح: "أكمل هوية... ومنع تكرارها ضمن نطاق المصدر الصحيح"):
    # لم يكن يوجد أي قيد تفرّد على external_id إطلاقًا رغم وجود الحقل —
    # نفس علة "حقل موجود، الوظيفة غير مفعَّلة" المكتشفة مرارًا في جولات
    # سابقة (مثال: superseded_by_id في invitation.py). النطاق الصحيح هنا هو
    # المجموعة الأم (group_id) — نفس معرّف خارجي قد يتكرر بمصادفة عبر
    # مجموعات مختلفة تمامًا بلا تعارض حقيقي (أنظمة POS مختلفة قد تُرقِّم
    # خياراتها محليًا داخل كل مجموعة)، فالتفرّد المُطلَق عبر كل المنظمة كان
    # سيرفض حالات مشروعة خطأً.
    _uniq_group_external_id = models.Constraint(
        "unique(group_id, external_id)",
        "external_id يجب أن يكون فريدًا داخل نفس مجموعة الإضافات (لا عبر المنظمة كلها — مصادر مختلفة قد تُرقِّم محليًا)")

    @api.constrains("price_minor_units")
    def _check_price_not_negative(self):
        for rec in self:
            if rec.price_minor_units < 0:
                raise ValidationError(_("سعر الإضافة لا يمكن أن يكون سالبًا"))


class OctaHubPriceOverride(models.Model):
    """تخصيص سعر لقناة معيّنة — الفرع مُحدَّد ضمنيًا عبر storefront الصنف
    نفسه (storefront = فرع×براند بالفعل)، فالبُعد المتبقي المتغيّر هو
    القناة فقط. يطابق lib/price_resolution.py المُختبَرة تمامًا."""

    _name = "octa.hub.price.override"
    _description = "Per-channel price override for a catalog item (storefront already fixes branch+brand)"

    item_id = fields.Many2one("octa.hub.catalog.item", required=True, ondelete="cascade", index=True)
    channel_code = fields.Char(required=True, help="مثال: 'demo' أو رمز التطبيق")
    amount_minor_units = fields.Integer(required=True)
    currency_id = fields.Many2one("res.currency", required=True)
    version = fields.Integer(default=1)
    allow_zero = fields.Boolean(default=False, help="يطابق allow_zero في price_resolution.py — صفر فعلي يحتاج سماحًا صريحًا")

    @api.constrains("amount_minor_units", "allow_zero")
    def _check_amount_not_negative_and_zero_requires_flag(self):
        """إصلاح (طلب صريح: "منع الأسعار السالبة"): لا سالب مهما كان
        allow_zero — allow_zero يخص الصفر فقط، ليس بديلًا عامًا لتعطيل
        التحقق. صفر بلا allow_zero=True يُرفض هنا أيضًا (بدل الاعتماد فقط
        على lib/price_resolution.py وقت الحل — رفض مبكر عند الحفظ نفسه أوضح)."""
        for rec in self:
            if rec.amount_minor_units < 0:
                raise ValidationError(_("السعر لا يمكن أن يكون سالبًا"))
            if rec.amount_minor_units == 0 and not rec.allow_zero:
                raise ValidationError(_("سعر صفر يتطلب تفعيل allow_zero صراحة"))

    _uniq_item_channel = models.Constraint(
        "unique(item_id, channel_code)", "تخصيص سعر واحد فقط لكل قناة لكل صنف")
