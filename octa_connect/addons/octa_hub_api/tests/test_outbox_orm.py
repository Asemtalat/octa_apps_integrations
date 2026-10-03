from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase


class TestOutboxUncertainDelivery(TransactionCase):
    def setUp(self):
        super().setUp()
        self.queue = self.env['octa.hub.outbox.item']
        self.item = self.queue.create({'item_key': 'uncertain-delivery-test', 'payload_json': '{}'})

    def test_dispatch_exception_does_not_resend(self):
        def dispatch(payload):
            raise ConnectionError('remote accepted but acknowledgement lost')
        self.queue.run_worker_batch(dispatch)
        self.assertEqual(self.item.status, 'awaiting_confirmation')
        self.assertNotIn(self.item, self.queue.claim_batch('second-worker'))

    def test_malformed_result_does_not_resend(self):
        self.queue.run_worker_batch(lambda payload: None)
        self.assertEqual(self.item.status, 'awaiting_confirmation')

    def test_stale_processing_requires_confirmation(self):
        self.item.write({'status': 'processing', 'claimed_at': fields.Datetime.now() - timedelta(minutes=10)})
        self.assertNotIn(self.item, self.queue.claim_batch('recovery-worker'))
        self.assertEqual(self.item.status, 'awaiting_confirmation')

    def test_success_requires_explicit_confirmation(self):
        self.queue.run_worker_batch(lambda payload: {'outcome': 'confirmed_success'})
        self.assertEqual(self.item.status, 'done')

    def test_invalid_query_result_stays_unconfirmed(self):
        self.item.write({'status': 'awaiting_confirmation', 'next_query_at': fields.Datetime.now()})
        self.queue.run_query_batch(lambda item: None)
        self.assertEqual(self.item.status, 'awaiting_confirmation')
        self.assertEqual(self.item.query_attempt_count, 1)
