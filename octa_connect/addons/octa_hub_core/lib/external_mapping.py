"""
توسيع المطابقة (OC05-05، P0) — Gate E.

يعمم مفهوم CatalogKey (في reconcile.py، محصور بالكتالوج فقط) إلى كل أنواع
الكيانات المطلوبة: الفرع، المنتج، مجموعة الإضافات، الإضافة، البراند، طريقة
الدفع، نوع الطلب، الوسوم. حدود التفرد بحسب المصدر — external_id وحده ليس
كافيًا (نفس external_id في اتصالين مختلفين لا يتصادم).
"""
from __future__ import annotations

import dataclasses
import enum


class EntityType(str, enum.Enum):
    BRANCH = "branch"
    PRODUCT = "product"
    MODIFIER_GROUP = "modifier_group"
    MODIFIER = "modifier"
    BRAND = "brand"
    PAYMENT_METHOD = "payment_method"
    ORDER_TYPE = "order_type"
    TAG = "tag"


class MappingState(str, enum.Enum):
    ACTIVE = "active"
    PENDING = "pending"
    CONFLICTED = "conflicted"


class UnknownPaymentCodeError(Exception):
    """كود دفع غير معروف ينتج استثناء قابلًا للتفسير — لا يُحوَّل نقديًا
    افتراضيًا (القبول ينص عليه حرفيًا)."""
    def __init__(self, source_system, external_code):
        super().__init__(
            f"كود دفع غير معروف من {source_system}: {external_code!r} — "
            f"يحتاج مطابقة صريحة قبل أي معالجة مالية، لا افتراض تلقائي"
        )


@dataclasses.dataclass(frozen=True)
class MappingKey:
    """مفتاح تفرد صريح — النطاق (tenant/source_connection) جزء من المفتاح،
    وليس external_id وحده. هذا هو ما يمنع تصادم نفس external_id في اتصالين
    مختلفين."""
    tenant_id: str
    source_system: str
    source_connection: str
    entity_type: EntityType
    external_id: str
    branch_id: str | None = None  # بعض الكيانات (مثال: منتج) نطاقها فرع محدد


@dataclasses.dataclass
class ExternalMapping:
    key: MappingKey
    internal_id: str
    mapping_version: int
    state: MappingState = MappingState.ACTIVE


class MappingStore:
    def __init__(self):
        self._by_key: dict = {}

    def upsert(self, mapping: ExternalMapping) -> ExternalMapping:
        self._by_key[mapping.key] = mapping
        return mapping

    def resolve(self, key: MappingKey) -> ExternalMapping | None:
        return self._by_key.get(key)

    def resolve_payment_code(self, source_system: str, source_connection: str,
                              tenant_id: str, external_code: str) -> ExternalMapping:
        key = MappingKey(tenant_id, source_system, source_connection,
                          EntityType.PAYMENT_METHOD, external_code)
        mapping = self.resolve(key)
        if mapping is None:
            raise UnknownPaymentCodeError(source_system, external_code)
        return mapping


def same_external_id_different_connections_do_not_collide(store: MappingStore,
                                                            tenant_id: str, external_id: str) -> bool:
    """يثبت أن نفس external_id عبر source_connection مختلفة يُخزَّن كسجلين
    منفصلين تمامًا، لا تصادم — يُستخدم في الاختبار للتحقق العملي."""
    m1 = ExternalMapping(
        MappingKey(tenant_id, "system_a", "conn_1", EntityType.PRODUCT, external_id),
        internal_id="INTERNAL-1", mapping_version=1,
    )
    m2 = ExternalMapping(
        MappingKey(tenant_id, "system_a", "conn_2", EntityType.PRODUCT, external_id),
        internal_id="INTERNAL-2", mapping_version=1,
    )
    store.upsert(m1)
    store.upsert(m2)
    r1 = store.resolve(m1.key)
    r2 = store.resolve(m2.key)
    return r1.internal_id == "INTERNAL-1" and r2.internal_id == "INTERNAL-2" and r1.internal_id != r2.internal_id
