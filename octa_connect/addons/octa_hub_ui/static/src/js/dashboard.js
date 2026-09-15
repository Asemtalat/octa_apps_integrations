/** @odoo-module **/
/*
 * لوحة النظرة العامة (screen 05، Blueprint P144: "عدد الطلبات، المسجل، الذي
 * يحتاج متابعة، حالة القنوات ومنحنى آخر 24 ساعة" + Phase_1.md §9/§13).
 *
 * إصلاح بعد المراجعة الثانية: كان هذا الملف يشاور على template
 * "octa_hub_ui.Dashboard" غير موجود، وعلى دالة خلفية get_dashboard_metrics
 * غير موجودة — bug حقيقي كان سيمنع تحميل الموديول بالكامل. اتصلح الاثنين:
 * الـ template موجود الآن في xml/dashboard.xml، والدالة في
 * addons/octa_hub_core/models/order.py::get_dashboard_metrics.
 *
 * NOT RUN / NOT RENDERED — لا متصفح Odoo حقيقي في هذه البيئة.
 */
import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import {
    OctaStatusBadge, OctaMetricCard, OctaEmptyState, OctaErrorState, OctaLoadingState, OctaTimeline,
} from "./components/shared_components";

export class OctaHubDashboard extends Component {
    static template = "octa_hub_ui.Dashboard";
    static components = { OctaStatusBadge, OctaMetricCard, OctaEmptyState, OctaErrorState, OctaLoadingState, OctaTimeline };

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            loading: true,
            error: null,
            stale: false,
            metrics: null,        // null = لم يُحمَّل بعد؛ التمييز بين null وصفر مقصود (القسم 10)
            exceptions: [],       // قائمة استثناءات مرتبة بالأثر والعمر (Blueprint P145)
            lastUpdatedAt: null,
        });
        onWillStart(() => this._loadMetrics());
    }

    async _loadMetrics() {
        this.state.loading = true;
        this.state.error = null;
        try {
            const result = await this.orm.call("octa.hub.order", "get_dashboard_metrics", []);
            this.state.metrics = result.metrics;
            this.state.exceptions = result.exceptions || [];
            this.state.lastUpdatedAt = result.computed_at;
            this.state.stale = Boolean(result.stale);
        } catch (e) {
            // فشل تحميل هذا القسم فقط لا يمحو بقية الصفحة (القسم 9)
            this.state.error = "تعذّر تحميل المؤشرات الآن";
        } finally {
            this.state.loading = false;
        }
    }

    get hasReceivedFirstOrderEver() {
        // Blueprint P70: حالة البداية الفارغة "لم يصل أول طلب بعد" منفصلة عن
        // حالة "لا توجد طلبات في هذه الفترة" — تمييز صريح مطلوب.
        return this.state.metrics && this.state.metrics.all_time_order_count > 0;
    }
}

registry.category("actions").add("octa_hub_dashboard", OctaHubDashboard);
