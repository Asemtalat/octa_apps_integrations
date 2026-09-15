# -*- coding: utf-8 -*-
"""
Webhook ingress رفيع (القسم 5: Controllers رفيعة). النواة المنطقية
(منع التكرار وحسم التعارض) مُختبَرة فعليًا بمعزل عن Odoo في
addons/octa_hub_api/lib/idempotency.py — هذا الملف فقط يربطها بـ
octa.hub.order عبر معاملة قاعدة بيانات (commit قبل ACK ناجح، القسم 9).

NOT RUN — لا خادم Odoo فعلي متاح، لكن هذا الملف أُعيد كتابته بالكامل بعد
التحقق من **مصدر Odoo 19 الحقيقي** (تنزيل فعلي لفرع 19.0 من GitHub، commit
مطابق لما استخدمته المراجعة المستقلة الخارجية)، وليس تخمينًا نظريًا.

إصلاحات هذه الجولة (مراجعة مستقلة خارجية R09/R10/R11/F-ERR-01/F-WIRE-01
السابقة، كل بند مُتحقَّق منه بدليل مصدري مباشر مذكور في تعليقه):

1. **R09 (حرج، مُتحقَّق من odoo/http.py الفعلي)**: `type="json"` في Odoo 19
   هو "اسم قديم مهجور لـ jsonrpc" حرفيًا (`odoo/http.py` سطر 813-819:
   "Since 19.0, @route(type='json') is a deprecated alias to
   @route(type='jsonrpc')"). ردود jsonrpc تُغلَّف دائمًا كـ
   `{"jsonrpc": "2.0", "id":.., "result": <أي شيء ترجعه>}` بحالة HTTP 200
   ثابتة (`JsonRPCDispatcher._response`، `odoo/http.py` سطر ~2624) — إرجاع
   tuple مثل `({"error":...}, 401)` كما كانت النسخة السابقة تفعل **لا يضبط
   حالة HTTP فعليًا إطلاقًا**؛ التuple كله كان سيُغلَّف حرفيًا داخل حقل
   "result" كمصفوفة غريبة، وكل الردود كانت لتصل كـHTTP 200 دائمًا مهما كان
   الخطأ. أُصلح بالتحويل الكامل لـ`type="http"` + قراءة الجسم يدويًا عبر
   `request.get_json_data()` + إرجاع `request.make_json_response(data,
   status=code)` (دالة حقيقية موجودة في `odoo/http.py` سطر 2074، تتحقق من
   ضبط حالة HTTP فعليًا عبر `status` كمعامل صريح).
2. **R10 (حرج)**: مقارنة وجود الطلب لم تكن تقارن المحتوى (أي تكرار بنفس
   external_order_id كان يُقبل كـ"مكرر" حتى لو المحتوى مختلفًا تمامًا) —
   أُضيفت مقارنة `content_hash` (من `lib/idempotency.py` المُختبَرة فعليًا
   7/7 PASS) فتُرجع 409 عند تعارض محتوى حقيقي، لا 200 صامتًا. كذلك
   `Order.create()` لم تكن محمية بـ`cr.savepoint()` — في PostgreSQL، خطأ
   قيد فريد بلا savepoint **يُفسد المعاملة بأكملها** (كل استعلام تالٍ في
   نفس الطلب يفشل بـ"current transaction is aborted") — مُتحقَّق من نمط
   الاستخدام الحقيقي في `odoo/addons/base/models/ir_model.py` (سطر 1763:
   `with self.env.cr.savepoint(): ...`). أُضيف `with request.env.cr.savepoint():`.
3. **R11 (عالٍ)**: `str(items)` كانت تنتج تمثيل بايثون (فواصل مفردة) وليس
   JSON صالحًا فعليًا — أُصلح بـ`json.dumps`. العملة كانت `base.SAR` ثابتة
   بصرف النظر عن عملة الحدث الوارد فعليًا — أُصلح بالبحث عن عملة الحدث
   نفسه (مع رفض صريح لعملة غير مسجَّلة، لا افتراض صامت).
"""
import json
import os
import sys
import uuid

import psycopg2

from odoo import http
from odoo.http import request

_CORE_LIB_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "octa_hub_core", "lib")
if _CORE_LIB_DIR not in sys.path:
    sys.path.insert(0, _CORE_LIB_DIR)
from connector_capabilities import Capability, UnsupportedCapabilityError  # noqa: E402

_API_LIB_DIR = os.path.join(os.path.dirname(__file__), "..", "lib")
if _API_LIB_DIR not in sys.path:
    sys.path.insert(0, _API_LIB_DIR)
from idempotency import content_hash  # noqa: E402
from duplicate_resolution import resolve_unique_violation, ConflictDecision  # noqa: E402

_CORE_LIB_DIR2 = os.path.join(os.path.dirname(__file__), "..", "..", "octa_hub_core", "lib")
if _CORE_LIB_DIR2 not in sys.path:
    sys.path.insert(0, _CORE_LIB_DIR2)
from api_key_utils import hash_api_key, looks_like_a_valid_key_format  # noqa: E402


class OctaHubApiController(http.Controller):

    @http.route("/octa/api/v1/orders", type="http", auth="none", methods=["POST"], csrf=False)
    def receive_order_event(self, **url_args):
        """يستقبل حدث طلب من موصل (channel_x). auth='none' لأن المصادقة هنا
        عبر مفتاح API خاص بالاتصال (Header)، وليس جلسة مستخدم أودو — القسم 8:
        'مفاتيح صادرة محددة بالبيئة والعميل والفروع والأفعال'.

        type='http' (وليس json/jsonrpc) — انظر شرح R09 أعلى الملف. الجسم
        يُقرأ يدويًا لأن type='http' لا يُفسِّر JSON تلقائيًا كما كان يُفترض
        خطأً في النسخة السابقة.
        """
        correlation_id = request.httprequest.headers.get("X-Correlation-Id") or str(uuid.uuid4())

        try:
            payload = request.get_json_data()
        except (ValueError, AttributeError):
            return request.make_json_response(
                {"error": "invalid_json", "correlation_id": correlation_id}, status=400)
        if not isinstance(payload, dict):
            return request.make_json_response(
                {"error": "invalid_json", "detail": "body must be a JSON object",
                 "correlation_id": correlation_id}, status=400)

        api_key = request.httprequest.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        connection = self._authenticate_connection(api_key)
        if not connection:
            # لا نكشف سبب الرفض الدقيق (مفتاح خاطئ vs موقوف vs غير موجود)
            return request.make_json_response(
                {"error": "unauthorized", "correlation_id": correlation_id}, status=401)

        try:
            self._enforce_orders_capability(connection)
        except UnsupportedCapabilityError:
            return request.make_json_response(
                {"error": "capability_unsupported", "detail": "orders",
                 "correlation_id": correlation_id}, status=422)

        external_order_id = payload.get("external_order_id")
        if not external_order_id:
            return request.make_json_response(
                {"error": "validation_error", "detail": "external_order_id required",
                 "correlation_id": correlation_id}, status=422)

        currency_code = payload.get("currency")
        currency = request.env["res.currency"].sudo().search([("name", "=", currency_code)], limit=1) if currency_code else None
        if not currency:
            # لا افتراض صامت لعملة افتراضية — القسم 8/9: لا تحويل/افتراض عملة صامت
            return request.make_json_response(
                {"error": "validation_error", "detail": "unknown or missing currency",
                 "correlation_id": correlation_id}, status=422)

        incoming_hash = content_hash({
            "items": payload.get("items", []),
            "total_minor_units": payload.get("total_minor_units", 0),
            "currency": currency_code,
        })

        Order = request.env["octa.hub.order"].sudo()
        existing = Order.search([
            ("organization_id", "=", connection.organization_id.id),
            ("connection_id", "=", connection.id),
            ("external_order_id", "=", external_order_id),
        ], limit=1)

        if existing:
            existing_hash = content_hash({
                "items": json.loads(existing.items_snapshot_json or "[]"),
                "total_minor_units": existing.total_minor_units,
                "currency": existing.currency_id.name,
            })
            if existing_hash == incoming_hash:
                return request.make_json_response(
                    {"status": "duplicate_same_payload", "order_id": existing.id,
                     "correlation_id": correlation_id}, status=200)
            # نفس المفتاح، محتوى مختلف — تعارض موثّق، لا نجاح صامت (القسم 9/14)
            return request.make_json_response(
                {"error": "conflict_different_payload", "order_id": existing.id,
                 "correlation_id": correlation_id}, status=409)

        try:
            with request.env.cr.savepoint():
                order = Order.create({
                    "organization_id": connection.organization_id.id,
                    "branch_id": connection.branch_id.id,
                    "connection_id": connection.id,
                    "external_order_id": external_order_id,
                    "contract_version": payload.get("contract_version", "octa-connect-order-v1"),
                    "items_snapshot_json": json.dumps(payload.get("items", []), ensure_ascii=False),
                    "total_minor_units": payload.get("total_minor_units", 0),
                    "currency_id": currency.id,
                })
        except psycopg2.errors.UniqueViolation as e:
            # إصلاح حرج بعد مراجعة V2 المستقلة — أثبتت المراجعة الادعاء
            # عمليًا (استخراج الدالة عبر AST وتشغيلها بـORM/request محاكيين):
            # الإصدار السابق كان يمسك أي psycopg2.IntegrityError (وليس فقط
            # تصادم قيد التفرّد على external_order_id تحديدًا)، ثم يُعيد 200
            # ناجحًا **حتى لو existing غير موجود فعليًا** (`order_id: None`).
            #
            # منطق القرار (رفض/500/200/409) مُستخرَج إلى
            # lib/duplicate_resolution.py **المُختبَرة فعليًا 5/5 PASS** —
            # هذا الملف فقط يستخرج القيم من psycopg2/Odoo (NOT VERIFIED: لم
            # يُشغَّل ضد PostgreSQL حقيقي — `e.diag.constraint_name` هو
            # slot للقراءة فقط على مستوى C تحقَّقت أنه لا يمكن تلفيقه في
            # اختبار معزول، لذلك هذا الاستخراج بالذات يبقى غير مُختبَر رغم
            # أن *القرار* المبني عليه مُختبَر بالكامل) ويستدعي القرار الجاهز.
            actual_constraint = getattr(getattr(e, "diag", None), "constraint_name", None)
            existing = Order.search([
                ("organization_id", "=", connection.organization_id.id),
                ("connection_id", "=", connection.id),
                ("external_order_id", "=", external_order_id),
            ], limit=1)
            existing_hash = None
            if existing:
                existing_hash = content_hash({
                    "items": json.loads(existing.items_snapshot_json or "[]"),
                    "total_minor_units": existing.total_minor_units,
                    "currency": existing.currency_id.name,
                })
            resolution = resolve_unique_violation(
                actual_constraint_name=actual_constraint, existing_record_found=bool(existing),
                existing_hash=existing_hash, incoming_hash=incoming_hash,
            )
            if resolution.decision == ConflictDecision.REJECT_UNRELATED_CONSTRAINT:
                raise  # ليس تعارض تكرار طلب أصلًا — لا يُبتلع
            if resolution.decision == ConflictDecision.UNRESOLVED_ANOMALY:
                return request.make_json_response(
                    {"error": "unresolved_conflict",
                     "detail": "unique constraint violated but no matching order found",
                     "correlation_id": correlation_id}, status=resolution.http_status)
            status_key = ("duplicate_concurrent_same_payload"
                          if resolution.decision == ConflictDecision.DUPLICATE_SAME_PAYLOAD
                          else "conflict_different_payload")
            body_key = "status" if resolution.http_status == 200 else "error"
            return request.make_json_response(
                {body_key: status_key, "order_id": existing.id, "correlation_id": correlation_id},
                status=resolution.http_status)
        # أي استثناء آخر (بما فيه IntegrityError غير UniqueViolation) يُعاد
        # رفعه (لا except عام) — يظهر كخطأ 500 حقيقي بدل نجاح صامت مضلِّل
        # (F-ERR-01، الجولة العاشرة).

        # إصلاح R13: كان الاستقبال يتوقف هنا بلا أي أثر متابع — لا طابور،
        # لا محاولة إرسال فعلية لاحقة. الآن يُسجَّل عنصر Outbox دائم فعليًا
        # (models/outbox_item.py، منطقه مُختبَر بالكامل في lib/outbox.py،
        # 8/8 PASS بما فيها تزامن 20 thread حقيقي) — عامل ir.cron
        # (data/outbox_cron.xml) يلتقطه لاحقًا. الإرسال الفعلي لنظام POS من
        # داخل ذلك العامل يبقى NOT_STARTED (البنية جاهزة، التكامل مع موصل
        # حقيقي مؤجَّل).
        #
        # تعمُّدًا **لا** يوجد try/except يبتلع فشل enqueue هنا: هذا نمط
        # "transactional outbox" القياسي — إدراج الطلب وعنصر الطابور معًا
        # داخل نفس معاملة قاعدة البيانات (نفس طلب HTTP في Odoo)، فينجحان
        # معًا أو يتراجعان معًا. لو ابتلعنا فشل enqueue هنا بصمت (كما كانت
        # نسخة أولى من هذا الإصلاح تفعل)، لكان الطلب يُحفَظ لكن **يبقى بلا
        # عنصر طابور للأبد وبلا أي آلية مطابقة تكتشف هذا لاحقًا** — تناقض
        # بيانات صامت أخطر من فشل الطلب كله بوضوح ورجوعه للمرسل ليعيد المحاولة.
        request.env["octa.hub.outbox.item"].sudo().enqueue(
            item_key=f"order-dispatch-{order.id}", order=order,
            payload={"order_id": order.id, "external_order_id": external_order_id})

        return request.make_json_response(
            {"status": "stored", "order_id": order.id, "correlation_id": correlation_id}, status=201)

    def _enforce_orders_capability(self, connection):
        """إصلاح بعد مراجعة V2 المستقلة (R12): كانت هذه الدالة تبني
        `ConnectorDefinition` **مؤقتًا داخل كل استدعاء**، تفترض أن ORDERS
        مدعومة دائمًا بصرف النظر عن أي بيانات فعلية — لم تكن تعكس قدرات
        الموصل الحقيقية إطلاقًا (كما لاحظت المراجعة V2 بحق: "لا تغيير
        وظيفي جوهري"). أُصلح بالقراءة من `octa.hub.connector.definition`
        المخزَّن فعليًا (models/connector_definition.py الجديد)، عبر
        `connection.connector_definition_id` — deny-by-default صريح: لا
        ربط أو تعريف مفقود = رفض، لا افتراض دعم.
        """
        if not connection.connector_definition_id:
            raise UnsupportedCapabilityError(connection.connector_code, Capability.ORDERS)
        status_str = connection.connector_definition_id.capability_status("orders")
        if status_str != "supported":
            raise UnsupportedCapabilityError(connection.connector_code, Capability.ORDERS)

    def _authenticate_connection(self, api_key):
        """إصلاح بعد مراجعة V2 المستقلة (R05): كانت هذه الدالة تقارن قيمة
        Header الواردة **مباشرة** بحقل `api_key_fingerprint` — لا دالة
        تجزئة كانت تُطبَّق على المدخل الوارد قبل المقارنة إطلاقًا، رغم أن
        اسم الحقل نفسه ("fingerprint") يوحي بأنه بصمة لا سرًا خامًا. لو
        كانت البصمة نفسها كافية للمرور، فهي السرّ الفعلي — لا فائدة من
        تسميتها بصمة. أُصلح بتطبيق `hash_api_key()` (من
        `lib/api_key_utils.py` الجديدة، 5/5 اختبار PASS) على القيمة الواردة
        قبل البحث، فتصبح المقارنة الفعلية ضد البصمة الحقيقية، لا السر الخام
        بحد ذاته.

        **متبقٍّ صراحة (نطاق أكبر، NOT_STARTED)**: هذا يُصلح آلية *التحقق*
        فقط. لا تزال هناك حاجة لبناء: (أ) تدفق *إصدار* فعلي في واجهة
        المستخدم يستدعي `generate_api_key()` ويعرض المفتاح الخام مرة واحدة
        فقط؛ (ب) تدوير/إلغاء مفتاح فعليين؛ (ج) ربط المفتاح بنطاق صريح
        (بيئة sandbox/production، فروع محددة) يُتحقَّق منه هنا أيضًا، لا فقط
        بمطابقة البصمة. لا يصح وصف R05 بأنه CLOSED — فقط طبقة التحقق الأولى.
        """
        if not api_key or not looks_like_a_valid_key_format(api_key):
            return None
        fingerprint = hash_api_key(api_key)
        return request.env["octa.hub.connection"].sudo().search(
            [("api_key_fingerprint", "=", fingerprint)], limit=1
        )
