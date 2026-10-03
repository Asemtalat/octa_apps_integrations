# -*- coding: utf-8 -*-
"""
اختبارات Odoo TransactionCase — مكتوبة وفق معرفتي بواجهة اختبار Odoo، لكنها
NOT RUN فعليًا لعدم توفر Odoo 19 + PostgreSQL في بيئة التطوير الحالية.
لا تُحسب PASS. راجع docs/test-report.md وdocs/HANDOFF.md لخطوات التشغيل
الفعلية المطلوبة (Odoo 19 حقيقي + `odoo-bin -i octa_hub_core --test-enable`).

الحالات المغطاة (اسميًا، بانتظار التشغيل الفعلي):
- عميل A لا يقرأ سجلات عميل B عبر ORM.
- مسؤول فرع لا يرى فرعًا آخر لنفس العميل.
- شريك خارج نطاق الـ grant أو منتهي المدة يُرفض.
- تاجر/شريك لا يستطيع إنشاء حساب مباشرة (فقط octatech_identity_admin).
"""
from odoo.tests.common import TransactionCase
from odoo.exceptions import AccessError


class TestTenantIsolation(TransactionCase):

    def setUp(self):
        super().setUp()
        self.org_a = self.env["octa.hub.organization"].create({"name": "Org A"})
        self.org_b = self.env["octa.hub.organization"].create({"name": "Org B"})
        self.branch_a1 = self.env["octa.hub.branch"].create({
            "name": "A-Branch-1", "organization_id": self.org_a.id, "external_branch_id": "A1",
        })
        self.branch_a2 = self.env["octa.hub.branch"].create({
            "name": "A-Branch-2", "organization_id": self.org_a.id, "external_branch_id": "A2",
        })

        self.user_a = self.env["res.users"].create({
            "name": "Owner A", "login": "owner_a@test.local",
            "group_ids": [(4, self.env.ref("octa_hub_core.group_merchant_owner").id)],
        })
        octatech_admin_user = self.env["res.users"].create({
            "name": "Identity Admin", "login": "identity_admin@test.local",
        })
        self.env["octa.hub.membership"].create({
            "user_id": self.user_a.id, "party_type": "merchant", "organization_id": self.org_a.id,
            "role_code": "merchant_owner", "granted_by_user_id": octatech_admin_user.id,
        })

    def test_merchant_a_cannot_read_org_b(self):
        orgs_visible = self.env["octa.hub.organization"].with_user(self.user_a).search([])
        self.assertNotIn(self.org_b.id, orgs_visible.ids, "عميل A لا يجب أن يرى عميل B")

    def test_membership_transfer_revokes_previous_user_group_and_context(self):
        membership = self.env['octa.hub.membership'].search([('user_id', '=', self.user_a.id)])
        self.user_a.active_membership_id = membership
        replacement = self.env['res.users'].create({'name': 'Replacement', 'login': 'replacement@test.local'})
        membership.write({'user_id': replacement.id})
        role = self.env.ref('octa_hub_core.group_merchant_owner')
        self.assertNotIn(role, self.user_a.group_ids)
        self.assertIn(role, replacement.group_ids)
        self.assertFalse(self.user_a.active_membership_id)

    def test_organization_change_invalidates_warmed_record_rule(self):
        membership = self.env['octa.hub.membership'].search([('user_id', '=', self.user_a.id)])
        organizations = self.env['octa.hub.organization'].with_user(self.user_a)
        self.assertIn(self.org_a, organizations.search([]))
        membership.write({'organization_id': self.org_b.id})
        visible = organizations.search([])
        self.assertNotIn(self.org_a, visible)
        self.assertIn(self.org_b, visible)

    def test_deactivation_clears_active_context(self):
        membership = self.env['octa.hub.membership'].search([('user_id', '=', self.user_a.id)])
        self.user_a.active_membership_id = membership
        membership.active = False
        self.assertFalse(self.user_a.active_membership_id)
        self.assertNotIn(self.env.ref('octa_hub_core.group_merchant_owner'), self.user_a.group_ids)

    def test_branch_manager_cannot_see_other_branch(self):
        manager_user = self.env["res.users"].create({"name": "BM", "login": "bm@test.local"})
        octatech_admin_user = self.env["res.users"].search([("login", "=", "identity_admin@test.local")])
        self.env["octa.hub.membership"].create({
            "user_id": manager_user.id, "party_type": "merchant", "organization_id": self.org_a.id,
            "role_code": "merchant_branch_manager", "branch_ids": [(4, self.branch_a1.id)],
            "granted_by_user_id": octatech_admin_user.id,
        })
        visible_branches = self.env["octa.hub.branch"].with_user(manager_user).search([])
        self.assertIn(self.branch_a1.id, visible_branches.ids)
        self.assertNotIn(self.branch_a2.id, visible_branches.ids)

    def test_merchant_cannot_create_account_directly(self):
        with self.assertRaises(AccessError):
            self.env["octa.hub.invitation"].with_user(self.user_a).create({
                "email": "someone@test.local", "purpose": "initial_invite",
                "token_hash": "x", "expires_at": "2099-01-01 00:00:00",
                "created_by_user_id": self.user_a.id,
            })

    def test_expired_partner_grant_is_rejected(self):
        from datetime import datetime, timedelta
        partner_user = self.env["res.users"].create({"name": "Partner", "login": "partner@test.local"})
        octatech_admin_user = self.env["res.users"].search([("login", "=", "identity_admin@test.local")])
        membership = self.env["octa.hub.membership"].create({
            "user_id": partner_user.id, "party_type": "partner",
            "role_code": "partner_tech", "granted_by_user_id": octatech_admin_user.id,
        })
        grant = self.env["octa.hub.partner.grant"].create({
            "partner_membership_id": membership.id, "organization_id": self.org_a.id,
            "allowed_action_codes": "read",
            "granted_by_user_id": self.user_a.id,
            "expires_at": (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
        })
        with self.assertRaises(AccessError):
            grant.check_access_or_raise("read")

    def test_connection_auto_links_matching_connector_definition_on_create(self):
        """إصلاح بعد مراجعة خامسة عشرة (فحص ذاتي): بلا هذا الربط التلقائي،
        كل اتصال جديد كان سيُرفَض له كل طلب فورًا (capability_unsupported)
        لغياب connector_definition_id — قيد أمان صحيح لكنه كان سيكسر أي
        اتصال حقيقي بديهيًا. يثبت هنا أن الإنشاء يربط تلقائيًا لو وُجد
        تعريف مطابق، ولا يخترع رابطًا لو لم يوجد.

        إصلاح إضافي (اكتُشف بتشغيل فعلي حقيقي): كانت تنشئ الاتصال بـ
        branch_id مباشرة — حقل أصبح `related` للقراءة فقط منذ إعادة هيكلة
        storefront (القسم 1، الجولة السادسة عشرة)؛ الكتابة المباشرة عليه
        كانت ستفشل بصمت (تُتجاهَل) أو تفشل بخطأ ORM، ولم يُكتشَف لأن هذا
        الاختبار لم يُشغَّل فعليًا قط حتى الآن. أُصلح بإنشاء storefront أولًا."""
        brand = self.env["octa.hub.brand"].create({"name": "Test Brand", "organization_id": self.org_a.id})
        storefront = self.env["octa.hub.storefront"].create({
            "name": "Test Storefront", "branch_id": self.branch_a1.id, "brand_id": brand.id,
        })
        definition = self.env["octa.hub.connector.definition"].create({
            "connector_code": "test_connector_xyz", "contract_version": "v1",
        })
        connection = self.env["octa.hub.connection"].create({
            "storefront_id": storefront.id, "connector_code": "test_connector_xyz",
        })
        self.assertEqual(connection.connector_definition_id.id, definition.id)

    def test_connection_with_unknown_connector_code_has_no_definition_linked(self):
        """لا تعريف مطابق = لا ربط مُختلَق — الرفض الأمني يبقى فعّالًا كما
        يجب، لا افتراض بديل خاطئ صامت."""
        brand = self.env["octa.hub.brand"].create({"name": "Test Brand 2", "organization_id": self.org_a.id})
        storefront = self.env["octa.hub.storefront"].create({
            "name": "Test Storefront 2", "branch_id": self.branch_a1.id, "brand_id": brand.id,
        })
        connection = self.env["octa.hub.connection"].create({
            "storefront_id": storefront.id, "connector_code": "does_not_exist_anywhere",
        })
        self.assertFalse(connection.connector_definition_id)
