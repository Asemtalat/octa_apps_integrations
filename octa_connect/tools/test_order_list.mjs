// Controller behavior with an ORM stub; does not replace browser/OWL tests.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { test } from 'node:test';

const source = fs.readFileSync(new URL('../addons/octa_hub_ui/static/src/js/order_list.js', import.meta.url), 'utf8')
    .replace(/^import .*;$/gm, '').replace('export class ', 'class ');
function controller(orm) {
    const context = vm.createContext({ Component: class {}, useState: x => x,
        onWillStart: () => {}, useService: () => orm,
        OctaStatusBadge: class {}, OctaEmptyState: class {}, OctaErrorState: class {}, OctaLoadingState: class {},
        registry: { category: () => ({ add() {} }) } });
    const Type = vm.runInContext(source + '\nOctaHubOrderList;', context);
    const instance = new Type();
    instance.setup();
    return instance;
}

test('51st row enables next page without rendering the lookahead row', async () => {
    const calls = [];
    const c = controller({ searchRead: async (...args) => { calls.push(args); return Array.from({length: 51}, (_, id) => ({id})); } });
    await c.reload();
    assert.equal(c.state.rows.length, 50);
    assert.equal(c.state.hasNext, true);
    await c.nextPage();
    assert.equal(calls[1][3].offset, 50);
    assert.equal(calls[1][3].order, 'id desc');
});
test('exact identifier filter resets page and cannot bypass domain structure', async () => {
    let domain;
    const c = controller({ searchRead: async (model, value) => { domain = value; return []; } });
    c.state.page = 4;
    c.state.search = ' EXT-123 ';
    await c.applyFilters();
    assert.equal(c.state.page, 1);
    assert.equal(JSON.stringify(domain), JSON.stringify([['external_order_id', '=', 'EXT-123']]));
    assert.equal(c.state.hasNext, false);
});
test('failed reload clears stale rows and next-page state', async () => {
    const c = controller({ searchRead: async () => { throw Error('offline'); } });
    c.state.rows = [{id: 1}]; c.state.hasNext = true;
    await c.reload();
    assert.equal(c.state.rows.length, 0);
    assert.equal(c.state.hasNext, false);
    assert.ok(c.state.error);
});
test('late response cannot overwrite a newer request', async () => {
    const pending = [];
    const c = controller({ searchRead: () => new Promise(resolve => pending.push(resolve)) });
    const first = c.reload(), second = c.reload();
    pending[1]([{id: 2}]); await second;
    pending[0]([{id: 1}]); await first;
    assert.equal(c.state.rows[0].id, 2);
    assert.equal(c.state.loading, false);
});
