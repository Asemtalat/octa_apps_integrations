"""Read-only merchant portal. Business reads always use the authenticated ORM.

The only sudo query resolves the current user's own membership. A requested
organization is matched against that query, never accepted as an authority.
No API credentials, payload snapshots or webhook URLs enter template values.
"""
from urllib.parse import urlencode

from werkzeug.exceptions import Forbidden, NotFound

from odoo import http
from odoo.http import request


def merchant_scope(env, organization=None):
    memberships = env['octa.hub.membership'].sudo().search([
        ('user_id', '=', env.uid), ('active', '=', True),
        ('party_type', '=', 'merchant'), ('organization_id.active', '=', True),
        ('organization_id.state', '!=', 'suspended'),
    ], order='id')
    if not memberships:
        raise Forbidden()
    if organization:
        try:
            organization = int(organization)
        except (TypeError, ValueError):
            raise NotFound() from None
        selected = memberships.filtered(lambda m: m.organization_id.id == organization)
        if not selected:
            raise NotFound()
        membership = selected[0]
    else:
        membership = memberships[0]
    domain = [('organization_id', '=', membership.organization_id.id)]
    # Apply explicit restrictions for every role, including owners with a
    # deliberately limited membership. A branch manager with no branches sees none.
    restricted = bool(membership.branch_ids) or membership.role_code == 'merchant_branch_manager'
    branch_ids = membership.branch_ids.filtered(
        lambda b: b.organization_id == membership.organization_id and b.active
    ).ids
    return membership, memberships, domain, branch_ids if restricted else None


class MerchantPortal(http.Controller):
    @http.route('/octa/start', type='http', auth='public', methods=['GET'])
    def entry(self, **kw):
        return request.render('octa_hub_ui.merchant_entry', {})

    @http.route(['/octa/portal', '/octa/portal/<string:section>'],
                type='http', auth='user', methods=['GET'])
    def portal(self, section='overview', organization=None, page='1', q='', **kw):
        if section not in {'overview', 'orders', 'connections', 'account'}:
            raise NotFound()
        env = request.env
        membership, memberships, domain, branch_ids = merchant_scope(env, organization)
        org_id = membership.organization_id.id
        scope_domain = domain + ([('branch_id', 'in', branch_ids)] if branch_ids is not None else [])
        Order = env['octa.hub.order']
        Connection = env['octa.hub.connection']
        Branch = env['octa.hub.branch']
        can_orders = Order.has_access('read')
        can_connections = Connection.has_access('read')
        can_branches = Branch.has_access('read')
        try:
            page = min(max(int(page), 1), 10000)
        except (ValueError, TypeError):
            page = 1
        q = (q or '').strip()[:160]
        def link(target, **params):
            return '/octa/portal/' + target + '?' + urlencode({'organization': org_id, **params})
        values = {
            'section': section, 'org_name': membership.organization_id.name,
            'org_id': org_id, 'role_name': dict(membership._fields['role_code'].selection)[membership.role_code],
            'organizations': [{'id': m.organization_id.id, 'name': m.organization_id.name} for m in memberships],
            'user_name': env.user.name, 'user_email': env.user.email or env.user.login,
            'org_state': dict(membership.organization_id._fields['state'].selection)[membership.organization_id.state],
            'link': link, 'q': q, 'page': page, 'can_orders': can_orders,
            'can_connections': can_connections, 'can_branches': can_branches,
            'orders': [], 'connections': [], 'branches': [], 'has_next': False,
        }
        if can_orders:
            values['order_count'] = Order.search_count(scope_domain)
            values['confirmed_count'] = Order.search_count(scope_domain + [('transport_state', '=', 'registered_confirmed')])
            values['attention_count'] = Order.search_count(scope_domain + [('transport_state', 'in', ['unknown', 'needs_intervention'])])
        if can_branches:
            branch_domain = domain + ([('id', 'in', branch_ids)] if branch_ids is not None else [])
            values['branch_count'] = Branch.search_count(branch_domain)
            if section == 'account':
                values['branches'] = Branch.search_read(branch_domain,
                    ['name', 'timezone', 'external_pos_system'], limit=100, order='name, id')
        if can_connections:
            values['connection_count'] = Connection.search_count(scope_domain)
        if section == 'orders' and can_orders:
            order_domain = scope_domain + ([('external_order_id', '=', q)] if q else [])
            records = Order.search_read(order_domain,
                ['external_order_id', 'branch_id', 'transport_state', 'commercial_state', 'create_date'],
                offset=(page - 1) * 30, limit=31, order='id desc')
            values['orders'], values['has_next'] = records[:30], len(records) > 30
            values['transport_labels'] = dict(Order._fields['transport_state'].selection)
            values['commercial_labels'] = dict(Order._fields['commercial_state'].selection)
        if section == 'connections' and can_connections:
            records = Connection.search_read(scope_domain,
                ['connector_code', 'technically_connected', 'production_approved', 'branch_ready'],
                offset=(page - 1) * 30, limit=31, order='id desc')
            values['connections'], values['has_next'] = records[:30], len(records) > 30
        response = request.render('octa_hub_ui.merchant_portal', values)
        response.headers['Cache-Control'] = 'private, no-store'
        response.headers['X-Frame-Options'] = 'DENY'
        return response
