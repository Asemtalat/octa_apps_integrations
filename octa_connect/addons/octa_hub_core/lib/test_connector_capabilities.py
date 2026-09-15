"""اختبارات RUN فعليًا لدليل الموصلات ومصفوفة القدرات (OC05-04)."""
import pytest
from connector_capabilities import (
    ConnectorDefinition, MerchantConnection, Capability, CapabilityStatus,
    enforce_capability, UnsupportedCapabilityError, reject_production_key_in_sandbox_env,
    two_merchants_same_connector_definition_do_not_mix_credentials,
)


def _demo_connector(pause_status=CapabilityStatus.UNSUPPORTED):
    return ConnectorDefinition(
        connector_code="demo", contract_version="v1",
        capabilities={
            Capability.ORDERS: CapabilityStatus.SUPPORTED,
            Capability.CANCEL: CapabilityStatus.SUPPORTED,
            Capability.MENU: CapabilityStatus.SUPPORTED,
            Capability.PRICES: CapabilityStatus.SUPPORTED,
            Capability.AVAILABILITY: CapabilityStatus.NOT_VERIFIED,
            Capability.PAUSE: pause_status,
            Capability.SCHEDULING: CapabilityStatus.UNSUPPORTED,
        },
    )


def test_unsupported_capability_is_rejected_server_side_not_silent_success():
    """القبول حرفيًا: قدرة غير مدعومة تُرفض بالخادم ولا تتحول إلى نجاح صامت."""
    conn = MerchantConnection("c1", "t1", _demo_connector(), is_sandbox=True, authorized=True)
    with pytest.raises(UnsupportedCapabilityError) as exc:
        enforce_capability(conn, Capability.SCHEDULING)
    assert exc.value.capability == Capability.SCHEDULING


def test_supported_capability_passes():
    conn = MerchantConnection("c1", "t1", _demo_connector(), is_sandbox=True, authorized=True)
    enforce_capability(conn, Capability.ORDERS)  # لا استثناء


def test_not_verified_capability_is_allowed_through_not_treated_as_unsupported():
    """not_verified ليست unsupported — الفرق بين الاثنين مقصود ومختلف."""
    conn = MerchantConnection("c1", "t1", _demo_connector(), is_sandbox=True, authorized=True)
    enforce_capability(conn, Capability.AVAILABILITY)  # لا يُرفض، رغم أنه غير مؤكد


def test_capability_missing_from_dict_defaults_to_unsupported_not_supported():
    """قدرة لم تُذكر إطلاقًا في القاموس = unsupported افتراضيًا (deny-by-default)،
    وليست مسموحة بالخطأ."""
    connector = ConnectorDefinition("demo", "v1", capabilities={})  # قاموس فارغ تمامًا
    conn = MerchantConnection("c1", "t1", connector, is_sandbox=True)
    with pytest.raises(UnsupportedCapabilityError):
        enforce_capability(conn, Capability.ORDERS)


def test_sandbox_env_rejects_production_looking_key():
    """القبول حرفيًا: بيئة اختبار لا تقبل مفاتيح إنتاج بالخطأ."""
    conn = MerchantConnection("c1", "t1", _demo_connector(), is_sandbox=True)
    with pytest.raises(ValueError):
        reject_production_key_in_sandbox_env(conn, key_looks_like_production=True)
    reject_production_key_in_sandbox_env(conn, key_looks_like_production=False)  # لا استثناء


def test_two_merchants_same_connector_do_not_mix_credentials():
    """القبول حرفيًا: توصيل تاجرين بنفس تعريف الموصل لا يخلط معرفاتهما."""
    shared_definition = _demo_connector()
    conn_a = MerchantConnection("conn-a", "tenant-a", shared_definition, is_sandbox=True)
    conn_b = MerchantConnection("conn-b", "tenant-b", shared_definition, is_sandbox=True)
    assert two_merchants_same_connector_definition_do_not_mix_credentials(conn_a, conn_b) is True
    # نفس الاتصال بالضبط (نفس id ونفس tenant) ليس "تاجرين مختلفين"
    assert two_merchants_same_connector_definition_do_not_mix_credentials(conn_a, conn_a) is False
