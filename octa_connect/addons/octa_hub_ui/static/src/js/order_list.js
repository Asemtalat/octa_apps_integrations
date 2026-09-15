/** @odoo-module **/
/*
 * قائمة الطلبات (screen 06، Blueprint P145/P73-74 من Phase_1.md):
 * "رقم التطبيق ورقم المنصة والفرع والقناة والإجمالي وحالة النقل وحالة الطلب
 * وآخر تحديث" + فصل الحالة التجارية عن حالة النقل + فلاتر + بحث دقيق بالمعرفات.
 *
 * لم يكن مبنيًا إطلاقًا في التسليم السابق (كان مسجّلاً NOT_STARTED في
 * requirements-coverage.md، بند C3). هذا أول تنفيذ له.
 *
 * NOT RUN / NOT RENDERED — لا متصفح Odoo حقيقي. لا يحمّل كل الحمولة لكل صف
 * (القسم 11: "لا تحميل كامل الطلبات في المتصفح")، فقط الحقول المعروضة.
 */
import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { OctaStatusBadge, OctaEmptyState, OctaErrorState, OctaLoadingState } from "./components/shared_components";

const TRANSPORT_LABELS = {
    stored: ["unknown", "محفوظ"],
    pending_dispatch: ["warning", "ينتظر الإرسال"],
    dispatching: ["warning", "قيد الإرسال"],
    registered_confirmed: ["success", "تأكد التسجيل"],
    unknown: ["unknown", "غير معروف"],
    needs_intervention: ["danger", "يحتاج تدخلًا"],
};
const COMMERCIAL_LABELS = {
    new: ["unknown", "جديد"], accepted: ["success", "مقبول"], rejected: ["danger", "مرفوض"],
    in_preparation: ["warning", "قيد التحضير"], ready: ["success", "جاهز"],
    completed: ["success", "مكتمل"], cancelled: ["danger", "ملغي"],
};

export class OctaHubOrderList extends Component {
    static template = "octa_hub_ui.OrderList";
    static components = { OctaStatusBadge, OctaEmptyState, OctaErrorState, OctaLoadingState };

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            loading: true,
            error: null,
            rows: [],
            filters: { date_from: null, date_to: null, branch_id: null, channel: null, state: null },
            page: 1,
            pageSize: 50, // حجم سجلات مضبوط — القسم 11
            total: 0,
        });
        onWillStart(() => this.reload());
    }

    transportBadge(state) { return TRANSPORT_LABELS[state] || ["unknown", state]; }
    commercialBadge(state) { return COMMERCIAL_LABELS[state] || ["unknown", state]; }

    async reload() {
        this.state.loading = true;
        this.state.error = null;
        try {
            // فقط الحقول المعروضة في القائمة — لا Payload كامل لكل صف (القسم 11)
            const result = await this.orm.searchRead(
                "octa.hub.order",
                this._buildDomain(),
                ["external_order_id", "branch_id", "connection_id", "total_minor_units",
                 "currency_id", "transport_state", "commercial_state", "write_date"],
                { limit: this.state.pageSize, offset: (this.state.page - 1) * this.state.pageSize }
            );
            this.state.rows = result;
        } catch (e) {
            this.state.error = "تعذّر تحميل قائمة الطلبات الآن";
        } finally {
            this.state.loading = false;
        }
    }

    _buildDomain() {
        const domain = [];
        const f = this.state.filters;
        if (f.date_from) domain.push(["create_date", ">=", f.date_from]);
        if (f.date_to) domain.push(["create_date", "<=", f.date_to]);
        if (f.branch_id) domain.push(["branch_id", "=", f.branch_id]);
        if (f.channel) domain.push(["connection_id.connector_code", "=", f.channel]);
        if (f.state) domain.push(["transport_state", "=", f.state]);
        return domain;
        // ملاحظة: التصدير (export) يجب أن يحترم نفس هذا الـdomain ونطاق
        // الصلاحيات (القسم 10) — دالة التصدير المرتبطة NOT_STARTED بعد.
    }

    openDetail(orderId) {
        // إصلاح بعد مراجعة مستقلة خارجية (R15): كان هذا يبني doAction بنوع
        // "ir.actions.act_window" لكن بحقل "tag" (خاص بـir.actions.client
        // فقط، لا معنى له في act_window) — خلط غير متسق بين نمطين. أُصلح
        // إلى ir.actions.client حقيقي، يمرر resId عبر params (كما تقرأه
        // order_detail.js الآن من action.params، لا كـprop مباشر).
        this.env.services.action.doAction({
            type: "ir.actions.client", tag: "octa_hub_order_detail",
            params: { resId: orderId },
        });
    }
}

// إصلاح بعد مراجعة مستقلة خارجية (R15): هذا المكوّن لم يكن مُسجَّلًا في
// سجل الإجراءات إطلاقًا — حتى بوجود ir.actions.client/menuitem في XML
// (المُضافة أيضًا هذه الجولة، انظر views/ui_actions.xml)، بلا هذا الاستدعاء
// فلا شيء كان سيربط الاسم التقني "octa_hub_order_list" بهذا المكوّن الفعلي.
registry.category("actions").add("octa_hub_order_list", OctaHubOrderList);
