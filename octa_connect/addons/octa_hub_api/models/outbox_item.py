# -*- coding: utf-8 -*-
"""
octa.hub.outbox.item — طابور دائم فعلي يربط استقبال الحدث بالإرسال (R13).
NOT RUN.

إصلاح حرج (طلب صريح: "أصلح أولًا النجاح الوهمي في العامل"): `run_worker_batch`
كانت تستدعي `item.mark_done()` **بلا أي إرسال حقيقي إطلاقًا** — نجاح وهمي
حرفي، لا مجرد فجوة نظرية. أُعيد بناء الطابور بعقد ثلاثي الحالة يطابق
`lib/outbox.py` المُعاد تصميمه بالكامل (14/14 PASS، منها دليل تكامل حقيقي
ضد خادم HTTP فعلي في `test_outbox_with_real_mock_pos_http_server_...`):
- `pending` → إرسال أولي.
- `awaiting_confirmation` (حالة جديدة): أُرسل فعليًا (أو حاول الإرسال)
  لكن انقطع الاتصال قبل تأكيد الرد — **لا يعني نجاحًا ولا فشلًا**.
- `done`: لا يصله أي مسار في هذا الملف إلا عبر تأكيد `confirmed_success`
  صريح من دالة إرسال أو استعلام حقيقية.

**`run_worker_batch`/`run_query_batch` تتطلبان الآن `dispatch_fn`/`query_fn`
كمعاملين إلزاميين بلا قيمة افتراضية** — هذا يجعل النجاح الوهمي **مستحيلًا
بنيويًا لا مجرد غير مرجَّح**: استدعاء بلا محوِّل حقيقي يرفع `TypeError`
فورًا وواضحًا (فشل صاخب)، بدل نجاح صامت كاذب كما كانت النسخة السابقة تفعل.
**لا محوِّل حقيقي لأي موصل POS متاح بعد في هذا المشروع** (mock_pos_service.py
أداة اختبار، لا موصل إنتاجي) — الـcron الحالي (data/outbox_cron.xml)
سيفشل فورًا عند التشغيل الفعلي لعدم توفر محوِّل، وهذا **الفشل الصحيح
المطلوب** ريثما يُربَط موصل حقيقي، لا نجاحًا مزيَّفًا.
"""
import json as _json

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

STUCK_PROCESSING_TIMEOUT_SECONDS = 300


class OctaHubOutboxItem(models.Model):
    _name = "octa.hub.outbox.item"
    _description = "Persistent outbox item linking event receipt to actual confirmed dispatch (R13)"
    _order = "create_date"

    item_key = fields.Char(required=True, index=True, help="مفتاح فريد للحدث — نفس دور external_order_id")
    order_id = fields.Many2one("octa.hub.order", ondelete="cascade", index=True)
    payload_json = fields.Text(required=True)
    status = fields.Selection([
        ("pending", "بانتظار الإرسال"), ("processing", "قيد المعالجة"),
        ("awaiting_confirmation", "بانتظار تأكيد — أُرسل ولم يُؤكَّد بعد"),
        ("done", "تم (مؤكَّد فعليًا)"), ("dead_letter", "فشل نهائي"),
    ], default="pending", required=True, index=True)
    attempt_count = fields.Integer(default=0)
    max_attempts = fields.Integer(default=5)
    query_attempt_count = fields.Integer(default=0)
    max_query_attempts = fields.Integer(default=10, help="سقف محاولات الاستعلام — لا انتظار أبدي لتأكيد لن يصل")
    next_retry_at = fields.Datetime(default=fields.Datetime.now)
    next_query_at = fields.Datetime()
    external_reference = fields.Char(help="معرّف العملية عند الطرف الآخر، لدعم الاستعلام بعد انقطاع اتصال")
    claimed_by = fields.Char()
    claimed_at = fields.Datetime()
    last_error = fields.Char()

    _uniq_item_key = models.Constraint("unique(item_key)", "لا تكرار لنفس مفتاح عنصر الطابور")

    @api.model
    def enqueue(self, item_key, order, payload: dict):
        """إدراج idempotent — نفس item_key مرتين لا ينشئ عنصرين."""
        existing = self.search([("item_key", "=", item_key)], limit=1)
        if existing:
            return existing
        return self.create({
            "item_key": item_key, "order_id": order.id if order else False,
            "payload_json": _json.dumps(payload, ensure_ascii=False),
        })

    @api.model
    def _reclaim_stuck_processing_items(self):
        """توقف العامل بعد claim وقبل تسجيل النتيجة — **لا يشمل
        awaiting_confirmation عمدًا** (ليست عالقة، تنتظر دورة استعلام
        مجدولة بوعي، تمامًا كما في lib/outbox.py المُختبَرة)."""
        threshold = fields.Datetime.now() - __import__("datetime").timedelta(seconds=STUCK_PROCESSING_TIMEOUT_SECONDS)
        stuck = self.search([("status", "=", "processing"), ("claimed_at", "<", threshold)])
        stuck.write({"status": "pending", "claimed_by": False, "claimed_at": False})

    @api.model
    def claim_batch(self, worker_id, batch_size=20):
        """`try_lock_for_update(limit=...)` — مُتحقَّقة من مصدر Odoo 19
        الحقيقي كالدالة الصحيحة لنمط "خذ المتاح، تجاهل المشغول" (انظر
        audit-findings.md مراجعة خامسة عشرة للتفاصيل الكاملة)."""
        self._reclaim_stuck_processing_items()
        candidates = self.search([
            ("status", "=", "pending"), ("next_retry_at", "<=", fields.Datetime.now()),
        ], order="create_date")
        locked = candidates.try_lock_for_update(limit=batch_size)
        if locked:
            locked.write({"status": "processing", "claimed_by": worker_id,
                          "claimed_at": fields.Datetime.now()})
        return locked

    @api.model
    def claim_for_query(self, worker_id, batch_size=20):
        candidates = self.search([
            ("status", "=", "awaiting_confirmation"), ("next_query_at", "<=", fields.Datetime.now()),
        ], order="create_date")
        return candidates.try_lock_for_update(limit=batch_size)

    def mark_done(self):
        """**لا يُستدعى إلا بعد تأكيد confirmed_success فعلي من dispatch_fn
        أو query_fn** — هذا هو الإصلاح الجوهري. لا مسار آخر في هذا الملف
        يصل لهذه الدالة."""
        self.write({"status": "done", "claimed_by": False})

    def mark_awaiting_confirmation(self, external_reference=None):
        self.write({
            "status": "awaiting_confirmation", "external_reference": external_reference,
            "next_query_at": fields.Datetime.now() + __import__("datetime").timedelta(seconds=5),
            "claimed_by": False,
        })

    def mark_failed(self, error=""):
        for rec in self:
            attempt = rec.attempt_count + 1
            if attempt >= rec.max_attempts:
                rec.write({"status": "dead_letter", "attempt_count": attempt,
                           "last_error": (error or "")[:500], "claimed_by": False})
            else:
                backoff_seconds = min(1.0 * (2 ** attempt), 300.0)
                next_retry = fields.Datetime.now() + __import__("datetime").timedelta(seconds=backoff_seconds)
                rec.write({"status": "pending", "attempt_count": attempt,
                           "next_retry_at": next_retry, "last_error": (error or "")[:500], "claimed_by": False})

    def mark_query_inconclusive(self, error=""):
        for rec in self:
            attempt = rec.query_attempt_count + 1
            if attempt >= rec.max_query_attempts:
                rec.write({"status": "dead_letter", "query_attempt_count": attempt,
                           "last_error": (error or "")[:500], "claimed_by": False})
            else:
                backoff_seconds = min(1.0 * (2 ** attempt), 300.0)
                next_query = fields.Datetime.now() + __import__("datetime").timedelta(seconds=backoff_seconds)
                rec.write({"status": "awaiting_confirmation", "query_attempt_count": attempt,
                           "next_query_at": next_query, "last_error": (error or "")[:500], "claimed_by": False})

    @api.model
    def run_worker_batch(self, dispatch_fn, worker_id="cron", batch_size=20):
        """يُستدعى من ir.cron. `dispatch_fn` **إلزامية بلا قيمة افتراضية**
        — استدعاء بلا محوِّل حقيقي يرفع TypeError فورًا (فشل صاخب صحيح)
        بدل نجاح وهمي صامت كما كانت النسخة السابقة تفعل.

        dispatch_fn(payload: dict) -> dict بمفاتيح:
          {"outcome": "confirmed_success"|"confirmed_failure"|"unknown_needs_query",
           "external_reference": str|None, "detail": str}
        NOT VERIFIED: لا محوِّل حقيقي لأي موصل POS متاح بعد في هذا المشروع.
        """
        items = self.claim_batch(worker_id, batch_size)
        for item in items:
            try:
                result = dispatch_fn(_json.loads(item.payload_json))
            except Exception as e:
                item.mark_failed(error=str(e))
                continue
            outcome = result.get("outcome")
            if outcome == "confirmed_success":
                item.mark_done()
            elif outcome == "confirmed_failure":
                item.mark_failed(error=result.get("detail", ""))
            elif outcome == "unknown_needs_query":
                item.mark_awaiting_confirmation(result.get("external_reference"))
            else:
                # قيمة outcome غير معروفة — لا نخمّن، نعامله كفشل قابل لإعادة
                # المحاولة (لا نجاح صامت لناتج لا نفهمه).
                item.mark_failed(error=f"unknown dispatch outcome: {outcome!r}")

    @api.model
    def run_query_batch(self, query_fn, worker_id="cron", batch_size=20):
        """query_fn(item) -> نفس شكل نتيجة dispatch_fn أعلاه. **إلزامية
        بلا قيمة افتراضية لنفس السبب**. لا تستدعي dispatch_fn إطلاقًا —
        استحالة بنيوية لإعادة إرسال بالخطأ أثناء استعلام (منع تكرار الأثر)."""
        items = self.claim_for_query(worker_id, batch_size)
        for item in items:
            try:
                result = query_fn(item)
            except Exception as e:
                item.mark_query_inconclusive(error=str(e))
                continue
            outcome = result.get("outcome")
            if outcome == "confirmed_success":
                item.mark_done()
            elif outcome == "confirmed_failure":
                item.mark_failed(error=result.get("detail", ""))
            else:
                item.mark_query_inconclusive(error=result.get("detail", ""))
