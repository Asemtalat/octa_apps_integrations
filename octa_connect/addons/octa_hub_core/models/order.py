# -*- coding: utf-8 -*-
"""
octa.hub.order — الطلب الموحد (القسم 9). لا نُنشئ pos.order/sale.order/
account.move داخل الـ Hub لمجرد استقبال رسالة (وثيقة المنتج، القسم 2).
NOT RUN — المنطق المطابق مُختبَر فعليًا بمعزل عن Odoo في
addons/octa_hub_api/lib/idempotency.py (انظر docs/test-report.md).
"""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

# إصلاح بعد المراجعة السادسة (أثناء كتابة RUNBOOK.md): كان sys.path.insert
# يُستدعى داخل write() في كل استدعاء — يُدرج نفس المسار في sys.path مرارًا
# بلا داعٍ (تراكم غير محدود على مدى عمر العملية). نُصلحه بفعله مرة واحدة
# فقط عند تحميل الموديل، لا في كل نداء.
import sys as _sys
import os as _os
_LIB_DIR = _os.path.join(_os.path.dirname(__file__), "..", "lib")
if _LIB_DIR not in _sys.path:
    _sys.path.insert(0, _LIB_DIR)
from state_machine import validate_transport_transition, validate_commercial_transition, IllegalTransitionError


class OctaHubOrder(models.Model):
    _name = "octa.hub.order"
    _description = "Unified Order snapshot (transport/commercial/payment tracked independently)"
    _order = "create_date desc"

    organization_id = fields.Many2one("octa.hub.organization", required=True, index=True, ondelete="restrict")
    branch_id = fields.Many2one("octa.hub.branch", required=True, index=True, ondelete="restrict")
    connection_id = fields.Many2one("octa.hub.connection", required=True, index=True, ondelete="restrict")
    external_order_id = fields.Char(required=True, index=True,
                                     help="فريد داخل نطاق (organization, connection) وفق عقد المصدر")
    contract_version = fields.Char(required=True, help="إصدار صيغة الطلب الموحد وقت الاستلام")

    # لقطة ثابتة رغم تعديل الكتالوج لاحقًا (القسم 9)
    items_snapshot_json = fields.Text(required=True)
    total_minor_units = fields.Integer(required=True, help="مال integer minor units، لا float أبدًا")
    currency_id = fields.Many2one("res.currency", required=True)

    # ثلاثة محاور منفصلة (القسم 9)
    transport_state = fields.Selection([
        ("stored", "محفوظ"), ("pending_dispatch", "ينتظر الإرسال"),
        ("dispatching", "قيد الإرسال"), ("registered_confirmed", "تأكد التسجيل"),
        ("unknown", "النتيجة مجهولة"), ("needs_intervention", "يحتاج تدخلًا"),
    ], default="stored", required=True)
    commercial_state = fields.Selection([
        ("new", "جديد"), ("accepted", "مقبول"), ("rejected", "مرفوض"),
        ("in_preparation", "قيد التحضير"), ("ready", "جاهز"),
        ("completed", "مكتمل"), ("cancelled", "ملغي"),
    ], default="new", required=True)
    payment_state = fields.Selection([
        ("unknown", "غير معروف"), ("pending", "معلّق"),
        ("settled", "مُسوّى"), ("disputed", "متنازع عليه"),
    ], default="unknown", required=True, help="مستقلة لا تُستنتج من النقل أو التحضير")

    # إصلاح R14 (عمق، بعد مراجعتين مستقلتين متتاليتين): كانت
    # get_dashboard_metrics تحسب "زمن النقل" من write_date - create_date —
    # تقريب خام يتأثر بـ**أي** كتابة على السجل (لا تحديدًا لحظة التسجيل
    # الفعلي)، وinstance واحد فقط لـwrite_date يُستبدَل بكل تعديل لاحق مهما
    # كان غير متعلق بالنقل. حقلا التوقيت الصريحان هنا يُسجَّلان **فقط** عند
    # لحظة الانتقال الفعلية (في write()، لا مُشتقّان من ميتاداتا عامة).
    dispatch_started_at = fields.Datetime(readonly=True, help="لحظة الانتقال الفعلية لـdispatching، لا وقت أي تعديل عام")
    registered_confirmed_at = fields.Datetime(readonly=True, help="لحظة الانتقال الفعلية لـregistered_confirmed")

    event_ids = fields.One2many("octa.hub.order.event", "order_id")
    attempt_ids = fields.One2many("octa.hub.delivery.attempt", "order_id")

    # إصلاح حرج بعد مراجعة مستقلة خارجية (R03)، مُتحقَّق منه بمصدر Odoo 19
    # الفعلي: `odoo/orm/model_classes.py` يسجّل صراحة أن `_sql_constraints`
    # "لم تعد مدعومة" ("Model attribute '_sql_constraints' is no longer
    # supported, please define models.Constraint on the model") — لا خطأ
    # حاسم، بل **تحذير فقط، والقيد نفسه يُتجاهَل صامتًا ولا يُنشأ إطلاقًا**.
    # هذا كان يعني أن **القيد الأهم في كامل التصميم** (منع تكرار الطلب على
    # مستوى قاعدة البيانات، أساس كل ضمانات idempotency في هذا المشروع) لم
    # يكن سيُطبَّق فعليًا على أي تثبيت Odoo 19 حقيقي. أُصلح بالتحويل إلى
    # `models.Constraint` الجديدة (مُتحقَّق من صياغتها الدقيقة في
    # `odoo/orm/table_objects.py::Constraint.__init__` من مصدر Odoo 19 نفسه).
    _uniq_org_conn_external_order = models.Constraint(
        "unique(organization_id, connection_id, external_order_id)",
        "external_order_id مكرر لنفس العميل والاتصال — استخدم استعلامًا بدل إنشاء نسخة جديدة",
    )

    @api.model_create_multi
    def create(self, vals_list):
        """إصلاح بعد مراجعة خامسة (تدقيق ذاتي): الحاجز في write() أدناه
        **لا يحمي create()** — في Odoo لا تمر القيم الابتدائية عبر write()،
        فأي كود كان يقدر يستدعي create({'commercial_state': 'completed',
        ...}) وينشئ طلبًا يبدأ من حالة نهائية مباشرة، متفاديًا الحاجز
        بالكامل. لم يكن هذا مغطى في الإصلاح السابق رغم أن write() أُضيف
        خصيصًا لهذا الغرض — فجوة حقيقية في تغطية الإصلاح نفسه. القاعدة هنا:
        الإنشاء يجب أن يبدأ دائمًا من الحالة الافتراضية؛ أي تمرير صريح لقيمة
        غير ابتدائية عند create() يُرفض، ولو أراد أحد تغييرها لاحقًا فليمر
        عبر write() (وهناك الحاجز يعمل فعليًا).
        """
        for vals in vals_list:
            if vals.get("transport_state") not in (None, "stored"):
                raise ValidationError(_("لا يمكن إنشاء طلب يبدأ من حالة نقل غير 'محفوظ' مباشرة"))
            if vals.get("commercial_state") not in (None, "new"):
                raise ValidationError(_("لا يمكن إنشاء طلب يبدأ من حالة تجارية غير 'جديد' مباشرة"))
        return super().create(vals_list)

    def write(self, vals):
        """إصلاح بعد المراجعة الرابعة: لم يكن هناك أي حاجز يمنع كتابة أي
        قيمة حالة مباشرة (مثال: كتابة commercial_state='new' فوق طلب
        'completed' سابقًا) — أي كود، بما فيه خطأ برمجي بسيط، كان يقدر
        يخالف Phase_1.md §9 ("تحديث قديم لا يعيد الطلب لحالة تحضير") بلا أي
        رفض. المنطق مُختبَر فعليًا بمعزل عن Odoo في lib/state_machine.py
        (11/11 PASS)؛ هذا الاستدعاء فقط يربطه. الاستيراد نفسه انتقل لأعلى
        الملف (مرة واحدة فقط) بعد المراجعة السادسة — انظر التعليق هناك.
        """
        if "transport_state" in vals or "commercial_state" in vals:
            for order in self:
                try:
                    if "transport_state" in vals:
                        validate_transport_transition(order.transport_state, vals["transport_state"])
                    if "commercial_state" in vals:
                        validate_commercial_transition(order.commercial_state, vals["commercial_state"])
                except IllegalTransitionError as e:
                    raise ValidationError(str(e)) from e
            # إصلاح R14: تسجيل التوقيت الصريح عند لحظة الانتقال الفعلية فقط
            # (لا عند أي كتابة أخرى غير متعلقة) — يُضاف لـvals قبل الكتابة
            # الفعلية بدل استنتاجه لاحقًا من write_date عام.
            if vals.get("transport_state") == "dispatching":
                vals.setdefault("dispatch_started_at", fields.Datetime.now())
            if vals.get("transport_state") == "registered_confirmed":
                vals.setdefault("registered_confirmed_at", fields.Datetime.now())
        return super().write(vals)

    @api.model
    def get_dashboard_metrics(self):
        """يُستدعى من octa_hub_ui/static/src/js/dashboard.js. لم تكن هذه
        الدالة موجودة في التسليم السابق رغم أن الواجهة تستدعيها — bug حقيقي
        اكتُشف بإعادة القراءة وأُصلح هنا. تُرجع الأربع قيم فقط (القسم 9):
        المستلمة، المسجّلة، تحتاج تدخلًا، وp95 النقل — لكل منها الفترة نفسها
        (آخر 24 ساعة) حتى لا تُخلط حالة الطلب التجارية بحالة النقل.

        NOT RUN — يعتمد على سجلات فعلية في قاعدة بيانات Odoo غير متاحة هنا.

        إصلاح بعد Gate E (OC05-17): p95 كان `None` بلا أي حساب فعلي — الآن
        يُحسب فعليًا عبر lib/reliability_metrics.py (مُختبَر 7/7 PASS بمعزل
        عن Odoo) بدل عنصر نائب دائم.

        إصلاح إضافي (R14 عمق، بعد مراجعتين مستقلتين متتاليتين): كان
        الحساب يشتق من `write_date`/`create_date` العامين (تقريب خام يتأثر
        بأي كتابة). الآن يستخدم `dispatch_started_at`/`registered_confirmed_at`
        الصريحين، المُسجَّلين فقط عند لحظة الانتقال الفعلية في `write()` —
        قياس حقيقي لفترة "بدء الإرسال حتى تأكيد التسجيل" تحديدًا، لا وقت
        الإنشاء الكلي.
        """
        import sys as _sys, os as _os
        _lib_dir = _os.path.join(_os.path.dirname(__file__), "..", "lib")
        if _lib_dir not in _sys.path:
            _sys.path.insert(0, _lib_dir)
        from reliability_metrics import compute_metric

        domain_24h = [("create_date", ">=", fields.Datetime.now() - __import__("datetime").timedelta(hours=24))]
        orders_24h = self.search(domain_24h)
        all_time_count = self.search_count([])

        needs_intervention = self.search_count([("transport_state", "=", "needs_intervention")])
        # إصلاح بعد مراجعة مستقلة خارجية (R14): هذا العدد **لم يكن مقيَّدًا
        # بنافذة الـ24 ساعة** بينما received_count/registered_confirmed_count
        # كانا كذلك — خلط نوافذ زمنية مختلفة في رد واحد بلا توضيح، قد يُضلِّل
        # (مثال: "16 يحتاج تدخلًا" قد تشمل طلبات قديمة جدًا مختلطة بأخرى
        # حديثة دون تمييز). القرار: يبقى العدد كليًا-عبر-الزمن عمدًا (مشكلة
        # عالقة تحتاج تدخلًا تبقى مهمة بصرف النظر عن عمرها)، لكن **اسم
        # الحقل نفسه يوضّح النطاق الآن صراحة** بدل الإيحاء بأنه يطابق نافذة
        # الـ24 ساعة الأخرى ضمنيًا.

        # إصلاح R14 (عمق، بعد مراجعتين مستقلتين متتاليتين لاحظتا نفس النقص):
        # كانت هذه تحسب من write_date - create_date — تقريب خام يتأثر بأي
        # كتابة على السجل. الآن تُحسب من dispatch_started_at إلى
        # registered_confirmed_at الصريحين (يُسجَّلان فقط عند لحظة الانتقال
        # الفعلية في write()، لا عند أي تعديل آخر). "زمن النقل" هنا يقصد
        # تحديدًا الفترة من بدء الإرسال حتى تأكيد التسجيل — لا من الإنشاء
        # الكلي، وهذا أدق لما يطلبه القسم 10 (فصل زمن النقل عن انتظار
        # الكاشير وعن معالجة النظام الخارجي الأوسع).
        durations = []
        for o in orders_24h:
            if o.transport_state == "registered_confirmed" and o.dispatch_started_at and o.registered_confirmed_at:
                durations.append((o.registered_confirmed_at - o.dispatch_started_at).total_seconds())
            else:
                durations.append(None)  # لا صفر — البيانات الناقصة (لا توقيتان صريحان) تبقى ناقصة صراحة
        p95_result = compute_metric(durations)

        return {
            "metrics": {
                "received_count": len(orders_24h),
                "registered_confirmed_count": len(orders_24h.filtered(lambda o: o.transport_state == "registered_confirmed")),
                "needs_intervention_count_all_time": needs_intervention,
                "transport_p95_seconds": p95_result.p95,  # None إن لم توجد عينات كافية — صريح
                "transport_median_seconds": p95_result.median,
                "transport_p99_seconds": p95_result.p99,
                "transport_p95_sample_count": p95_result.sample_count,
                "transport_p95_completeness": p95_result.completeness_ratio,
                "all_time_order_count": all_time_count,
            },
            "exceptions": [],  # مركز الاستثناءات (screen 08) غير موصول بعد — NOT_STARTED
            "computed_at": fields.Datetime.now(),
            "stale": False,
        }


class OctaHubOrderEvent(models.Model):
    _name = "octa.hub.order.event"
    _description = "Timestamped event in an order's lifecycle"
    _order = "sequence, id"

    order_id = fields.Many2one("octa.hub.order", required=True, ondelete="cascade", index=True)
    event_id = fields.Char(required=True, help="event_id فريد من المصدر لكل حدث وارد")
    event_type = fields.Selection([
        ("app_created", "إنشاء التطبيق"), ("hub_received", "استقبال hub"),
        ("stored", "الحفظ"), ("pos_dispatch_started", "بدء إرسال POS"),
        ("pos_registration_confirmed", "تأكيد التسجيل"), ("cashier_seen", "عرض الكاشير"),
        ("accepted_or_rejected", "قبول/رفض"), ("pos_update_received", "استقبال تحديث POS"),
        ("app_update_sent", "إرسال تحديث التطبيق"), ("external_confirmed", "تأكيد الطرف الخارجي"),
    ], required=True)
    sequence = fields.Integer(default=10)
    source_timestamp = fields.Datetime(help="وقت المصدر إن توفر — 'غياب الحدث يعني unavailable لا صفرًا'")
    received_at = fields.Datetime(required=True, default=fields.Datetime.now)
    is_automated_ack = fields.Boolean(default=False, help="قبول آلي لا يُحسب كاستجابة كاشير (القسم 10)")

    _uniq_order_event_id = models.Constraint("unique(order_id, event_id)", "event_id مكرر لنفس الطلب")


class OctaHubDeliveryAttempt(models.Model):
    _name = "octa.hub.delivery.attempt"
    _description = "Each dispatch attempt to the customer POS/ERP system"
    _order = "id"

    order_id = fields.Many2one("octa.hub.order", required=True, ondelete="cascade", index=True)
    attempt_id = fields.Char(required=True, help="attempt_id فريد — كل محاولة قابلة للتتبع")
    idempotency_key_used = fields.Char()
    http_status = fields.Integer(help="200 وحده لا يعني قبول الكاشير أو تأكيد التطبيق (القسم 9)")
    result_code = fields.Selection([
        ("registered_confirmed", "تأكد التسجيل"), ("unknown", "مجهول"),
        ("conflict", "تعارض"), ("rate_limited", "429"), ("token_expired", "توكن منتهٍ"),
        ("timeout", "انتهاء مهلة"),
    ])
    started_at = fields.Datetime()
    finished_at = fields.Datetime()

    _uniq_order_attempt_id = models.Constraint("unique(order_id, attempt_id)", "attempt_id مكرر لنفس الطلب")
