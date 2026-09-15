"""اختبارات RUN فعليًا لتوسيع المطابقة (OC05-05)."""
import pytest
from external_mapping import (
    MappingKey, ExternalMapping, MappingStore, EntityType, MappingState,
    UnknownPaymentCodeError, same_external_id_different_connections_do_not_collide,
)


def test_same_external_id_across_two_connections_does_not_collide():
    """القبول حرفيًا: نفس external_id في اتصالين مختلفين لا يتصادم."""
    store = MappingStore()
    assert same_external_id_different_connections_do_not_collide(store, "t1", "EXT-SAME-ID") is True


def test_unknown_payment_code_raises_interpretable_error_not_silent_cash_conversion():
    """القبول حرفيًا: كود دفع غير معروف ينتج استثناء قابلًا للتفسير ولا
    يُحوَّل نقديًا افتراضيًا."""
    store = MappingStore()
    with pytest.raises(UnknownPaymentCodeError) as exc:
        store.resolve_payment_code("pos_x", "conn1", "t1", "UNKNOWN-CODE-99")
    assert "UNKNOWN-CODE-99" in str(exc.value)


def test_known_payment_code_resolves_correctly():
    store = MappingStore()
    key = MappingKey("t1", "pos_x", "conn1", EntityType.PAYMENT_METHOD, "CASH-01")
    store.upsert(ExternalMapping(key, internal_id="cash", mapping_version=1))
    result = store.resolve_payment_code("pos_x", "conn1", "t1", "CASH-01")
    assert result.internal_id == "cash"


def test_mapping_entity_types_are_distinct_scopes():
    """نفس external_id بنفس الاتصال لكن entity_type مختلف = مفاتيح منفصلة تمامًا."""
    store = MappingStore()
    tenant, system, conn = "t1", "pos_x", "conn1"
    product_key = MappingKey(tenant, system, conn, EntityType.PRODUCT, "ID-1")
    tag_key = MappingKey(tenant, system, conn, EntityType.TAG, "ID-1")
    store.upsert(ExternalMapping(product_key, internal_id="PRODUCT-INTERNAL", mapping_version=1))
    store.upsert(ExternalMapping(tag_key, internal_id="TAG-INTERNAL", mapping_version=1))
    assert store.resolve(product_key).internal_id == "PRODUCT-INTERNAL"
    assert store.resolve(tag_key).internal_id == "TAG-INTERNAL"


def test_branch_scoped_product_mapping_distinguishes_branches():
    """منتج نطاقه فرع محدد — نفس external_id بفرعين مختلفين لا يتصادم."""
    store = MappingStore()
    key_a = MappingKey("t1", "pos_x", "conn1", EntityType.PRODUCT, "SKU-1", branch_id="BR-A")
    key_b = MappingKey("t1", "pos_x", "conn1", EntityType.PRODUCT, "SKU-1", branch_id="BR-B")
    store.upsert(ExternalMapping(key_a, internal_id="PROD-A", mapping_version=1))
    store.upsert(ExternalMapping(key_b, internal_id="PROD-B", mapping_version=1))
    assert store.resolve(key_a).internal_id != store.resolve(key_b).internal_id


def test_conflicted_state_is_preserved_not_silently_overwritten():
    store = MappingStore()
    key = MappingKey("t1", "pos_x", "conn1", EntityType.MODIFIER, "MOD-1")
    conflicted = ExternalMapping(key, internal_id="MOD-INTERNAL", mapping_version=2, state=MappingState.CONFLICTED)
    store.upsert(conflicted)
    assert store.resolve(key).state == MappingState.CONFLICTED
