# -*- coding: utf-8 -*-
"""
اختبارات Odoo TransactionCase فعلية لنماذج المنيو (catalog.py) — طلب صريح:
"أضف اختبارات Odoo فعلية للحفظ والصلاحيات والعلاقات والقيود؛ وجود اختبارات
للمنطق المنعزل أو بيانات Demo لا يثبت صحة النماذج الجديدة". هذا صحيح تمامًا
— كل الاختبارات المُختبَرة فعليًا (13/13 لـprice_resolution، 9/9 لـ
modifier_rules) تثبت المنطق المعزول فقط، لا القيود/العلاقات/الصلاحيات
الفعلية على نماذج Odoo نفسها. هذا الملف يسد تلك الفجوة تحديدًا.

مكتوبة وفق معرفتي بواجهة اختبار Odoo، لكنها **NOT RUN فعليًا** لعدم توفر
Odoo 19 + PostgreSQL في بيئة التطوير الحالية — نفس القيد المُعلَن في كل
ملفات هذا المشروع. لا تُحسب PASS.
"""
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger
from odoo.exceptions import ValidationError, AccessError
import psycopg2


class TestCatalogModels(TransactionCase):

    def setUp(self):
        super().setUp()
        self.org_a = self.env["octa.hub.organization"].create({"name": "Org A"})
        self.org_b = self.env["octa.hub.organization"].create({"name": "Org B"})
        self.branch_a = self.env["octa.hub.branch"].create({
            "name": "A-Branch-1", "organization_id": self.org_a.id, "external_branch_id": "A1",
        })
        self.brand_a1 = self.env["octa.hub.brand"].create({"name": "Brand A1", "organization_id": self.org_a.id})
        self.brand_a2 = self.env["octa.hub.brand"].create({"name": "Brand A2 (virtual)", "organization_id": self.org_a.id})
        self.storefront_a1 = self.env["octa.hub.storefront"].create({
            "name": "Storefront A1", "branch_id": self.branch_a.id, "brand_id": self.brand_a1.id,
        })
        self.branch_b = self.env["octa.hub.branch"].create({
            "name": "B-Branch-1", "organization_id": self.org_b.id, "external_branch_id": "B1",
        })
        self.brand_b = self.env["octa.hub.brand"].create({"name": "Brand B", "organization_id": self.org_b.id})
        self.storefront_b = self.env["octa.hub.storefront"].create({
            "name": "Storefront B", "branch_id": self.branch_b.id, "brand_id": self.brand_b.id,
        })
        self.sar = self.env.ref("base.SAR")
        self.merchant_a_user = self.env["res.users"].create({
            "name": "Owner A", "login": "owner_a_catalog@test.local",
            "group_ids": [(4, self.env.ref("octa_hub_core.group_merchant_owner").id)],
        })
        octatech_admin_user = self.env["res.users"].create({
            "name": "Identity Admin", "login": "identity_admin_catalog@test.local",
            "group_ids": [(4, self.env.ref("octa_hub_core.group_octatech_identity_admin").id)],
        })
        self.env["octa.hub.membership"].create({
            "user_id": self.merchant_a_user.id, "organization_id": self.org_a.id,
            "party_type": "merchant", "role_code": "merchant_owner",
            "granted_by_user_id": octatech_admin_user.id,
        })

    # --- الحفظ الأساسي (Save) ---

    def test_catalog_item_saves_successfully(self):
        item = self.env["octa.hub.catalog.item"].create({
            "storefront_id": self.storefront_a1.id, "name_ar": "برجر", "external_id": "SKU-1",
            "base_price_minor_units": 3000, "currency_id": self.sar.id,
        })
        self.assertTrue(item.id)
        self.assertEqual(item.organization_id, self.org_a)  # related field محسوب بشكل صحيح

    def test_modifier_group_with_two_items_saves_and_relation_works(self):
        """اختبار علاقة فعلي: مجموعة واحدة مرتبطة بصنفين — القسم 2."""
        item1 = self.env["octa.hub.catalog.item"].create({
            "storefront_id": self.storefront_a1.id, "name_ar": "برجر", "external_id": "SKU-1",
            "base_price_minor_units": 3000, "currency_id": self.sar.id,
        })
        item2 = self.env["octa.hub.catalog.item"].create({
            "storefront_id": self.storefront_a1.id, "name_ar": "بطاطس", "external_id": "SKU-2",
            "base_price_minor_units": 1200, "currency_id": self.sar.id,
        })
        group = self.env["octa.hub.modifier.group"].create({
            "name": "الحجم", "organization_id": self.org_a.id,
            "min_select": 1, "max_select": 1, "mandatory": True,
            "item_ids": [(4, item1.id), (4, item2.id)],
        })
        self.assertEqual(len(group.item_ids), 2)
        self.assertIn(item1, group.item_ids)
        self.assertIn(item2, group.item_ids)

    # --- القيود (Constraints) ---

    def test_catalog_item_negative_base_price_rejected(self):
        with self.assertRaises(ValidationError):
            self.env["octa.hub.catalog.item"].create({
                "storefront_id": self.storefront_a1.id, "name_ar": "خطأ", "external_id": "SKU-NEG",
                "base_price_minor_units": -100, "currency_id": self.sar.id,
            })

    def test_price_override_negative_amount_rejected(self):
        item = self.env["octa.hub.catalog.item"].create({
            "storefront_id": self.storefront_a1.id, "name_ar": "صنف", "external_id": "SKU-3",
            "base_price_minor_units": 1000, "currency_id": self.sar.id,
        })
        with self.assertRaises(ValidationError):
            self.env["octa.hub.price.override"].create({
                "item_id": item.id, "channel_code": "demo", "amount_minor_units": -50, "currency_id": self.sar.id,
            })

    def test_price_override_zero_without_allow_zero_rejected(self):
        item = self.env["octa.hub.catalog.item"].create({
            "storefront_id": self.storefront_a1.id, "name_ar": "صنف", "external_id": "SKU-4",
            "base_price_minor_units": 1000, "currency_id": self.sar.id,
        })
        with self.assertRaises(ValidationError):
            self.env["octa.hub.price.override"].create({
                "item_id": item.id, "channel_code": "demo", "amount_minor_units": 0,
                "currency_id": self.sar.id, "allow_zero": False,
            })

    def test_price_override_zero_with_allow_zero_succeeds(self):
        """إصلاح صريح مُختبَر هنا: allow_zero يجب أن يُمرَّر وتُحترَم قيمته."""
        item = self.env["octa.hub.catalog.item"].create({
            "storefront_id": self.storefront_a1.id, "name_ar": "صنف", "external_id": "SKU-5",
            "base_price_minor_units": 1000, "currency_id": self.sar.id,
        })
        override = self.env["octa.hub.price.override"].create({
            "item_id": item.id, "channel_code": "demo", "amount_minor_units": 0,
            "currency_id": self.sar.id, "allow_zero": True,
        })
        self.assertTrue(override.id)

    def test_modifier_negative_price_rejected(self):
        group = self.env["octa.hub.modifier.group"].create({"name": "إضافات", "organization_id": self.org_a.id})
        with self.assertRaises(ValidationError):
            self.env["octa.hub.modifier"].create({
                "group_id": group.id, "name_ar": "إضافة سالبة", "price_minor_units": -10,
            })

    def test_modifier_group_min_greater_than_max_rejected(self):
        with self.assertRaises(ValidationError):
            self.env["octa.hub.modifier.group"].create({
                "name": "خطأ", "organization_id": self.org_a.id, "min_select": 3, "max_select": 1,
            })

    def test_modifier_group_mandatory_requires_min_at_least_1(self):
        with self.assertRaises(ValidationError):
            self.env["octa.hub.modifier.group"].create({
                "name": "خطأ", "organization_id": self.org_a.id, "mandatory": True, "min_select": 0, "max_select": 1,
            })

    def test_modifier_group_name_can_duplicate_no_unique_constraint(self):
        """القبول الحرفي (القسم 2): 'لا تستخدم الاسم مفتاحًا لمنع التكرار؛
        قد توجد مجموعات مختلفة تحمل الاسم نفسه' — يجب أن ينجح هذا فعليًا."""
        g1 = self.env["octa.hub.modifier.group"].create({"name": "الحجم", "organization_id": self.org_a.id})
        g2 = self.env["octa.hub.modifier.group"].create({"name": "الحجم", "organization_id": self.org_a.id})
        self.assertNotEqual(g1.id, g2.id)  # سجلان منفصلان تمامًا بنفس الاسم، بلا استثناء

    def test_modifier_group_cannot_link_item_from_different_organization(self):
        """قيد اتساق التاجر — إصلاح صريح مُختبَر هنا."""
        item_b = self.env["octa.hub.catalog.item"].create({
            "storefront_id": self.storefront_b.id, "name_ar": "صنف ب", "external_id": "SKU-B-1",
            "base_price_minor_units": 1000, "currency_id": self.sar.id,
        })
        with self.assertRaises(ValidationError):
            self.env["octa.hub.modifier.group"].create({
                "name": "مجموعة أ", "organization_id": self.org_a.id,
                "item_ids": [(4, item_b.id)],  # صنف من منظمة مختلفة تمامًا
            })

    def test_modifier_external_id_unique_within_group_but_not_across_groups(self):
        """منع التكرار ضمن نطاق المصدر الصحيح: نفس external_id يتكرر خطأً
        داخل نفس المجموعة يُرفض، لكن نفس القيمة عبر مجموعتين مختلفتين
        مسموحة (مصادر POS مختلفة قد ترقّم محليًا).

        إصلاح بعد تشغيل فعلي حقيقي: كانت تتوقع `ValidationError` — خطأ.
        القيد `_uniq_group_external_id` هو `models.Constraint` (قيد قاعدة
        بيانات SQL حقيقي)، لا `@api.constrains` بايثون؛ الاستثناء الذي
        يصل فعليًا عند `.create()` المباشر هو `psycopg2.IntegrityError`
        الخام — تحقَّقت هذا بالتشغيل الفعلي، لا بالقراءة. ويجب حماية بقية
        الاختبار بـ`cr.savepoint()` (نفس نمط api_controller.py المُتحقَّق
        سابقًا من مصدر Odoo 19) — بلا هذا، القيد الفاشل يُفسد معاملة
        الاختبار بأكملها فلا يمكن تنفيذ أي استعلام تالٍ، بما فيها الجزء
        الثاني من هذا الاختبار نفسه."""
        group1 = self.env["octa.hub.modifier.group"].create({"name": "م1", "organization_id": self.org_a.id})
        group2 = self.env["octa.hub.modifier.group"].create({"name": "م2", "organization_id": self.org_a.id})
        self.env["octa.hub.modifier"].create({"group_id": group1.id, "name_ar": "خيار1", "external_id": "OPT-1"})
        with self.assertRaises(psycopg2.IntegrityError), mute_logger('odoo.sql_db'):
            with self.env.cr.savepoint():
                self.env["octa.hub.modifier"].create(
                    {"group_id": group1.id, "name_ar": "خيار مكرر", "external_id": "OPT-1"})
        # نفس القيمة في مجموعة مختلفة تمامًا — يجب أن تنجح (المعاملة سليمة، السطر أعلاه محمي بـsavepoint)
        modifier_other_group = self.env["octa.hub.modifier"].create(
            {"group_id": group2.id, "name_ar": "خيار في مجموعة أخرى", "external_id": "OPT-1"})
        self.assertTrue(modifier_other_group.id)

    def test_modifier_group_external_id_unique_within_organization(self):
        """نفس تصحيح الاختبار السابق تمامًا — psycopg2.IntegrityError خام
        محمي بـcr.savepoint()، لا ValidationError."""
        self.env["octa.hub.modifier.group"].create(
            {"name": "م1", "organization_id": self.org_a.id, "external_id": "GRP-EXT-1"})
        with self.assertRaises(psycopg2.IntegrityError), mute_logger('odoo.sql_db'):
            with self.env.cr.savepoint():
                self.env["octa.hub.modifier.group"].create(
                    {"name": "م2", "organization_id": self.org_a.id, "external_id": "GRP-EXT-1"})
        # نفس القيمة لمنظمة مختلفة تمامًا — يجب أن تنجح (نطاق المصدر الصحيح هو المنظمة، لا عبر الكل)
        other_org_group = self.env["octa.hub.modifier.group"].create(
            {"name": "م3", "organization_id": self.org_b.id, "external_id": "GRP-EXT-1"})
        self.assertTrue(other_org_group.id)

    def test_catalog_item_external_id_unique_within_storefront(self):
        """إصلاح بعد تشغيل فعلي حقيقي: نفس تصحيح اختبارات modifier أعلاه —
        psycopg2.IntegrityError خام محمي بـcr.savepoint()، لا ValidationError."""
        self.env["octa.hub.catalog.item"].create({
            "storefront_id": self.storefront_a1.id, "name_ar": "صنف", "external_id": "SKU-DUP",
            "base_price_minor_units": 1000, "currency_id": self.sar.id,
        })
        with self.assertRaises(psycopg2.IntegrityError), mute_logger('odoo.sql_db'):
            with self.env.cr.savepoint():
                self.env["octa.hub.catalog.item"].create({
                    "storefront_id": self.storefront_a1.id, "name_ar": "صنف مكرر", "external_id": "SKU-DUP",
                    "base_price_minor_units": 2000, "currency_id": self.sar.id,
                })

    # --- Storefront: نقطة القسم 1 الأساسية ---

    def test_storefront_supports_two_brands_at_same_physical_branch(self):
        """القبول الحرفي (القسم 1): 'ادعم وجود أكثر من براند أو مطعم
        افتراضي داخل موقع واحد' — نفس self.branch_a يستضيف الآن براندين."""
        storefront_2 = self.env["octa.hub.storefront"].create({
            "name": "Storefront A2 (نفس المطبخ)", "branch_id": self.branch_a.id, "brand_id": self.brand_a2.id,
        })
        self.assertEqual(storefront_2.branch_id, self.storefront_a1.branch_id)  # نفس الموقع الفعلي فعلًا
        self.assertNotEqual(storefront_2.brand_id, self.storefront_a1.brand_id)  # براند مختلف فعلًا

    def test_connection_allows_same_connector_for_two_storefronts_same_branch(self):
        """إصلاح ذاتي اكتُشف أثناء بناء storefront: القيد القديم
        unique(branch_id, connector_code) كان سيمنع هذا بالضبط."""
        storefront_2 = self.env["octa.hub.storefront"].create({
            "name": "Storefront A2", "branch_id": self.branch_a.id, "brand_id": self.brand_a2.id,
        })
        conn1 = self.env["octa.hub.connection"].create({
            "storefront_id": self.storefront_a1.id, "connector_code": "demo",
        })
        conn2 = self.env["octa.hub.connection"].create({
            "storefront_id": storefront_2.id, "connector_code": "demo",  # نفس الموصل، نفس الفرع، storefront مختلف
        })
        self.assertEqual(conn1.branch_id, conn2.branch_id)  # نفس الفرع الفعلي (related field)
        self.assertNotEqual(conn1.storefront_id, conn2.storefront_id)

    # --- الصلاحيات (Permissions) ---

    def test_merchant_a_cannot_read_org_b_catalog_item_via_record_rule(self):
        """اختبار صلاحية فعلي — لا مجرد فحص منطق معزول."""
        item_b = self.env["octa.hub.catalog.item"].create({
            "storefront_id": self.storefront_b.id, "name_ar": "صنف ب سري", "external_id": "SKU-B-SECRET",
            "base_price_minor_units": 500, "currency_id": self.sar.id,
        })
        found = self.env["octa.hub.catalog.item"].with_user(self.merchant_a_user).search(
            [("id", "=", item_b.id)])
        self.assertFalse(found, "التاجر A لا يجب أن يرى صنف عميل B عبر record rule")

    def test_merchant_a_can_read_own_org_catalog_item(self):
        item_a = self.env["octa.hub.catalog.item"].create({
            "storefront_id": self.storefront_a1.id, "name_ar": "صنفي", "external_id": "SKU-MINE",
            "base_price_minor_units": 500, "currency_id": self.sar.id,
        })
        found = self.env["octa.hub.catalog.item"].with_user(self.merchant_a_user).search(
            [("id", "=", item_a.id)])
        self.assertTrue(found, "التاجر A يجب أن يرى أصنافه الخاصة")
