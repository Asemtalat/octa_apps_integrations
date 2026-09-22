from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestMerchantPortal(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.org = cls.env['octa.hub.organization'].create({'name': 'Portal Alpha'})
        cls.other_org = cls.env['octa.hub.organization'].create({'name': 'SECRET_OTHER_MERCHANT'})
        cls.user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Portal Test Owner', 'login': 'octa_portal_test',
            'password': 'Synthetic-Portal-Test-Only-2026',
            'group_ids': [(6, 0, [cls.env.ref('base.group_portal').id])],
        })
        cls.membership = cls.env['octa.hub.membership'].create({
            'user_id': cls.user.id, 'party_type': 'merchant',
            'organization_id': cls.org.id, 'role_code': 'merchant_owner',
            'granted_by_user_id': cls.env.uid,
        })

    def login_merchant(self):
        self.authenticate('octa_portal_test', 'Synthetic-Portal-Test-Only-2026')

    def test_portal_user_can_open_all_sections(self):
        self.login_merchant()
        self.assertFalse(self.user.has_group('base.group_user'))
        for section in ['overview', 'orders', 'connections', 'account']:
            response = self.url_open('/octa/portal/' + section)
            self.assertEqual(response.status_code, 200, section)
            self.assertIn('Portal Alpha', response.text)
            self.assertNotIn('SECRET_OTHER_MERCHANT', response.text)
            self.assertEqual(response.headers.get('Cache-Control'), 'private, no-store')

    def test_foreign_organization_is_not_found(self):
        self.login_merchant()
        response = self.url_open('/octa/portal?organization=%s' % self.other_org.id)
        self.assertEqual(response.status_code, 404)
        self.assertNotIn('SECRET_OTHER_MERCHANT', response.text)

    def test_revoked_membership_denied_on_next_request(self):
        self.login_merchant()
        self.membership.active = False
        response = self.url_open('/octa/portal')
        self.assertEqual(response.status_code, 403)
        self.assertNotIn('Portal Alpha', response.text)

    def test_suspended_organization_denied(self):
        self.login_merchant()
        self.org.state = 'suspended'
        self.assertEqual(self.url_open('/octa/portal').status_code, 403)

    def test_anonymous_redirects_to_authentication(self):
        response = self.url_open('/octa/portal', allow_redirects=False)
        self.assertIn(response.status_code, [302, 303])
        self.assertIn('/web/login', response.headers.get('Location', ''))
