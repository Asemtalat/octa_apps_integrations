# -*- coding: utf-8 -*-
"""octa.hub.branch — فرع/Store مستقل تحت عميل معزول (القسم 1). NOT RUN.

إصلاحان بعد مراجعة مستقلة خارجية، مُتحقَّق منهما بمصدر Odoo 19 الحقيقي:
1. `_sql_constraints` — غير مدعومة فعليًا (التفاصيل الكاملة في models/order.py
   أعلى الملف وفي docs/audit-findings.md). حُوِّلت لـ`models.Constraint`.
2. `fields._tz_get` (R01) — **لم يكن هذا مجرد تعليق سابقًا بل خطأ برمجي
   فعلي لم يُصلَح فورًا رغم توثيقه** (اكتُشف لاحقًا عند إعادة الفحص). تحقق
   مباشر من مصدر Odoo 19 (تنزيل حقيقي لفرع 19.0): `odoo/fields.py` لم يعد
   ملفًا مفردًا بل صار حزمة `odoo/fields/`، ولا يحتوي (ولا حاوى من قبل)
   دالة `_tz_get` كسمة له. الدالة الحقيقية معرَّفة في
   `odoo/addons/base/models/res_partner.py` وتُستورَد من وحدات أخرى عبر
   `from odoo.addons.base.models.res_partner import _tz_get` (نمط
   مُتحقَّق منه فعليًا في `addons/hr_holidays`, `addons/event`, `addons/resource`
   ضمن مصدر Odoo 19 نفسه). `fields._tz_get` كانت سترفع `AttributeError`
   فورًا عند تحميل الموديول — مانع تثبيت حقيقي 100%، لا نظري.
"""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.addons.base.models.res_partner import _tz_get

# إصلاح بعد المراجعة السادسة: استيراد مرة واحدة عند تحميل الموديل بدل كل نداء.
import sys as _sys
import os as _os
_LIB_DIR = _os.path.join(_os.path.dirname(__file__), "..", "lib")
if _LIB_DIR not in _sys.path:
    _sys.path.insert(0, _LIB_DIR)
from ssrf_guard import validate_url, SsrfRejected


class OctaHubBranch(models.Model):
    _name = "octa.hub.branch"
    _description = "Octa Connect Branch / Store"
    _order = "name"

    name = fields.Char(required=True)
    organization_id = fields.Many2one("octa.hub.organization", required=True, ondelete="restrict", index=True)
    brand_id = fields.Many2one("octa.hub.brand", ondelete="restrict", index=True,
                                help="OC05-02: الفرع Store مستقل داخل تاجر واحد؛ البراند اختياري إن لم يُصنَّف بعد")
    timezone = fields.Selection(_tz_get, default="Asia/Riyadh", required=True)
    external_pos_system = fields.Char(help="اسم/نوع نظام العميل الخارجي (POS/ERP) — لا نديره، نتصل به فقط")
    external_branch_id = fields.Char(help="معرف الفرع في نظام العميل الخارجي")
    active = fields.Boolean(default=True)

    connection_ids = fields.One2many("octa.hub.connection", "branch_id", string="اتصالات القنوات")

    _uniq_org_external_branch = models.Constraint(
        "unique(organization_id, external_branch_id)",
        "external_branch_id يجب أن يكون فريدًا داخل نفس العميل",
    )

    @api.constrains("organization_id")
    def _check_tenant_present(self):
        for rec in self:
            if not rec.organization_id:
                raise ValidationError("الفرع يجب أن ينتمي لعميل (tenant) — لا فروع بلا مالك")

    @api.constrains("brand_id", "organization_id")
    def _check_brand_same_tenant(self):
        """القسم 6: 'كل العلاقات بين السجلات تتحقق من تطابق tenant'."""
        for rec in self:
            if rec.brand_id and rec.brand_id.organization_id != rec.organization_id:
                raise ValidationError("البراند المرتبط يجب أن ينتمي لنفس عميل هذا الفرع")


class OctaHubConnection(models.Model):
    """اتصال قناة (تطبيق توصيل) لمتجر تطبيق (storefront) معيّن. مرتبط بحساب
    مصرّح به، وليس مجرد اسم تطبيق (القسم 6/13 من الوثيقة الأصلية).

    إصلاح بعد مراجعة بوابة هنقرستيشن (القسم 1): كان الاتصال يرتبط بـ
    `branch_id` مباشرة — فرع واحد = براند واحد ضمنيًا، لا يدعم "أكثر من
    براند أو مطعم افتراضي داخل موقع واحد" (مطبخ سحابي). الآن يرتبط بـ
    `storefront_id` (فرع×براند) — يمكن لعدة storefronts بنفس الفرع أن
    تملك اتصالات منفصلة تمامًا لنفس تطبيق التوصيل أو تطبيقات مختلفة.
    `branch_id` أدناه أصبح حقل related للحفاظ على توافق كل الكود القائم
    (api_controller.py، الاختبارات) دون أي تغيير في تلك الملفات.
    """

    _name = "octa.hub.connection"
    _description = "Delivery App Connection per Storefront (supports multi-brand per branch)"

    storefront_id = fields.Many2one("octa.hub.storefront", required=True, ondelete="cascade", index=True)
    branch_id = fields.Many2one(related="storefront_id.branch_id", store=True, index=True, readonly=True)
    organization_id = fields.Many2one(related="branch_id.organization_id", store=True, index=True)
    connector_code = fields.Char(required=True, help="مثال: 'demo' لموديول octa_hub_connector_demo")
    connector_definition_id = fields.Many2one(
        "octa.hub.connector.definition", ondelete="restrict", index=True,
        help="إصلاح R12: ربط فعلي بقدرات موصل مخزَّنة، بدل افتراض ثابت داخل الكود")
    technically_connected = fields.Boolean(default=False)
    production_approved = fields.Boolean(default=False)
    branch_ready = fields.Boolean(default=False)
    api_key_fingerprint = fields.Char(readonly=True, help="بصمة المفتاح فقط، لا نخزن السر إن لم نحتج استرجاعه")
    callback_url = fields.Char(
        help="عنوان Webhook الذي يدخله العميل/الشريك لاستقبال تحديثات الطلبات "
             "(Blueprint P95/P254) — يخضع لفحص SSRF قبل الحفظ")

    @api.constrains("callback_url")
    def _check_callback_url_is_safe(self):
        """إصلاح بعد المراجعة الرابعة: لم يكن هناك حقل URL واحد في كل
        الموديلات يخضع لأي تحقق SSRF رغم أن القسم 8/23 يشترطه صراحة لأي
        عنوان يُدخله العميل. هذا أول حقل وأول تطبيق فعلي. المنطق مُختبَر
        فعليًا بمعزل عن Odoo في lib/ssrf_guard.py (12/12 PASS بعد إصلاح ثغرة
        حرجة، انظر docs/audit-findings.md#F-SEC-05). resolver الحقيقي هنا
        (socket.getaddrinfo) **تحقَّق منه فعليًا بشبكة حقيقية** خارج pytest
        (`https://pypi.org/` قُبل بصحة، `https://localtest.me/` رُفض بصحة
        لأنه يحل فعليًا إلى 127.0.0.1 — انظر docs/test-results.md) — لكن هذا
        تحقق يدوي منفرد، وليس اختبار آلي مُدمَج ضمن مجموعة pytest بعد.
        """
        import socket

        def _real_resolver(hostname):
            return [info[4][0] for info in socket.getaddrinfo(hostname, None)]

        for rec in self:
            if not rec.callback_url:
                continue
            try:
                validate_url(rec.callback_url, _real_resolver)
            except SsrfRejected as e:
                raise ValidationError(_("عنوان Webhook مرفوض لأسباب أمنية: %s") % e.reason) from e

    _uniq_storefront_connector = models.Constraint(
        "unique(storefront_id, connector_code)",
        "اتصال واحد فقط لكل موصل ولكل متجر تطبيق (storefront) — "
        "مقصود: نفس الفرع الفعلي يمكن أن يملك عدة storefronts (براندات)، "
        "كل واحد باتصاله الخاص لنفس تطبيق التوصيل دون تعارض")

    @api.model_create_multi
    def create(self, vals_list):
        """إصلاح بعد مراجعة خامسة عشرة (فحص ذاتي): كان الحقل الجديد
        `connector_definition_id` (إصلاح R12) **بلا أي ربط تلقائي** — أي
        اتصال جديد يُنشأ (عبر معالج التفعيل أو أي مسار آخر) كان سيبقى بلا
        تعريف قدرة مرتبط، فترفض `_enforce_orders_capability` **كل** طلب له
        بـ"capability_unsupported" — قيد أمان صحيح (deny-by-default) لكنه
        كان سيكسر أي اتصال حقيقي فورًا لغياب خطوة ربط تلقائية بديهية. أُصلح
        بالبحث التلقائي عن تعريف مطابق لنفس `connector_code` عند الإنشاء،
        إن لم يُحدَّد `connector_definition_id` صراحة. لا يُخفي هذا غياب
        تعريف حقيقي: لو لم يوجد تعريف مطابق، يبقى الحقل فارغًا والرفض
        الأمني يعمل كما هو مقصود تمامًا (لا بديل خاطئ يُفترَض صامتًا).
        """
        for vals in vals_list:
            if not vals.get("connector_definition_id") and vals.get("connector_code"):
                matching = self.env["octa.hub.connector.definition"].sudo().search(
                    [("connector_code", "=", vals["connector_code"])], limit=1)
                if matching:
                    vals["connector_definition_id"] = matching.id
        return super().create(vals_list)
