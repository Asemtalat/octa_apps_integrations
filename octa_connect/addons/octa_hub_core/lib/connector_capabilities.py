"""
دليل الموصلات ومصفوفة القدرات (OC05-04، P0) — Gate E.

يفصل ConnectorDefinition (تعريف الموصل نفسه) عن MerchantConnection (اتصال
تاجر معيّن به) عن BranchChannelBinding (ربط فرع محدد بهذا الاتصال) — ثلاث
طبقات منفصلة، لا خلط. كل قدرة لها حالة صريحة: supported / unsupported /
not_verified — ولا يوجد "افتراض دعم" لقدرة لم تُعلَن.

هذا يوحّد ما كان قاموسًا منفصلًا وغير متوافق في simulator.py
(`DEMO_CONNECTOR_CAPABILITIES` بمفاتيح نصية مختلفة: menu_sync، price_sync،
availability_sync، branch_pause) — كان قاموسًا ثابتًا بلا أي دالة إنفاذ
فعلية، وبمفردات مختلفة تمامًا عن هذا الملف رغم أنهما يمثلان **نفس
المفهوم**. اكتُشف هذا التعارض بمراجعة عاشرة مخصصة لفحص تناقض العقود بين
الموديولات. أُصلح بتوحيد المفردة هنا فقط؛ simulator.py يستورد من هذا
الملف الآن بدل تعريف مفرداته الخاصة (راجع audit-findings.md#F-CONTRACT-01).
"""
from __future__ import annotations

import dataclasses
import enum


class CapabilityStatus(str, enum.Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    NOT_VERIFIED = "not_verified"


class Capability(str, enum.Enum):
    ORDERS = "orders"
    CANCEL = "cancel"
    STATUS_UPDATES = "status_updates"
    MENU = "menu"
    PRICES = "prices"
    AVAILABILITY = "availability"
    PAUSE = "pause"
    SCHEDULING = "scheduling"
    QUERY = "query"
    IDEMPOTENCY = "idempotency"
    RECONCILIATION = "reconciliation"


class UnsupportedCapabilityError(Exception):
    """القبول حرفيًا: قدرة غير مدعومة تُرفض بالخادم ولا تتحول إلى نجاح صامت."""
    def __init__(self, connector_code, capability):
        super().__init__(f"الموصل {connector_code} لا يدعم القدرة {capability.value} — العملية مرفوضة صراحة")
        self.connector_code = connector_code
        self.capability = capability


@dataclasses.dataclass(frozen=True)
class ConnectorDefinition:
    """تعريف الموصل نفسه — مشترك بين كل التجار الذين يستخدمونه (يُعاد
    استخدامه دون تفريع الكود لكل تاجر، كما ينص البند)."""
    connector_code: str
    contract_version: str
    capabilities: dict  # Capability -> CapabilityStatus


@dataclasses.dataclass
class MerchantConnection:
    """اتصال تاجر محدد بهذا التعريف — منفصل عن التعريف العام."""
    connection_id: str
    tenant_id: str
    connector: ConnectorDefinition
    is_sandbox: bool
    authorized: bool = False


@dataclasses.dataclass
class BranchChannelBinding:
    """ربط فرع محدد باتصال تاجر معيّن — الطبقة الثالثة، منفصلة أيضًا."""
    branch_id: str
    connection: MerchantConnection
    active: bool = True


def enforce_capability(connection: MerchantConnection, capability: Capability) -> None:
    """يُستدعى قبل أي فعل حسّاس (نشر أسعار، جدولة، إلخ). يرفع
    UnsupportedCapabilityError لو القدرة unsupported. not_verified يُسمح
    به مع تحذير ضمني (القدرة قد تعمل لكن لم تُختبر) — القرار هنا: not_verified
    ليست unsupported، لكنها ليست ضمانًا أيضًا؛ الاستدعاء لا يُمنع، والمسؤولية
    على الطبقة الأعلى أن تعرض هذا الفارق للمستخدم صراحة (ليس هنا).
    """
    status = connection.connector.capabilities.get(capability, CapabilityStatus.UNSUPPORTED)
    if status == CapabilityStatus.UNSUPPORTED:
        raise UnsupportedCapabilityError(connection.connector.connector_code, capability)


def reject_production_key_in_sandbox_env(connection: MerchantConnection, key_looks_like_production: bool) -> None:
    """القبول حرفيًا: بيئة اختبار لا تقبل مفاتيح إنتاج بالخطأ."""
    if connection.is_sandbox and key_looks_like_production:
        raise ValueError(
            f"اتصال {connection.connection_id} في بيئة sandbox لكن المفتاح المُدخل يبدو مفتاح إنتاج — مرفوض"
        )


def two_merchants_same_connector_definition_do_not_mix_credentials(
        conn_a: MerchantConnection, conn_b: MerchantConnection) -> bool:
    """القبول حرفيًا: توصيل تاجرين بنفس تعريف الموصل لا يخلط معرفاتهما أو
    اعتماداتهما — يثبت أن كل MerchantConnection مستقل رغم مشاركة نفس
    ConnectorDefinition."""
    same_definition = conn_a.connector is conn_b.connector or conn_a.connector.connector_code == conn_b.connector.connector_code
    different_connections = conn_a.connection_id != conn_b.connection_id and conn_a.tenant_id != conn_b.tenant_id
    return same_definition and different_connections
