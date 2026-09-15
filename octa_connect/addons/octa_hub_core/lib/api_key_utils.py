"""
إصدار وتجزئة مفاتيح API (R05، Gate B) — Gate تدقيق مستقل V2.

كان `api_key_fingerprint` (branch.py) موثَّقًا في تعليقاته بأنه "بصمة فقط،
لا نخزن السر" — لكن **لا دالة كانت تحسب هذه البصمة من أي مفتاح خام
إطلاقًا في أي مكان بالمشروع**، ولا دالة إصدار مفتاح واحدة. المقارنة في
`api_controller.py::_authenticate_connection` كانت تقارن قيمة الـHeader
الواردة مباشرة، وكأن العميل يرسل "البصمة" نفسها كسرّه — ما يُبطل الغرض من
وجود بصمة أصلًا (لو البصمة نفسها كافية للمرور، فهي السرّ الفعلي).

هذا أول تنفيذ حقيقي: نفس نمط `invitation.py::issue()` المُثبَت (secrets.
token_urlsafe + sha256، السر الخام لا يُخزَّن أبدًا) لكن لمفاتيح API.
"""
from __future__ import annotations

import hashlib
import secrets

API_KEY_BYTES = 32  # 256-bit، نفس مستوى أمان رموز الدعوة


def generate_api_key() -> tuple[str, str]:
    """يُصدر مفتاحًا خامًا جديدًا وبصمته معًا. المفتاح الخام يُعرَض للمستخدم
    مرة واحدة فقط عند الإصدار (نفس مبدأ SecretRevealOnce في الواجهة)؛
    البصمة فقط هي ما يُخزَّن في قاعدة البيانات."""
    raw_key = secrets.token_urlsafe(API_KEY_BYTES)
    return raw_key, hash_api_key(raw_key)


def hash_api_key(raw_key: str) -> str:
    """بصمة مستقرة وأحادية الاتجاه — لا يمكن استرجاع المفتاح الخام منها."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def looks_like_a_valid_key_format(raw_key: str) -> bool:
    """فحص شكلي سريع قبل أي بحث في قاعدة البيانات (رفض مبكر رخيص لمدخلات
    فارغة أو قصيرة بشكل واضح لا يمكن أن تكون مفتاحًا صادرًا فعليًا) — هذا
    ليس بديلاً عن التحقق الفعلي بالبصمة، فقط تحسين أداء بسيط."""
    return bool(raw_key) and len(raw_key) >= 16
