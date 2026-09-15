/** @odoo-module **/
/*
 * مكوّنات قابلة لإعادة الاستخدام — تجمع قائمتي Phase_1.md §13 وBlueprint P209
 * (StatusBadge, MetricCard, EmptyState, ErrorState, LoadingState, Timeline,
 * SecretRevealOnce). لم تكن موجودة كمكوّنات منفصلة في التسليم السابق —
 * dashboard.js كان يشاور على كلاسات CSS بلا مكوّنات OWL فعلية خلفها.
 *
 * NOT RUN / NOT RENDERED — لا متصفح Odoo حقيقي في هذه البيئة. معاينة بصرية
 * مكافئة (HTML/CSS ثابت بنفس design tokens) عُرضت في المحادثة للمراجعة.
 */
import { Component } from "@odoo/owl";

// القسم 13: "الحالة لا تعتمد على اللون فقط" — لذلك كل StatusBadge يحمل نصًا
// دائمًا، وليس دائرة ملونة فقط.
export class OctaStatusBadge extends Component {
    static template = "octa_hub_ui.StatusBadge";
    static props = {
        kind: { type: String }, // "success" | "warning" | "danger" | "unknown"
        label: { type: String }, // نص عربي مفهوم دائمًا — القسم 13
    };
}

export class OctaMetricCard extends Component {
    static template = "octa_hub_ui.MetricCard";
    static props = {
        label: String,
        value: [String, Number, { value: null }], // null = "غير متاح" لا صفر (القسم 10)
        period: { type: String, optional: true },
    };
}

export class OctaEmptyState extends Component {
    static template = "octa_hub_ui.EmptyState";
    static props = { message: String, actionLabel: { type: String, optional: true }, onAction: { type: Function, optional: true } };
}

export class OctaErrorState extends Component {
    static template = "octa_hub_ui.ErrorState";
    static props = { message: String };
}

export class OctaLoadingState extends Component {
    static template = "octa_hub_ui.LoadingState";
    static props = {};
}

export class OctaTimeline extends Component {
    static template = "octa_hub_ui.Timeline";
    static props = {
        // كل عنصر: {label, time, unknown} — القسم 10: غياب الحدث = unavailable لا صفر
        items: Array,
    };
}

export class OctaSecretRevealOnce extends Component {
    // Blueprint P218: "لا يظهر مفتاح Secret كامل مرة أخرى بعد إنشائه"
    static template = "octa_hub_ui.SecretRevealOnce";
    static props = { secret: { type: String, optional: true }, alreadyConsumed: { type: Boolean, optional: true } };
}
