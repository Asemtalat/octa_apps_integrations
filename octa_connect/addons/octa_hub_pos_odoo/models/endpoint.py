"""Administrator-only sandbox adapter. Never connects to production hosts."""
import base64
import json
import re
from urllib.parse import urlsplit
import requests
from odoo import api, fields, models, Command, _
from odoo.exceptions import AccessError, ValidationError


class Endpoint(models.Model):
    _name = 'octa.hub.pos.endpoint'
    _description = 'Sandbox Odoo POS endpoint'
    name = fields.Char(required=True)
    storefront_id = fields.Many2one('octa.hub.storefront', required=True, ondelete='restrict')
    url = fields.Char(help='HTTPS Odoo.sh development/staging host only')
    api_key = fields.Char(copy=False, groups='base.group_system')
    enabled = fields.Boolean(default=False)
    source_id = fields.Char(readonly=True, copy=False)
    config_id_external = fields.Integer(readonly=True)
    imported_at = fields.Datetime(readonly=True)
    source_generated_at = fields.Datetime(readonly=True)
    snapshot_file = fields.Binary(attachment=False, copy=False)
    snapshot_json = fields.Text(readonly=True, groups='base.group_system')
    item_count = fields.Integer(readonly=True)
    mapping_ids = fields.One2many('octa.hub.pos.price.mapping', 'endpoint_id')
    _unique_storefront = models.Constraint('unique(storefront_id)', 'One POS source per storefront in this pilot.')

    def write(self, vals):
        if 'storefront_id' in vals and any(r.source_id and r.storefront_id.id != vals['storefront_id'] for r in self):
            raise ValidationError(_('An imported POS connection cannot be moved to another storefront.'))
        return super().write(vals)

    def _admin(self):
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(_('System administrator required for sandbox integration.'))
        self.ensure_one()

    def _request(self, method, path, **kwargs):
        self._admin()
        parts = urlsplit(self.url or '')
        if (parts.scheme != 'https' or not re.fullmatch(r'[a-z0-9-]+\.dev\.odoo\.com', parts.hostname or '')
                or parts.username or parts.password or parts.port not in (None, 443)
                or parts.path not in ('', '/') or parts.query or parts.fragment):
            raise ValidationError(_('Only HTTPS Odoo.sh sandbox host URLs are allowed.'))
        if not self.enabled or not self.api_key:
            raise ValidationError(_('Sandbox connection is disabled or missing its key.'))
        return requests.request(method, self.url.rstrip('/') + path,
            headers={'Authorization': 'Bearer ' + self.api_key}, timeout=(5, 25),
            allow_redirects=False, **kwargs)

    def action_pull_catalog(self):
        self._admin()
        try:
            response = self._request('GET', '/octa/pos/v1/catalog')
            if response.status_code != 200:
                raise ValidationError(_('Catalog request failed (HTTP %s).') % response.status_code)
            if len(response.content) > 20 * 1024 * 1024:
                raise ValidationError(_('Catalog exceeds the pilot snapshot limit.'))
            payload = response.json()
        except (requests.RequestException, ValueError):
            raise ValidationError(_('Catalog could not be retrieved or decoded. Existing menu unchanged.'))
        self._import_catalog(payload)

    def action_import_snapshot(self):
        self._admin()
        try:
            raw = base64.b64decode(self.snapshot_file or b'', validate=True)
            if len(raw) > 20 * 1024 * 1024:
                raise ValueError('too large')
            payload = json.loads(raw)
        except (ValueError, TypeError):
            raise ValidationError(_('Invalid catalog snapshot.'))
        self._import_catalog(payload)
        self.snapshot_file = False

    def _import_catalog(self, payload):
        self._admin()
        # A caller catching validation errors must not retain a partial import.
        with self.env.cr.savepoint():
            return self._apply_catalog(payload)

    def _apply_catalog(self, payload):
        if not isinstance(payload, dict) or payload.get('contract') != 'octa-pos-catalog-v1' or payload.get('currency') != 'SAR':
            raise ValidationError(_('Invalid catalog contract or currency.'))
        source = payload.get('source_id')
        if not isinstance(source, str) or not re.fullmatch(r'[a-f0-9]{32}', source):
            raise ValidationError(_('Missing stable source identity.'))
        if self.source_id and (self.source_id != source or self.config_id_external != payload.get('config_id')):
            raise ValidationError(_('This connection is bound to a different POS source.'))
        items = payload.get('items')
        if not isinstance(items, list) or payload.get('count') != len(items):
            raise ValidationError(_('Incomplete snapshot.'))
        if type(payload.get('config_id')) is not int or payload['config_id'] <= 0:
            raise ValidationError(_('Missing POS configuration identity.'))
        try:
            generated = fields.Datetime.to_datetime(payload.get('generated_at'))
        except (ValueError, TypeError):
            raise ValidationError(_('Invalid snapshot timestamp.'))
        if not generated or (self.source_generated_at and generated < self.source_generated_at):
            raise ValidationError(_('Missing or stale snapshot timestamp.'))
        ids = [i.get('external_id') for i in items if isinstance(i, dict)]
        if len(ids) != len(items) or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
            raise ValidationError(_('Missing or repeated product IDs.'))
        # All operations share one transaction. A bad row rolls back the complete import.
        Item = self.env['octa.hub.catalog.item'].sudo().with_context(active_test=False)
        currency = self.env.ref('base.SAR')
        imported = Item.browse()
        for raw in items:
            prices = raw.get('prices', [])
            if (not isinstance(prices, list) or any(not isinstance(p, dict) for p in prices)
                    or any(type(p.get('total_included_minor')) is not int or p['total_included_minor'] < 0 for p in prices)):
                raise ValidationError(_('Invalid price rows.'))
            defaults = [p for p in prices if p.get('pricelist_id') == payload.get('default_pricelist_id')]
            if len(defaults) != 1 or defaults[0].get('currency') != 'SAR':
                raise ValidationError(_('A unique SAR default price is required for every item.'))
            price = defaults[0].get('total_included_minor')
            if type(price) is not int or price < 0:
                raise ValidationError(_('Invalid default price.'))
            external = source + ':' + raw['external_id']
            item = Item.search([('storefront_id', '=', self.storefront_id.id), ('external_id', '=', external)], limit=1)
            values = {'name_ar': raw.get('name') or raw['external_id'], 'description_ar': raw.get('description', ''),
                      'sku': raw.get('sku', ''), 'category': ', '.join(raw.get('categories', [])),
                      'base_price_minor_units': price, 'currency_id': currency.id, 'active': True,
                      'pos_snapshot_json': json.dumps(raw, ensure_ascii=False),
                      'pos_image': raw.get('image_base64') or False,
                      'external_version': (item.external_version + 1) if item else 1}
            if item:
                item.write(values)
            else:
                item = Item.create(dict(values, storefront_id=self.storefront_id.id, external_id=external))
            imported |= item
            groups = self.env['octa.hub.modifier.group'].sudo()
            for group in raw.get('modifier_groups', []):
                group_key = source + ':' + str(group['external_id'])
                Group = self.env['octa.hub.modifier.group'].sudo()
                saved = Group.search([('organization_id', '=', self.storefront_id.organization_id.id), ('external_id', '=', group_key)], limit=1)
                vals = {'name': group.get('name_ar') or group['name'], 'min_select': group['min_select'],
                        'max_select': group['max_select'], 'mandatory': group['min_select'] > 0,
                        'allow_repeat': bool(group.get('allow_repeat'))}
                if saved:
                    saved.write(vals)
                else:
                    saved = Group.create(dict(vals, organization_id=self.storefront_id.organization_id.id, external_id=group_key))
                for option in group.get('options', []):
                    Modifier = self.env['octa.hub.modifier'].sudo().with_context(active_test=False)
                    opt = Modifier.search([('group_id', '=', saved.id), ('external_id', '=', str(option['external_id']))], limit=1)
                    vals = {'name_ar': option.get('name_ar') or option['name'], 'price_minor_units': option['price_minor'], 'active': True}
                    if opt:
                        opt.write(vals)
                    else:
                        Modifier.create(dict(vals, group_id=saved.id, external_id=str(option['external_id'])))
                groups |= saved
            item.modifier_group_ids = [Command.set(groups.ids)]
            for mapping in self.mapping_ids:
                matches = [p for p in prices if p.get('pricelist_id') == mapping.pricelist_id_external]
                if len(matches) != 1 or matches[0].get('currency') != 'SAR':
                    raise ValidationError(_('Mapped pricelist missing or wrong currency.'))
                Override = self.env['octa.hub.price.override'].sudo()
                override = Override.search([('item_id', '=', item.id), ('channel_code', '=', mapping.channel_code)], limit=1)
                amount = matches[0]['total_included_minor']
                values = {'amount_minor_units': amount, 'currency_id': currency.id, 'allow_zero': amount == 0,
                          'version': item.external_version}
                if override:
                    override.write(values)
                else:
                    Override.create(dict(values, item_id=item.id, channel_code=mapping.channel_code))
        # A complete snapshot removes availability, never deletes historical items.
        Item.search([('storefront_id', '=', self.storefront_id.id),
                     ('external_id', '=like', source + ':%'), ('id', 'not in', imported.ids)]).write({'active': False})
        self.write({'source_id': source, 'config_id_external': payload['config_id'], 'item_count': len(items),
                    'snapshot_json': json.dumps(payload, ensure_ascii=False), 'imported_at': fields.Datetime.now(),
                    'source_generated_at': generated})


class Mapping(models.Model):
    _name = 'octa.hub.pos.price.mapping'
    _description = 'Explicit POS pricelist to channel mapping'
    endpoint_id = fields.Many2one('octa.hub.pos.endpoint', required=True, ondelete='cascade')
    pricelist_id_external = fields.Integer(required=True)
    channel_code = fields.Char(required=True)
    _unique_channel = models.Constraint('unique(endpoint_id, channel_code)', 'One mapping per channel.')


class Catalog(models.Model):
    _inherit = 'octa.hub.catalog.item'
    pos_image = fields.Image(max_width=256, max_height=256)
    pos_snapshot_json = fields.Text(groups='base.group_system')
