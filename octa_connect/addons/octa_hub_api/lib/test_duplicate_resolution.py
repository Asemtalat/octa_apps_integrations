"""اختبارات RUN فعليًا لمنطق حسم تعارض القيد الفريد (إصلاح بعد مراجعة V2)."""
from duplicate_resolution import (
    resolve_unique_violation, ConflictDecision, EXPECTED_ORDER_UNIQUE_CONSTRAINT_NAME,
)


def test_unrelated_constraint_is_rejected_not_treated_as_duplicate():
    """قيد مختلف تمامًا (FK/NOT NULL/CHECK) ليس تعارض تكرار طلب — يُرفض
    (يعني: يُعاد رفع الاستثناء الأصلي في الـcontroller، لا 200 مزيَّف)."""
    result = resolve_unique_violation(
        actual_constraint_name="some_other_table_some_fk_constraint",
        existing_record_found=False,
    )
    assert result.decision == ConflictDecision.REJECT_UNRELATED_CONSTRAINT


def test_correct_constraint_but_no_matching_record_is_unresolved_anomaly_not_fake_success():
    """السيناريو الذي أثبتته مراجعة V2 عمليًا ضد النسخة السابقة: القيد
    الصحيح انتُهك، لكن لا سجل مطابق — كان الكود القديم يُرجع 200 بـ
    order_id=None هنا بالضبط. يجب أن يكون 500 صريحًا الآن، لا نجاحًا مُختلَقًا."""
    result = resolve_unique_violation(
        actual_constraint_name=EXPECTED_ORDER_UNIQUE_CONSTRAINT_NAME,
        existing_record_found=False,
    )
    assert result.decision == ConflictDecision.UNRESOLVED_ANOMALY
    assert result.http_status == 500


def test_correct_constraint_with_matching_content_is_real_200():
    result = resolve_unique_violation(
        actual_constraint_name=EXPECTED_ORDER_UNIQUE_CONSTRAINT_NAME,
        existing_record_found=True, existing_hash="abc", incoming_hash="abc",
    )
    assert result.decision == ConflictDecision.DUPLICATE_SAME_PAYLOAD
    assert result.http_status == 200


def test_correct_constraint_with_different_content_is_409_conflict():
    """نفس المفتاح (external_order_id)، محتوى مختلف — تعارض موثّق، لا نجاح صامت."""
    result = resolve_unique_violation(
        actual_constraint_name=EXPECTED_ORDER_UNIQUE_CONSTRAINT_NAME,
        existing_record_found=True, existing_hash="abc", incoming_hash="xyz",
    )
    assert result.decision == ConflictDecision.CONFLICT_DIFFERENT_PAYLOAD
    assert result.http_status == 409


def test_none_constraint_name_is_treated_as_unrelated_not_matched_by_accident():
    """None لا يجب أن يُطابق EXPECTED_ORDER_UNIQUE_CONSTRAINT_NAME بالخطأ."""
    result = resolve_unique_violation(actual_constraint_name=None, existing_record_found=True,
                                       existing_hash="a", incoming_hash="a")
    assert result.decision == ConflictDecision.REJECT_UNRELATED_CONSTRAINT
