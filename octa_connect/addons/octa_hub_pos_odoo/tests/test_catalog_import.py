from copy import deepcopy
from odoo.tests import TransactionCase, tagged
from odoo.exceptions import AccessError, ValidationError


@tagged('post_install', '-at_install')
class TestPosImport(TransactionCase):
    def setUp(self):
        super().setUp()
        org = self.env['octa.hub.organization'].create({'name': 'POS pilot'})
        branch = self.env['octa.hub.branch'].create({'name': 'Aziziya test', 'organization_id': org.id, 'external_branch_id': 'test-first'})
        brand = self.env['octa.hub.brand'].create({'name': 'Pilot', 'organization_id': org.id})
        store = self.env['octa.hub.storefront'].create({'name': 'Pilot first', 'branch_id': branch.id, 'brand_id': brand.id})
        self.endpoint = self.env['octa.hub.pos.endpoint'].create({'name': 'Test', 'storefront_id': store.id})
        self.endpoint.mapping_ids.create({'endpoint_id': self.endpoint.id, 'pricelist_id_external': 2, 'channel_code': 'hungerstation'})
        self.payload = {'contract': 'octa-pos-catalog-v1', 'currency': 'SAR', 'source_id': 'a' * 32,
            'config_id': 4, 'generated_at': '2026-09-23 10:00:00', 'default_pricelist_id': 1,
            'count': 1, 'items': [{'external_id': '17', 'name': 'Test sandwich', 'sku': 'S17', 'categories': ['Sandwiches'],
                'prices': [{'pricelist_id': 1, 'currency': 'SAR', 'total_included_minor': 1000},
                           {'pricelist_id': 2, 'currency': 'SAR', 'total_included_minor': 1200}]}]}

    def items(self):
        return self.env['octa.hub.catalog.item'].with_context(active_test=False).search([('storefront_id', '=', self.endpoint.storefront_id.id)])

    def test_repeat_updates_without_duplicate(self):
        self.endpoint._import_catalog(self.payload)
        original = self.items()
        self.endpoint._import_catalog(self.payload)
        self.assertEqual(self.items(), original)
        self.assertEqual(original.base_price_minor_units, 1000)
        self.assertEqual(original.price_override_ids.amount_minor_units, 1200)
        self.assertEqual(original.price_override_ids.channel_code, 'hungerstation')

    def test_invalid_second_row_rolls_back_whole_import(self):
        payload = deepcopy(self.payload)
        bad = deepcopy(payload['items'][0])
        bad.update(external_id='18', prices=[])
        payload['items'].append(bad)
        payload['count'] = 2
        with self.assertRaisesRegex(ValidationError, 'unique SAR default'):
            self.endpoint._import_catalog(payload)
        self.assertFalse(self.items())
        self.assertFalse(self.endpoint.source_id)

    def test_source_cannot_be_switched(self):
        self.endpoint._import_catalog(self.payload)
        self.payload['source_id'] = 'b' * 32
        with self.assertRaisesRegex(ValidationError, 'different POS source'):
            self.endpoint._import_catalog(self.payload)

    def test_stale_snapshot_rejected(self):
        self.endpoint._import_catalog(self.payload)
        self.payload['generated_at'] = '2026-09-22 10:00:00'
        with self.assertRaisesRegex(ValidationError, 'stale snapshot'):
            self.endpoint._import_catalog(self.payload)

    def test_removed_item_archived_not_deleted(self):
        self.endpoint._import_catalog(self.payload)
        self.payload.update(items=[], count=0)
        self.endpoint._import_catalog(self.payload)
        self.assertEqual(len(self.items()), 1)
        self.assertFalse(self.items().active)

    def test_duplicate_product_ids_rejected(self):
        self.payload['items'] *= 2
        self.payload['count'] = 2
        with self.assertRaisesRegex(ValidationError, 'repeated product IDs'):
            self.endpoint._import_catalog(self.payload)

    def test_production_and_non_https_hosts_rejected_before_network(self):
        for url in ['https://example.com', 'http://safe.dev.odoo.com', 'https://safe.dev.odoo.com@evil.com', 'https://safe.dev.odoo.com/api']:
            self.endpoint.url = url
            with self.assertRaisesRegex(ValidationError, 'sandbox host'):
                self.endpoint._request('GET', '/octa/pos/v1/catalog')

    def test_non_admin_cannot_use_import(self):
        public = self.env.ref('base.public_user')
        with self.assertRaises(AccessError):
            self.endpoint.with_user(public)._import_catalog(self.payload)
