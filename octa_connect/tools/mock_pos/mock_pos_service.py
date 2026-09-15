"""
tools/mock_pos — خدمة اختبار مستقلة تمامًا عن موديلات Odoo (كما يشترط
القسم 5 من ملف Octa_Connect_Claude_Phase_1.md: "خدمة اختبار منفصلة عن
موديلات أودو، تحاكي التسجيل والاستعلام والتكرار وضياع الرد").

تستخدم http.server القياسي فقط (بدون Flask) حتى لا نضيف تبعية غير لازمة
لخدمة اختبار بسيطة. تدعم:
  POST /orders            تسجيل طلب (يدعم Idempotency-Key)
  GET  /orders/{ext_id}   استعلام لتأكيد التسجيل بعد ضياع رد
  POST /_test/drop_next_response   يجعل الطلب التالي "يسجل وتنقطع الاستجابة"
       (لمحاكاة سيناريو: POS يسجل ثم يقطع الرد، بدون فعليًا قطع اتصال TCP)

هذا محاكٍ مُعلن (mock) لا يمثل أي نظام POS حقيقي ولا يثبت اعتماد أي تكامل.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

_lock = threading.Lock()
_orders: dict[str, dict] = {}          # external_order_id -> order record
_idempotency_keys: dict[str, str] = {}  # idempotency_key -> external_order_id
_drop_next_response = {"flag": False}


def reset_state():
    with _lock:
        _orders.clear()
        _idempotency_keys.clear()
        _drop_next_response["flag"] = False


class MockPosHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # سجل هادئ أثناء الاختبارات

    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid_json"})
            return

        if parsed.path == "/_test/drop_next_response":
            with _lock:
                _drop_next_response["flag"] = True
            self._send_json(200, {"ok": True})
            return

        if parsed.path == "/orders":
            self._handle_create_order(data)
            return

        self._send_json(404, {"error": "not_found"})

    def _handle_create_order(self, data):
        ext_id = data.get("external_order_id")
        idem_key = self.headers.get("Idempotency-Key")
        if not ext_id:
            self._send_json(422, {"error": "external_order_id_required"})
            return

        with _lock:
            # منع التكرار عبر Idempotency-Key أولاً (لو أُرسل)
            if idem_key and idem_key in _idempotency_keys:
                existing_ext_id = _idempotency_keys[idem_key]
                if existing_ext_id == ext_id:
                    order = _orders[existing_ext_id]
                    self._send_json(200, {"status": "already_registered", "order": order})
                    return
                self._send_json(409, {"error": "idempotency_key_conflict",
                                       "detail": "same key used for a different external_order_id"})
                return

            if ext_id in _orders:
                # نفس external_order_id بدون idempotency key: نرفض التكرار الصامت
                self._send_json(409, {"error": "duplicate_external_order_id"})
                return

            order = {
                "external_order_id": ext_id,
                "items": data.get("items", []),
                "total_minor_units": data.get("total_minor_units"),
                "currency": data.get("currency", "SAR"),
                "registered": True,
            }
            _orders[ext_id] = order
            if idem_key:
                _idempotency_keys[idem_key] = ext_id

            should_drop = _drop_next_response["flag"]
            _drop_next_response["flag"] = False

        if should_drop:
            # الطلب اتسجل فعلاً (موجود في _orders) لكن لا نرسل ردًا —
            # نقطع الاتصال بدون استجابة لمحاكاة "POS سجل ثم قطع الرد".
            self.close_connection = True
            return

        self._send_json(201, {"status": "registered", "order": order})

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/orders/"):
            ext_id = parsed.path.split("/orders/", 1)[1]
            with _lock:
                order = _orders.get(ext_id)
            if order is None:
                self._send_json(404, {"error": "not_found"})
            else:
                self._send_json(200, {"status": "found", "order": order})
            return
        self._send_json(404, {"error": "not_found"})


def make_server(host="127.0.0.1", port=0) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), MockPosHandler)


if __name__ == "__main__":
    srv = make_server(port=8765)
    print(f"mock_pos listening on http://127.0.0.1:{srv.server_address[1]}")
    srv.serve_forever()
