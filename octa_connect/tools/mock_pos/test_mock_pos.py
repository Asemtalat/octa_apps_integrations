"""
اختبارات RUN فعليًا: تشغّل خادم HTTP حقيقي (mock_pos) على منفذ محلي عشوائي
وترسل له طلبات HTTP فعلية عبر urllib (ليست استدعاء دوال Python مباشرة) —
هذا فعلًا "end-to-end" بين عميل ومحاكي POS مستقل، كما يطلب القسم 19.
"""
import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from mock_pos_service import make_server, reset_state


@pytest.fixture()
def server():
    reset_state()
    srv = make_server()
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    port = srv.server_address[1]
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()


def _post(base, path, body, headers=None, timeout=2):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(base + path, data=data, method="POST",
                                  headers={"Content-Type": "application/json", **(headers or {})})
    return urllib.request.urlopen(req, timeout=timeout)


def _get(base, path, timeout=2):
    return urllib.request.urlopen(base + path, timeout=timeout)


def test_register_order_succeeds(server):
    resp = _post(server, "/orders", {"external_order_id": "EXT-1", "total_minor_units": 3000})
    assert resp.status == 201
    body = json.loads(resp.read())
    assert body["status"] == "registered"


def test_duplicate_external_id_without_idempotency_key_is_rejected(server):
    _post(server, "/orders", {"external_order_id": "EXT-2", "total_minor_units": 1000})
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(server, "/orders", {"external_order_id": "EXT-2", "total_minor_units": 1000})
    assert exc.value.code == 409


def test_same_idempotency_key_same_order_is_idempotent_replay(server):
    headers = {"Idempotency-Key": "idem-abc"}
    r1 = _post(server, "/orders", {"external_order_id": "EXT-3", "total_minor_units": 500}, headers)
    assert r1.status == 201
    r2 = _post(server, "/orders", {"external_order_id": "EXT-3", "total_minor_units": 500}, headers)
    assert r2.status == 200
    assert json.loads(r2.read())["status"] == "already_registered"


def test_same_idempotency_key_different_order_is_conflict(server):
    headers = {"Idempotency-Key": "idem-xyz"}
    _post(server, "/orders", {"external_order_id": "EXT-4", "total_minor_units": 500}, headers)
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(server, "/orders", {"external_order_id": "EXT-5", "total_minor_units": 999}, headers)
    assert exc.value.code == 409
    assert json.loads(exc.value.read())["error"] == "idempotency_key_conflict"


def test_pos_registers_then_drops_response_client_must_query_not_blind_retry(server):
    """يحاكي بالضبط سيناريو الوثيقة: POS يسجل الطلب فعليًا ثم تُقطع الاستجابة.
    العميل الصحيح لا يعيد الإرسال بمعرف جديد؛ يستعلم بالمعرف نفسه فيجد
    الطلب مسجلاً فعلاً رغم ضياع الرد الأول.
    """
    _post(server, "/_test/drop_next_response", {})
    try:
        _post(server, "/orders", {"external_order_id": "EXT-6", "total_minor_units": 777}, timeout=1)
        raised = False
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        raised = True
    assert raised, "الرد المتوقَّع أن ينقطع فعليًا في هذا الاختبار"

    # العميل الصحيح: يستعلم بدل إعادة الإرسال بمعرف جديد
    resp = _get(server, "/orders/EXT-6")
    assert resp.status == 200
    body = json.loads(resp.read())
    assert body["order"]["external_order_id"] == "EXT-6"  # سُجّل فعلاً رغم ضياع الرد


def test_query_unknown_order_returns_404_not_silent_success(server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(server, "/orders/DOES-NOT-EXIST")
    assert exc.value.code == 404


def test_20_real_concurrent_http_clients_same_idempotency_key_no_duplicate(server):
    """اختبار جديد (مراجعة سابعة): كل الاختبارات السابقة كانت متسلسلة (طلب
    HTTP واحد في كل مرة). هذا يرسل 20 طلب HTTP حقيقيًا متزامنًا فعليًا عبر
    threads منفصلة على نفس idempotency-key — تزامن على مستوى الشبكة نفسها،
    لا استدعاء دوال داخل نفس العملية فقط. يتحقق أن القفل يصمد تحت تزامن
    اتصالات حقيقية عبر ThreadingHTTPServer، لا محاكاة تزامن فقط."""
    import concurrent.futures
    from collections import Counter

    def send(_):
        try:
            resp = _post(server, "/orders", {"external_order_id": "EXT-STRESS", "total_minor_units": 100},
                         headers={"Idempotency-Key": "stress-key"})
            return resp.status
        except urllib.error.HTTPError as e:
            return e.code

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
        results = list(ex.map(send, range(20)))

    counts = Counter(results)
    assert counts[201] == 1   # تسجيل فعلي واحد فقط
    assert counts[200] == 19  # الباقي "already_registered"
