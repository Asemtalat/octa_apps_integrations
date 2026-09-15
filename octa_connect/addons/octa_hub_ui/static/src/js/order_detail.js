/** @odoo-module **/
/*
 * تفاصيل الطلب (screen 07، Blueprint P146/P74-76): ملخص ثابت + تبويبات
 * (الأصناف والمبالغ/الأحداث/محاولات التوصيل/معلومات الربط) + Timeline
 * واضح من استلام القناة إلى نظام العميل. "لم يصل تأكيد التسجيل بعد؛ جارٍ
 * الاستعلام قبل إعادة الإرسال" — لا نكتب "فشل" لحالة لا نعرف نتيجتها (P75).
 *
 * لم يكن مبنيًا في التسليم السابق. NOT RUN / NOT RENDERED.
 */
import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { OctaTimeline, OctaStatusBadge, OctaLoadingState, OctaErrorState } from "./components/shared_components";

// القسم 9/Blueprint P75: HTTP 200 لا يعني قبول الكاشير. رسائل دقيقة لكل حالة
// نقل، بدل "فشل" العامة لحالة غير معروفة.
const TRANSPORT_MESSAGES = {
    stored: "الطلب محفوظ لدينا، بانتظار الإرسال إلى نظام المطعم",
    pending_dispatch: "بانتظار إرسال الطلب إلى نظام المطعم",
    dispatching: "جارٍ إرسال الطلب الآن",
    registered_confirmed: "تأكد تسجيل الطلب لدى نظام المطعم",
    unknown: "لم يصل تأكيد التسجيل بعد؛ جارٍ الاستعلام قبل إعادة الإرسال",
    needs_intervention: "هذا الطلب يحتاج مراجعة يدوية",
};

// يطابق حرفيًا خيارات event_type في models/order.py::OctaHubOrderEvent —
// أي قيمة جديدة تُضاف هناك يجب أن تُضاف هنا أيضًا (لا مصدر حقيقة مزدوج
// يُفترض تطابقه ضمنيًا؛ لا اختبار آلي يتحقق من هذا التطابق حاليًا لأن هذا
// ملف JS لا Python — فجوة موثَّقة صراحة).
const EVENT_TYPE_LABELS = {
    app_created: "أُنشئ في التطبيق",
    hub_received: "استقبلته المنصة",
    stored: "حُفظ",
    pos_dispatch_started: "بدأ إرساله لنظام المطعم",
    pos_registration_confirmed: "تأكد تسجيله لدى نظام المطعم",
    cashier_seen: "شاهده الكاشير",
    accepted_or_rejected: "قُبل أو رُفض",
    pos_update_received: "وصل تحديث من نظام المطعم",
    app_update_sent: "أُرسل تحديث للتطبيق",
    external_confirmed: "أكّده الطرف الخارجي",
};

export class OctaHubOrderDetail extends Component {
    static template = "octa_hub_ui.OrderDetail";
    static components = { OctaTimeline, OctaStatusBadge, OctaLoadingState, OctaErrorState };
    static props = { action: { type: Object, optional: true }, resId: { type: Number, optional: true } };

    get resId() {
        // إصلاح (R15): مكوّنات ir.actions.client الحقيقية تستقبل resId عبر
        // action.params، لا كـprop مباشر — النسخة السابقة كانت تفترض
        // this.props.resId مباشرة، وهو ما لا يصل هكذا فعليًا من doAction
        // بنوع client action حقيقي في Odoo (NOT VERIFIED — لم يُشغَّل على
        // Odoo حقيقي، لكن هذا الاتساق مبني على قراءة توثيق/أمثلة OWL action).
        return this.props.action?.params?.resId ?? this.props.resId;
    }

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            loading: true, error: null, order: null, activeTab: "items",
            timelineItems: [], attempts: [],
        });
        onWillStart(() => this._load());
    }

    async _load() {
        this.state.loading = true;
        try {
            const [order] = await this.orm.read("octa.hub.order", [this.resId], [
                "external_order_id", "branch_id", "connection_id", "items_snapshot_json",
                "total_minor_units", "currency_id", "transport_state", "commercial_state",
                "payment_state", "event_ids", "attempt_ids",
            ]);
            this.state.order = order;
            // إصلاح حرج بعد مراجعة V2 المستقلة (R15): كانت event_ids/attempt_ids
            // تُمرَّر كما هي مباشرة لمكوّن Timeline — لكن orm.read() على حقل
            // One2many يُرجع فقط قائمة IDs خام (أرقام)، لا سجلات فعلية بها
            // label/time. كان مكوّن Timeline سيعرض عناصر فارغة تمامًا
            // (item.label وitem.time كلاهما undefined لكل عنصر). أُصلح
            // بجلب السجلات الفعلية عبر استدعاء ثانٍ ثم تحويلها للشكل الذي
            // يتوقعه المكوّن فعليًا.
            if (order.event_ids && order.event_ids.length) {
                const events = await this.orm.searchRead(
                    "octa.hub.order.event",
                    [["id", "in", order.event_ids]],
                    ["event_type", "source_timestamp", "received_at", "sequence"],
                    { order: "sequence, id" }
                );
                this.state.timelineItems = events.map((ev) => ({
                    label: EVENT_TYPE_LABELS[ev.event_type] || ev.event_type,
                    // القسم 10: غياب الحدث يعني unavailable لا صفرًا — نُفضّل
                    // توقيت المصدر إن توفر، وإلا نعرض "غير متاح" صراحة بدل
                    // اختلاق وقت وهمي.
                    time: ev.source_timestamp || ev.received_at || null,
                    unknown: !ev.source_timestamp && !ev.received_at,
                }));
            } else {
                this.state.timelineItems = [];
            }
            if (order.attempt_ids && order.attempt_ids.length) {
                this.state.attempts = await this.orm.searchRead(
                    "octa.hub.delivery.attempt",
                    [["id", "in", order.attempt_ids]],
                    ["attempt_id", "idempotency_key_used", "http_status", "result_code",
                     "started_at", "finished_at"],
                    {}
                );
            } else {
                this.state.attempts = [];
            }
        } catch (e) {
            this.state.error = "تعذّر تحميل تفاصيل الطلب";
        } finally {
            this.state.loading = false;
        }
    }

    get transportMessage() {
        if (!this.state.order) return "";
        return TRANSPORT_MESSAGES[this.state.order.transport_state] || this.state.order.transport_state;
    }

    setTab(tab) { this.state.activeTab = tab; }

    openSupportTicket() {
        // Blueprint P45: "دليل واحد للطلب... يمكن تنزيل تقرير دعم منقح دون
        // أسرار". هذا الفعل غير موصول بموديل تذاكر دعم حقيقي بعد — NOT_STARTED.
        this.env.services.notification.add("فتح تذكرة الدعم غير متاح بعد في هذه المرحلة", { type: "warning" });
    }
}

// إصلاح (R15): لم يكن هذا المكوّن مُسجَّلًا في سجل الإجراءات إطلاقًا رغم
// أن order_list.js يستدعيه بالاسم التقني "octa_hub_order_detail" — استدعاء
// بلا وجهة فعلية. أُضيف التسجيل هنا.
registry.category("actions").add("octa_hub_order_detail", OctaHubOrderDetail);
