"""اختبارات RUN فعليًا تثبت bug حقيقي (R07) والإصلاح الصحيح له."""
from odoo_semantics import is_empty_odoo_field, odoo_field_is_none_bug_example


def test_false_is_correctly_treated_as_empty():
    """False هي القيمة الفعلية التي يُرجعها Odoo لحقل فارغ (مُتحقَّق من
    Field.convert_to_record في مصدر Odoo 19 الحقيقي) — يجب أن تُعامَل كفارغة."""
    assert is_empty_odoo_field(False) is True


def test_none_is_also_treated_as_empty_defensively():
    assert is_empty_odoo_field(None) is True


def test_real_datetime_value_is_not_empty():
    assert is_empty_odoo_field("2026-01-01 00:00:00") is False


def test_demonstrate_the_actual_bug_pattern_always_fails_for_false():
    """يثبت أن النمط الخاطئ (`value is None`) كان سيفشل دائمًا مقابل القيمة
    الفعلية (False) التي يُرجعها Odoo — هذا بالضبط ما اكتُشف في
    invitation.py::preview_only قبل الإصلاح."""
    actual_odoo_value_for_empty_field = False  # مُتحقَّق من المصدر، ليس افتراضًا
    assert odoo_field_is_none_bug_example(actual_odoo_value_for_empty_field) is False  # الـbug: كان يُتوقَّع True
    assert is_empty_odoo_field(actual_odoo_value_for_empty_field) is True  # الإصلاح الصحيح
