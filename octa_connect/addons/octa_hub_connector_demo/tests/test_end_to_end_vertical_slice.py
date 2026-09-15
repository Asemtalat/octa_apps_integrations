"""
اختبار تكامل end-to-end RUN فعليًا يربط الثلاثة أطراف المطلوبة في القسم 4/19:
محاكي تطبيق التوصيل (ConnectorDemoSimulator) → نواة idempotency/orders
(octa_hub_api/lib/idempotency.py) → خدمة POS تجريبية مستقلة (tools/mock_pos)
عبر HTTP حقيقي، وليس استدعاء دوال داخلي فقط.

هذا لا يثبت اعتماد أي تطبيق حقيقي — محاكيات معلنة فقط (القسم 17/19).
"""
import concurrent.futures
import json
import os
import sys
import threading
import urllib.request

import pytest

_HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(_HERE, "..", ".."))                       # addons/
sys.path.insert(0, os.path.join(_HERE, "..", "..", "octa_hub_api", "lib"))  # idempotency.py
sys.path.insert(0, os.path.join(_HERE, "..", "..", "..", "tools", "mock_pos"))  # mock_pos_service.py
sys.path.insert(0, os.path.join(_HERE, "..", "..", "octa_hub_core", "lib"))  # connector_capabilities.py

from octa_hub_connector_demo.simulator import (
    ConnectorDemoSimulator, SimulatedOrderEvent, RateLimitedError, TokenExpiredError,
)
from connector_capabilities import (  # noqa: E402
    MerchantConnection, Capability, enforce_capability, UnsupportedCapabilityError,
)
from idempotency import InMemoryIdempotencyStore, IdempotencyOutcome, TransportState
from mock_pos_service import make_server, reset_state


@pytest.fixture()
def pos_server():
    reset_state()
    srv = make_server()
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _dispatch_to_pos(base_url, event: SimulatedOrderEvent):
    body = json.dumps({
        "external_order_id": event.external_order_id,
        "items": event.items,
        "total_minor_units": event.total_minor_units,
        "currency": event.currency,
    }).encode()
    req = urllib.request.Request(
        base_url + "/orders", data=body, method="POST",
        headers={"Content-Type": "application/json", "Idempotency-Key": event.event_id},
    )
    with urllib.request.urlopen(req, timeout=2) as resp:
        return resp.status, json.loads(resp.read())


def _make_event(event_id="evt-1"):
    return SimulatedOrderEvent(
        event_id=event_id,
        external_order_id="EXT-100",
        tenant_id="t1", branch_id="b1", connection_id="conn_demo",
        items=[{"sku": "LIVER", "qty": 1}],
        total_minor_units=3000, currency="SAR",
        source_created_at=0.0,
    )


def test_full_slice_20_concurrent_webhook_deliveries_one_pos_registration(pos_server):
    """الحدث نفسه يصل 20 مرة متزامنة من المحاكي؛ نواة idempotency تحسم
    طلبًا منطقيًا واحدًا فقط يُرسَل لمرة واحدة فعليًا إلى POS التجريبي.
    """
    connector = ConnectorDemoSimulator()
    idem_store = InMemoryIdempotencyStore()
    event = _make_event()
    order_key = (event.tenant_id, event.branch_id, event.connection_id, event.external_order_id)

    dispatched_to_pos = []
    dispatch_lock = threading.Lock()

    def handle_incoming_webhook(_):
        received = connector.emit(event)  # يمر عبر "التطبيق" (محاكى)
        payload = {"items": received.items, "total": received.total_minor_units}
        order, outcome = idem_store.register_event(order_key, received.event_id, payload)
        if outcome == IdempotencyOutcome.NEW_LOGICAL_ORDER:
            idem_store.mark_dispatching(order_key)
            status, body = _dispatch_to_pos(pos_server, received)
            with dispatch_lock:
                dispatched_to_pos.append((status, body))
            idem_store.mark_registered_confirmed(order_key)
        return outcome

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
        outcomes = list(ex.map(handle_incoming_webhook, range(20)))

    assert outcomes.count(IdempotencyOutcome.NEW_LOGICAL_ORDER) == 1
    assert outcomes.count(IdempotencyOutcome.DUPLICATE_SAME_PAYLOAD) == 19
    assert len(dispatched_to_pos) == 1  # أثر واحد فعليًا داخل POS التجريبي، مُتحقَّق عبر HTTP حقيقي
    assert idem_store.get(order_key).transport_state == TransportState.REGISTERED_CONFIRMED


def test_rate_limit_429_surfaces_as_real_state_not_silent_swallow(pos_server):
    connector = ConnectorDemoSimulator()
    connector.force_next_failure("429", retry_after=1.5)
    event = _make_event(event_id="evt-rl")
    with pytest.raises(RateLimitedError) as exc:
        connector.emit(event)
    assert exc.value.retry_after_seconds == 1.5


def test_token_expired_surfaces_as_real_state(pos_server):
    connector = ConnectorDemoSimulator()
    connector.force_next_failure("token_expired")
    event = _make_event(event_id="evt-tok")
    with pytest.raises(TokenExpiredError):
        connector.emit(event)


def test_pause_capability_is_rejected_via_unified_contract(pos_server):
    """اختبار جديد (مراجعة عاشرة) يثبت إصلاح تعارض العقود: القدرة "pause"
    غير المدعومة في DEMO_CONNECTOR_DEFINITION (الموحَّدة الآن مع
    lib/connector_capabilities.py بدل قاموس simulator.py القديم المنفصل)
    تُرفض فعليًا عبر enforce_capability — لا تتحول إلى نجاح صامت."""
    from octa_hub_connector_demo.simulator import DEMO_CONNECTOR_DEFINITION
    connection = MerchantConnection("c1", "t1", DEMO_CONNECTOR_DEFINITION, is_sandbox=True)
    with pytest.raises(UnsupportedCapabilityError):
        enforce_capability(connection, Capability.PAUSE)
    enforce_capability(connection, Capability.ORDERS)  # المدعومة تمر بلا استثناء
