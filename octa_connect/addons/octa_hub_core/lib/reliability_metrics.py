"""
مؤشرات الموثوقية والتوقيت (OC05-17، P0) — Gate E.

يفصل زمن انتظار الطابور عن زمن معالجة Hub عن زمن انتظار الطرف عن زمن
القرار البشري — أربعة أزمنة مختلفة، لا رقم واحد مجمّع. البيانات الناقصة
لا تساوي صفرًا (القسم 10 يشترط هذا صراحة، وكان `transport_p95_seconds`
في `octa_hub_core/models/order.py::get_dashboard_metrics` يُعاد None بلا
حساب فعلي — هذا أول تنفيذ حقيقي للحساب الموعود).
"""
from __future__ import annotations

import dataclasses
import math


@dataclasses.dataclass
class TimingSample:
    order_id: str
    queue_wait_seconds: float | None       # None = البيانات غير متاحة، ليست صفرًا
    hub_processing_seconds: float | None
    external_wait_seconds: float | None
    human_decision_seconds: float | None    # None أيضًا لو القبول كان آليًا بحتًا
    is_automated_acceptance: bool = False
    is_scheduled_order: bool = False


@dataclasses.dataclass
class MetricResult:
    median: float | None
    p95: float | None
    p99: float | None
    sample_count: int
    missing_count: int
    completeness_ratio: float  # نسبة اكتمال أحداث القياس


def _percentile(sorted_values: list, pct: float) -> float:
    if not sorted_values:
        raise ValueError("لا عينات لحساب percentile عليها")
    k = (len(sorted_values) - 1) * pct
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_values[int(k)]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


def compute_metric(values: list) -> MetricResult:
    """values: قائمة float أو None. None يُستبعد من الحساب (لا يُحوَّل لصفر)
    لكنه يُحسب في completeness_ratio صراحة."""
    total = len(values)
    present = [v for v in values if v is not None]
    missing = total - len(present)
    if not present:
        return MetricResult(median=None, p95=None, p99=None, sample_count=0,
                             missing_count=missing, completeness_ratio=0.0)
    sorted_vals = sorted(present)
    return MetricResult(
        median=_percentile(sorted_vals, 0.5),
        p95=_percentile(sorted_vals, 0.95),
        p99=_percentile(sorted_vals, 0.99),
        sample_count=len(present),
        missing_count=missing,
        completeness_ratio=len(present) / total if total else 0.0,
    )


def hub_processing_metric(samples: list) -> MetricResult:
    """زمن معالجة Hub وحده — لا يتأثر ببطء الطرف الخارجي (القبول: العميل
    البطيء لا يغير قياس زمن Hub الداخلي، لأننا نقرأ حقلاً منفصلاً تمامًا)."""
    return compute_metric([s.hub_processing_seconds for s in samples])


def cashier_response_metric(samples: list) -> MetricResult:
    """استجابة الكاشير = قرار بشري فقط. القبول: قبول آلي لا يُحسب كاستجابة
    كاشير — نستبعد العينات الآلية تمامًا من هذا المؤشر بدل احتسابها كصفر."""
    human_only = [s.human_decision_seconds for s in samples if not s.is_automated_acceptance]
    return compute_metric(human_only)


def scheduled_wait_is_not_transport_delay(samples: list) -> list:
    """القبول: عرض الموعد لا يحسب انتظار الموعد كتأخير نقل. يُرجع فقط
    العينات غير المجدولة لحساب تأخير النقل — الطلبات المجدولة تُستبعد من
    هذا المؤشر تحديدًا، لا تُحسب بقيمة مضخّمة."""
    return [s for s in samples if not s.is_scheduled_order]
