from copy import deepcopy
from unittest.mock import patch, Mock
import requests
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
                'prices': [{'pricelist_id': 1, 'currency': 'SAR', 'price_unit_minor': 1000, 'total_included_minor': 1000},
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

    def delivery(self):
        self.endpoint._import_catalog(self.payload)
        self.endpoint.test_item_id = self.items()
        result = self.endpoint.action_prepare_test_order()
        return self.env['octa.hub.pos.delivery'].browse(result['res_id'])

    def test_prepare_has_no_network_and_retry_queries_first(self):
        with patch.object(type(self.endpoint), '_request') as request:
            delivery = self.delivery()
            request.assert_not_called()
            receipt = {'registered': True, 'external_order_id': delivery.external_id, 'pos_order_id': 19}
            request.side_effect = [Mock(status_code=404), Mock(status_code=200, json=lambda: receipt)]
            delivery.action_send()
            self.assertEqual([c.args[0] for c in request.call_args_list], ['GET', 'POST'])
            self.assertEqual(delivery.state, 'confirmed')
            self.assertEqual(delivery.order_id.transport_state, 'registered_confirmed')
            self.assertEqual(delivery.order_id.commercial_state, 'new')
            delivery.action_send()
            self.assertEqual(request.call_count, 2)

    def test_timeout_then_lookup_confirms_without_resending(self):
        delivery = self.delivery()
        with patch.object(type(self.endpoint), '_request') as request:
            request.side_effect = [Mock(status_code=404), requests.Timeout()]
            delivery.action_send()
            self.assertEqual(delivery.state, 'unknown')
            self.assertEqual(delivery.order_id.transport_state, 'unknown')
            request.reset_mock()
            receipt = {'registered': True, 'external_order_id': delivery.external_id, 'pos_order_id': 20}
            request.side_effect = [Mock(status_code=200, json=lambda: receipt)]
            delivery.action_send()
            self.assertEqual(request.call_count, 1)
            self.assertEqual(request.call_args.args[0], 'GET')
            self.assertEqual(delivery.state, 'confirmed')

    def test_mismatched_receipt_never_counts_as_success(self):
        delivery = self.delivery()
        response = Mock(status_code=200, json=lambda: {'registered': True, 'external_order_id': 'wrong', 'pos_order_id': 20})
        with patch.object(type(self.endpoint), '_request', return_value=response):
            delivery.action_send()
        self.assertEqual(delivery.state, 'unknown')
        self.assertNotEqual(delivery.order_id.transport_state, 'registered_confirmed')

    def test_persisted_delivery_identity_cannot_be_changed(self):
        delivery = self.delivery()
        with self.assertRaisesRegex(ValidationError, 'immutable'):
            delivery.write({'payload_json': '{}'})
