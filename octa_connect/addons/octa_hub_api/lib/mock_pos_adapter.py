"""
محوِّل حقيقي لموصل mock_pos — يكمل إصلاح النجاح الوهمي بربط فعلي حقيقي،
لا بنية جاهزة بلا محوِّل كما كانت الحالة بعد الجولة السابقة مباشرة.

**صدق حول حدود هذا المحوِّل**: mock_pos_service.py أداة اختبار (tools/mock_pos)،
لا نظام POS إنتاجي حقيقي. هذا المحوِّل يثبت أن **آلية outbox كاملة تعمل
صحيحًا من طرف إلى طرف** (استقبال → طابور → إرسال → تعامل صحيح مع انقطاع
الاتصال → استعلام → تأكيد) ضد خادم HTTP حقيقي فعليًا — وهذا دليل حقيقي
لا نظري. لكنه **ليس** اعتمادًا لتكامل موصل POS إنتاجي حقيقي (يحتاج مصادقة،
معالجة أخطاء خاصة بذلك النظام، عقد بيانات مختلف، إلخ) — ذلك يبقى
NOT_STARTED كما كان، ولا يدّعي هذا الملف خلاف ذلك.

الشكل المُرجَع من كلتا الدالتين يطابق حرفيًا العقد الذي يتوقعه
`octa_hub_api/models/outbox_item.py::run_worker_batch/run_query_batch`
(قاموس بمفتاح "outcome"، لا كائن DispatchResult من lib/outbox.py — الطبقتان
تتعمدان عقدين مختلفين شكليًا لتفادي استيراد dataclass عبر حدود Odoo/lib
بلا داعٍ حقيقي).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request


def make_mock_pos_dispatch_fn(base_url: str, timeout_seconds: float = 5.0):
    """يُرجع دالة dispatch_fn حقيقية تتصل فعليًا بخادم mock_pos عبر HTTP.

    عقد الإرجاع (يطابق outbox_item.py حرفيًا):
    {"outcome": "confirmed_success"|"confirmed_failure"|"unknown_needs_query",
     "external_reference": str|None, "detail": str}
    """
    def dispatch_fn(payload: dict) -> dict:
        external_order_id = payload.get("external_order_id")
        if not external_order_id:
            return {"outcome": "confirmed_failure", "detail": "payload missing external_order_id"}
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            base_url + "/orders", data=data, method="POST",
            headers={"Content-Type": "application/json", "Idempotency-Key": f"outbox-{external_order_id}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                if resp.status in (200, 201):
                    return {"outcome": "confirmed_success", "external_reference": external_order_id}
                return {"outcome": "confirmed_failure", "detail": f"unexpected status {resp.status}"}
        except urllib.error.HTTPError as e:
            if e.code == 409:
                # تعارض idempotency-key بمحتوى مختلف — فشل حقيقي مؤكَّد، لا مجهول
                return {"outcome": "confirmed_failure", "detail": f"409 conflict: {e.reason}"}
            return {"outcome": "confirmed_failure", "detail": f"HTTP {e.code}: {e.reason}"}
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            # القسم الأهم: انقطاع اتصال حقيقي بعد إرسال محتمل — لا نعرف هل
            # سجّل الطرف الآخر أم لا. لا نفترض فشلًا ولا نجاحًا؛ نطلب استعلامًا.
            return {"outcome": "unknown_needs_query", "external_reference": external_order_id,
                    "detail": f"connection error: {e}"}

    return dispatch_fn


def make_mock_pos_query_fn(base_url: str, timeout_seconds: float = 5.0):
    """يُرجع دالة query_fn حقيقية — **تستعلم فقط، لا ترسل مجددًا إطلاقًا**
    (منع تكرار الأثر بنيويًا: لا استدعاء POST هنا على الإطلاق)."""
    def query_fn(item) -> dict:
        ext_id = getattr(item, "external_reference", None)
        if not ext_id:
            return {"outcome": "confirmed_failure", "detail": "no external_reference to query by"}
        try:
            with urllib.request.urlopen(base_url + f"/orders/{ext_id}", timeout=timeout_seconds) as resp:
                if resp.status == 200:
                    return {"outcome": "confirmed_success"}
                return {"outcome": "unknown_needs_query", "detail": f"unexpected status {resp.status}"}
        except urllib.error.HTTPError as e:
            if e.code == 404:
                # لم يُسجَّل بعد — قد يصل لاحقًا (تأخر شبكي)، ليس فشلًا مؤكَّدًا بعد
                return {"outcome": "unknown_needs_query", "detail": "not found yet (404)"}
            return {"outcome": "unknown_needs_query", "detail": f"HTTP {e.code}: {e.reason}"}
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            return {"outcome": "unknown_needs_query", "detail": f"query connection error: {e}"}

    return query_fn
