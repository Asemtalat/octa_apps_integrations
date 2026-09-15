"""
قواعد الإضافات (OC05-10، P0) — Gate E.

يفصل عدد الخيارات المختلفة (كم صنف إضافة مختلف اختير) عن كمية الخيار نفسه
(كم مرة كُرِّر نفس الخيار) — البند ينص على هذا الفصل صراحة. الاختيارات
الافتراضية (preselected) يجب أن تُحقق القيود من البداية.
"""
from __future__ import annotations

import dataclasses


class InvalidModifierGroupError(Exception):
    pass


class ModifierSelectionError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class Modifier:
    modifier_id: str
    source_id: str
    price_minor_units: int
    preselected: bool = False
    allow_repeat: bool = False


@dataclasses.dataclass(frozen=True)
class ModifierGroup:
    group_id: str
    min_select: int
    max_select: int
    mandatory: bool
    allow_repeat: bool  # يمكن اختيار نفس modifier أكثر من مرة داخل هذه المجموعة
    modifiers: tuple

    def __post_init__(self):
        # القبول: قيمة min أكبر من max مرفوضة — يُفحص فور الإنشاء، لا عند
        # أول محاولة اختيار فقط.
        if self.min_select > self.max_select:
            raise InvalidModifierGroupError(
                f"group {self.group_id}: min_select ({self.min_select}) > max_select ({self.max_select})"
            )
        if self.mandatory and self.min_select < 1:
            raise InvalidModifierGroupError(
                f"group {self.group_id}: mandatory group must have min_select >= 1"
            )

    def default_selection(self) -> list[str]:
        """الاختيارات الافتراضية (preselected) — يجب أن تحقق القيود ولا
        تفرض إضافة غير متاحة (modifiers غير الموجودة في المجموعة)."""
        return [m.modifier_id for m in self.modifiers if m.preselected]


@dataclasses.dataclass(frozen=True)
class Selection:
    modifier_id: str
    quantity: int = 1


def validate_selection(group: ModifierGroup, selections: list) -> None:
    """يرفع ModifierSelectionError إن كان الاختيار مخالفًا لقيود المجموعة.

    عدد الخيارات المختلفة = len(selections) (عدد الأصناف الفريدة المختارة).
    كمية الخيار = selection.quantity (مرات تكرار نفس الصنف) — منفصلة تمامًا
    عن عدد الأصناف المختلفة، كما ينص البند صراحة.
    """
    valid_ids = {m.modifier_id for m in group.modifiers}
    distinct_count = len(selections)

    for sel in selections:
        if sel.modifier_id not in valid_ids:
            raise ModifierSelectionError(f"modifier {sel.modifier_id} غير موجود في المجموعة {group.group_id}")
        modifier = next(m for m in group.modifiers if m.modifier_id == sel.modifier_id)
        if sel.quantity > 1 and not modifier.allow_repeat and not group.allow_repeat:
            raise ModifierSelectionError(
                f"modifier {sel.modifier_id} لا يسمح بالتكرار (allow_repeat=False) لكن الكمية {sel.quantity}"
            )

    if group.mandatory and distinct_count == 0:
        raise ModifierSelectionError(f"group {group.group_id} إلزامية ولم يُختر منها شيء")

    if distinct_count < group.min_select:
        raise ModifierSelectionError(
            f"group {group.group_id}: اختير {distinct_count} أقل من الحد الأدنى {group.min_select}"
        )
    if distinct_count > group.max_select:
        raise ModifierSelectionError(
            f"group {group.group_id}: اختير {distinct_count} أكثر من الحد الأقصى {group.max_select}"
        )


def compute_selection_total_minor_units(selections: list, group: ModifierGroup) -> int:
    """السعر = سعر كل خيار × كميته، ليس × عدد الأصناف المختلفة — الكمية
    والعدد مفهومان منفصلان يجب ألا يختلطا في الحساب أيضًا."""
    by_id = {m.modifier_id: m for m in group.modifiers}
    return sum(by_id[s.modifier_id].price_minor_units * s.quantity for s in selections)


def channel_supports_repeat_or_reject(group: ModifierGroup, channel_supports_repeat: bool) -> None:
    """قناة لا تدعم تكرار الإضافة تُمنع قبل النشر أو تستخدم تحويلًا موثقًا
    معتمدًا؛ لا إسقاط صامت — القبول ينص على هذا حرفيًا."""
    if group.allow_repeat and not channel_supports_repeat:
        raise ModifierSelectionError(
            f"group {group.group_id} يسمح بتكرار الإضافة لكن القناة المستهدفة لا تدعمه — "
            f"يُمنع النشر لهذه القناة صراحة، لا إسقاط صامت للقيد"
        )
