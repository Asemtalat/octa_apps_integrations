"""Manual sandbox delivery. Persist intent before network; reconcile before retry."""
import json
import uuid
from urllib.parse import urlencode
import requests
from odoo import fields, models, _
from odoo.exceptions import ValidationError


class Delivery(models.Model):
    _name = 'octa.hub.pos.delivery'
    _description = 'Sandbox POS delivery evidence'
    _order = 'id desc'
    endpoint_id = fields.Many2one('octa.hub.pos.endpoint', required=True, ondelete='restrict')
    order_id = fields.Many2one('octa.hub.order', required=True, ondelete='restrict')
    external_id = fields.Char(required=True, readonly=True)
    payload_json = fields.Text(required=True, readonly=True)
    state = fields.Selection([('prepared', 'Prepared'), ('unknown', 'Awaiting confirmation'),
        ('confirmed', 'Registered at POS'), ('rejected', 'Rejected')], default='prepared', readonly=True)
    last_http_status = fields.Integer(readonly=True)
    last_checked_at = fields.Datetime(readonly=True)
    receipt_json = fields.Text(readonly=True)
    _unique_order = models.Constraint('unique(order_id)', 'One delivery intent per order.')
    _unique_external = models.Constraint('unique(endpoint_id, external_id)', 'Duplicate delivery identity.')

    def write(self, vals):
        if {'endpoint_id', 'order_id', 'external_id', 'payload_json'} & vals.keys():
            raise ValidationError(_('Delivery identity and payload are immutable.'))
        return super().write(vals)

    def action_send(self):
        self.ensure_one()
        self.endpoint_id._admin()
        self.env.cr.execute('SELECT id FROM octa_hub_pos_delivery WHERE id=%s FOR UPDATE', [self.id])
        if self.state == 'confirmed':
            return
        if self.order_id.transport_state != 'dispatching':
            self.order_id.write({'transport_state': 'dispatching'})
        try:
            # This runs even after a process crash that rolled back local state.
            # The delivery identity was saved by a separate, earlier UI request.
            response = self.endpoint_id._request('GET', '/octa/pos/v1/status?' + urlencode({'external_order_id': self.external_id}))
            if response.status_code == 404:
                response = self.endpoint_id._request('POST', '/octa/pos/v1/orders', json=json.loads(self.payload_json))
            self._record_response(response)
        except (requests.RequestException, ValueError):
            self.write({'state': 'unknown', 'last_checked_at': fields.Datetime.now()})
            self.order_id.write({'transport_state': 'unknown'})

    def action_refresh(self):
        self.ensure_one()
        self.endpoint_id._admin()
        try:
            response = self.endpoint_id._request('GET', '/octa/pos/v1/status?' + urlencode({'external_order_id': self.external_id}))
            self._record_response(response)
        except (requests.RequestException, ValueError):
            self.last_checked_at = fields.Datetime.now()

    def _record_response(self, response):
        vals = {'last_http_status': response.status_code, 'last_checked_at': fields.Datetime.now()}
        if response.status_code == 200:
            body = response.json()
            if (body.get('registered') is not True or body.get('external_order_id') != self.external_id
                    or type(body.get('pos_order_id')) is not int or body['pos_order_id'] <= 0):
                raise ValueError('Unconfirmed or mismatched receipt')
            vals.update(state='confirmed', receipt_json=json.dumps(body, ensure_ascii=False))
            if self.order_id.transport_state == 'stored':
                self.order_id.write({'transport_state': 'dispatching'})
            self.order_id.write({'transport_state': 'registered_confirmed'})
        elif self.state != 'confirmed':
            vals['state'] = 'rejected' if response.status_code in (401, 403, 422) else 'unknown'
            if self.order_id.transport_state == 'stored':
                self.order_id.write({'transport_state': 'dispatching'})
            self.order_id.write({'transport_state': 'needs_intervention' if vals['state'] == 'rejected' else 'unknown'})
        self.write(vals)


class Endpoint(models.Model):
    _inherit = 'octa.hub.pos.endpoint'
    test_item_id = fields.Many2one('octa.hub.catalog.item', string='Pilot test item')

    def action_prepare_test_order(self):
        self._admin()
        item = self.test_item_id
        if not item or not item.active or item.storefront_id != self.storefront_id or not self.source_id:
            raise ValidationError(_('Select an imported active item from this storefront.'))
        raw = json.loads(item.pos_snapshot_json or '{}')
        if item.modifier_group_ids or not item.external_id.startswith(self.source_id + ':'):
            raise ValidationError(_('The pilot order requires an imported item without modifiers.'))
        catalog = json.loads(self.snapshot_json)
        prices = [p for p in raw.get('prices', []) if p['pricelist_id'] == catalog['default_pricelist_id']]
        if len(prices) != 1:
            raise ValidationError(_('Default POS price is missing.'))
        key = 'octa-test-' + uuid.uuid4().hex
        payload = {'contract': 'octa-pos-order-v1', 'external_order_id': key, 'currency': 'SAR',
            'items': [{'external_id': raw['external_id'], 'quantity': 1, 'price_unit_minor': prices[0]['price_unit_minor']}],
            'total_included_minor': prices[0]['total_included_minor']}
        Connection = self.env['octa.hub.connection'].sudo()
        connection = Connection.search([('storefront_id', '=', self.storefront_id.id), ('connector_code', '=', 'pos_sandbox_test')], limit=1)
        if not connection:
            connection = Connection.create({'storefront_id': self.storefront_id.id, 'connector_code': 'pos_sandbox_test'})
        order = self.env['octa.hub.order'].sudo().create({'organization_id': self.storefront_id.organization_id.id,
            'branch_id': self.storefront_id.branch_id.id, 'connection_id': connection.id,
            'external_order_id': key, 'contract_version': 'octa-pos-order-v1',
            'items_snapshot_json': json.dumps(payload['items']), 'total_minor_units': payload['total_included_minor'],
            'currency_id': self.env.ref('base.SAR').id})
        delivery = self.env['octa.hub.pos.delivery'].create({'endpoint_id': self.id, 'order_id': order.id,
            'external_id': key, 'payload_json': json.dumps(payload, sort_keys=True)})
        # No network here: commit this intent before the explicit Send action.
        return {'type': 'ir.actions.act_window', 'res_model': delivery._name, 'res_id': delivery.id, 'view_mode': 'form', 'target': 'current'}
