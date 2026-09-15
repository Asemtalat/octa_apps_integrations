"""اختبارات RUN فعليًا بـfixtures بتوقيتات معروفة (كما ينص القبول حرفيًا)."""
from reliability_metrics import (
    TimingSample, compute_metric, hub_processing_metric, cashier_response_metric,
    scheduled_wait_is_not_transport_delay,
)


def test_known_fixture_median_and_p95():
    """fixture بأرقام معروفة يدويًا: median وp95 لـ [1,2,3,4,5,6,7,8,9,10]
    يجب أن يطابقا الحساب القياسي بالضبط."""
    values = list(range(1, 11))  # 1..10
    result = compute_metric([float(v) for v in values])
    assert result.median == 5.5
    assert result.sample_count == 10
    assert result.missing_count == 0
    assert result.completeness_ratio == 1.0


def test_missing_data_is_not_zero_and_tracked_in_completeness():
    """القبول حرفيًا: البيانات الناقصة لا تساوي صفرًا."""
    values = [10.0, None, 20.0, None, 30.0]
    result = compute_metric(values)
    assert result.sample_count == 3  # فقط القيم الموجودة
    assert result.missing_count == 2
    assert result.completeness_ratio == 0.6
    assert result.median == 20.0  # median الثلاثة الموجودة فقط، لا خمسة بصفرين


def test_all_missing_returns_none_not_zero():
    result = compute_metric([None, None, None])
    assert result.median is None
    assert result.p95 is None
    assert result.completeness_ratio == 0.0


def test_slow_external_client_does_not_change_hub_internal_measurement():
    """القبول حرفيًا: العميل البطيء لا يغير قياس زمن Hub الداخلي."""
    samples = [
        TimingSample("o1", queue_wait_seconds=0.1, hub_processing_seconds=0.05,
                     external_wait_seconds=30.0, human_decision_seconds=None),  # طرف خارجي بطيء جدًا
        TimingSample("o2", queue_wait_seconds=0.1, hub_processing_seconds=0.06,
                     external_wait_seconds=0.2, human_decision_seconds=None),   # طرف خارجي سريع
    ]
    result = hub_processing_metric(samples)
    assert result.median < 0.1  # زمن Hub نفسه صغير رغم أن external_wait لأحدهما كان 30 ثانية


def test_automated_acceptance_excluded_from_cashier_response_metric():
    """القبول حرفيًا: قبول آلي لا يُحسب كاستجابة كاشير."""
    samples = [
        TimingSample("o1", None, None, None, human_decision_seconds=5.0, is_automated_acceptance=False),
        TimingSample("o2", None, None, None, human_decision_seconds=0.01, is_automated_acceptance=True),  # آلي
    ]
    result = cashier_response_metric(samples)
    assert result.sample_count == 1  # العينة الآلية استُبعدت تمامًا، لم تُحسب حتى كصفر
    assert result.median == 5.0


def test_scheduled_order_wait_excluded_from_transport_delay():
    """القبول حرفيًا: عرض الموعد لا يحسب انتظار الموعد كتأخير نقل."""
    samples = [
        TimingSample("o1", queue_wait_seconds=0.1, hub_processing_seconds=0.1,
                     external_wait_seconds=0.1, human_decision_seconds=None, is_scheduled_order=False),
        TimingSample("o2", queue_wait_seconds=7200.0, hub_processing_seconds=0.1,  # ساعتان انتظار موعد
                     external_wait_seconds=0.1, human_decision_seconds=None, is_scheduled_order=True),
    ]
    non_scheduled = scheduled_wait_is_not_transport_delay(samples)
    assert len(non_scheduled) == 1
    assert non_scheduled[0].order_id == "o1"


def test_p95_and_p99_are_distinct_from_median_with_larger_sample():
    values = [float(v) for v in range(1, 101)]  # 1..100
    result = compute_metric(values)
    assert result.median != result.p95 != result.p99
    assert result.p95 < result.p99  # p99 دائمًا أعلى من p95 لتوزيع متزايد
    assert result.sample_count == 100
