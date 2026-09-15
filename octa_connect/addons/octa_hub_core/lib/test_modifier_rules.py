"""اختبارات RUN فعليًا لقواعد الإضافات (OC05-10)."""
import pytest
from modifier_rules import (
    Modifier, ModifierGroup, Selection, validate_selection,
    compute_selection_total_minor_units, channel_supports_repeat_or_reject,
    InvalidModifierGroupError, ModifierSelectionError,
)


def test_min_greater_than_max_rejected_at_creation():
    """القبول حرفيًا: قيمة min أكبر من max مرفوضة."""
    with pytest.raises(InvalidModifierGroupError):
        ModifierGroup("g1", min_select=3, max_select=1, mandatory=False, allow_repeat=False, modifiers=())


def test_mandatory_single_size_does_not_accept_two_sizes():
    """القبول حرفيًا: حجم واحد إجباري لا يقبل حجمين."""
    group = ModifierGroup("size", min_select=1, max_select=1, mandatory=True, allow_repeat=False, modifiers=(
        Modifier("small", "SRC-S", 0), Modifier("large", "SRC-L", 500),
    ))
    with pytest.raises(ModifierSelectionError):
        validate_selection(group, [Selection("small"), Selection("large")])
    validate_selection(group, [Selection("small")])  # لا استثناء


def test_repeatable_modifier_counts_quantity_and_price_correctly():
    """القبول حرفيًا: إضافة مسموح تكرارها مرتين تحسب الكمية والسعر صحيحين."""
    group = ModifierGroup("sauce", min_select=0, max_select=3, mandatory=False, allow_repeat=True, modifiers=(
        Modifier("extra_cheese", "SRC-C", 200, allow_repeat=True),
    ))
    selections = [Selection("extra_cheese", quantity=2)]
    validate_selection(group, selections)  # لا استثناء
    assert compute_selection_total_minor_units(selections, group) == 400  # 200 × 2، ليس 200 × 1


def test_distinct_count_separate_from_quantity():
    """اختيار صنف واحد بكمية 3 هو distinct_count=1 لا 3 — منفصلان تمامًا."""
    group = ModifierGroup("g", min_select=1, max_select=1, mandatory=True, allow_repeat=True, modifiers=(
        Modifier("x", "SRC-X", 100, allow_repeat=True),
    ))
    validate_selection(group, [Selection("x", quantity=3)])  # distinct=1 يجتاز max_select=1 رغم الكمية 3


def test_non_repeatable_modifier_with_quantity_2_is_rejected():
    group = ModifierGroup("g", min_select=0, max_select=2, mandatory=False, allow_repeat=False, modifiers=(
        Modifier("x", "SRC-X", 100, allow_repeat=False),
    ))
    with pytest.raises(ModifierSelectionError):
        validate_selection(group, [Selection("x", quantity=2)])


def test_default_selection_does_not_force_unavailable_modifier():
    group = ModifierGroup("g", min_select=0, max_select=1, mandatory=False, allow_repeat=False, modifiers=(
        Modifier("a", "SRC-A", 0, preselected=True),
        Modifier("b", "SRC-B", 100, preselected=False),
    ))
    assert group.default_selection() == ["a"]


def test_mandatory_group_empty_selection_rejected():
    group = ModifierGroup("g", min_select=1, max_select=1, mandatory=True, allow_repeat=False, modifiers=(
        Modifier("a", "SRC-A", 0),
    ))
    with pytest.raises(ModifierSelectionError):
        validate_selection(group, [])


def test_channel_not_supporting_repeat_blocks_publish_not_silent_drop():
    group = ModifierGroup("g", min_select=0, max_select=3, mandatory=False, allow_repeat=True, modifiers=(
        Modifier("x", "SRC-X", 100, allow_repeat=True),
    ))
    with pytest.raises(ModifierSelectionError):
        channel_supports_repeat_or_reject(group, channel_supports_repeat=False)
    channel_supports_repeat_or_reject(group, channel_supports_repeat=True)  # لا استثناء


def test_unknown_modifier_id_in_selection_rejected():
    group = ModifierGroup("g", min_select=0, max_select=1, mandatory=False, allow_repeat=False, modifiers=(
        Modifier("a", "SRC-A", 0),
    ))
    with pytest.raises(ModifierSelectionError):
        validate_selection(group, [Selection("does-not-exist")])
