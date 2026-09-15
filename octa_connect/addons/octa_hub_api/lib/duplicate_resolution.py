"""
منطق حسم تعارض القيد الفريد (مستخرج من api_controller.py ليكون قابلًا
للاختبار الفعلي) — Gate B، إصلاح بعد مراجعة V2 المستقلة.

سبب الفصل: `psycopg2.errors.UniqueViolation.diag` هو slot للقراءة فقط على
مستوى C، مرتبط بحالة اتصال libpq حقيقية — **لا يمكن تلفيقه في اختبار معزول
بلا PostgreSQL فعلي** (تحقَّقت من هذا فعليًا: `object.__setattr__` نفسها
تُرفض). لذلك يُفصَل استخراج `e.diag.constraint_name` (وهذا الاستخراج نفسه
يبقى NOT RUN/NOT VERIFIED هنا) عن **القرار** المبني على تلك القيمة (وهذا
القرار نصّي بحت، قابل للاختبار الكامل بمعزل عن psycopg2/Odoo).
"""
from __future__ import annotations

import dataclasses
import enum


class ConflictDecision(str, enum.Enum):
    REJECT_UNRELATED_CONSTRAINT = "reject_unrelated_constraint"  # ليس تعارض تكرار طلب أصلًا — يُعاد رفعه
    UNRESOLVED_ANOMALY = "unresolved_anomaly"                     # القيد الصحيح، لكن لا سجل مطابق — 500
    DUPLICATE_SAME_PAYLOAD = "duplicate_same_payload"             # القيد الصحيح + محتوى مطابق — 200 حقيقي
    CONFLICT_DIFFERENT_PAYLOAD = "conflict_different_payload"     # القيد الصحيح + محتوى مختلف — 409


@dataclasses.dataclass(frozen=True)
class ConflictResolution:
    decision: ConflictDecision
    http_status: int


EXPECTED_ORDER_UNIQUE_CONSTRAINT_NAME = "octa_hub_order_uniq_org_conn_external_order"
"""مُتحقَّق من الصيغة الحقيقية لتسمية القيد في Odoo 19
(odoo/orm/table_objects.py::TableObject.full_name: '{model._table}_{self.name}'،
حيث self.name = اسم سمة الصنف بلا الشرطة السفلية الأولى) — للنموذج
octa.hub.order (الجدول octa_hub_order) وسمة القيد `_uniq_org_conn_external_order`."""


def resolve_unique_violation(actual_constraint_name: str | None, existing_record_found: bool,
                              existing_hash: str | None = None, incoming_hash: str | None = None,
                              expected_constraint_name: str = EXPECTED_ORDER_UNIQUE_CONSTRAINT_NAME) -> ConflictResolution:
    """يحسم ماذا يفعل الـcontroller بعد `psycopg2.errors.UniqueViolation`.

    القاعدة: لا نجاح بلا سجل حقيقي مطابق. قيد غير متوقَّع يُعاد رفعه (ليس
    خطأ تكرار طلب أصلًا). القيد المتوقَّع بلا سجل = حالة شاذة حقيقية، لا
    تكرار عادي — 500 صريح، لا 200 مزيَّف (هذا بالضبط ما أثبتته مراجعة V2
    المستقلة عمليًا ضد النسخة السابقة).
    """
    if actual_constraint_name != expected_constraint_name:
        return ConflictResolution(ConflictDecision.REJECT_UNRELATED_CONSTRAINT, 0)  # 0 = يُعاد رفع الاستثناء، لا رد HTTP
    if not existing_record_found:
        return ConflictResolution(ConflictDecision.UNRESOLVED_ANOMALY, 500)
    if existing_hash == incoming_hash:
        return ConflictResolution(ConflictDecision.DUPLICATE_SAME_PAYLOAD, 200)
    return ConflictResolution(ConflictDecision.CONFLICT_DIFFERENT_PAYLOAD, 409)
