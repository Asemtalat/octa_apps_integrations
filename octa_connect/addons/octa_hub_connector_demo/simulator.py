"""
octa_hub_connector_demo — محاكي تطبيق توصيل مُعلن كاختبار (القسم 5).
لا يسجل أي قناة حقيقية جاهزة للإنتاج؛ اسمه في كل مكان "demo" ويُمنع
استخدامه كإثبات اعتماد قناة فعلية (القسم 14 وقسم 17 من ملف التنفيذ).

يوفر:
- توليد أحداث طلب صناعية (Fixtures) بعلامات زمنية معروفة لقياس التوقيتات.
- حقن تكرار/تأخير/إلغاء قبل الإنشاء/429/انتهاء توكن — كما يشترط القسم 14.
- قدرات معلنة عبر عقد Gate E الموحَّد (`octa_hub_core/lib/connector_capabilities.py`).

إصلاح بعد مراجعة عاشرة (فحص تعارض العقود بين الموديولات): كانت هذه الوحدة
تُعرِّف `ConnectorCapability`/`DEMO_CONNECTOR_CAPABILITIES` بمفردات خاصة بها
(menu_sync، price_sync، availability_sync، branch_pause) **مختلفة تمامًا**
عن `Capability`/`CapabilityStatus` في `lib/connector_capabilities.py`
(menu، prices، availability، pause) رغم أنهما يمثلان نفس المفهوم بالضبط —
لو حاول أي كود لاحق ربط الاثنين لكان يفشل صامتًا (مفتاح غير موجود = يُقرأ
كـunsupported افتراضيًا حتى لو كان مدعومًا فعليًا بالاسم القديم). أُصلح
بتوحيد المفردة: هذا الملف يستورد من lib الآن، لا يُعرِّف نسخته الخاصة.
"""
from __future__ import annotations

import dataclasses
import os
import sys
import time
from typing import Optional

_LIB_DIR = os.path.join(os.path.dirname(__file__), "..", "octa_hub_core", "lib")
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)
from connector_capabilities import (  # noqa: E402
    Capability, CapabilityStatus, ConnectorDefinition, MerchantConnection,
    enforce_capability, UnsupportedCapabilityError,
)

CONTRACT_VERSION = "octa-connect-order-v1"

# إعلان صريح وحيد المصدر الآن — القدرات غير المدعومة تُعرض كذلك دون زر
# قابل للنقر في الواجهة (القسم 13/16)، وتُرفض فعليًا عبر enforce_capability
# (وليس إعلانًا شكليًا بلا إنفاذ كما كانت النسخة القديمة).
DEMO_CONNECTOR_DEFINITION = ConnectorDefinition(
    connector_code="demo",
    contract_version=CONTRACT_VERSION,
    capabilities={
        Capability.ORDERS: CapabilityStatus.SUPPORTED,
        Capability.CANCEL: CapabilityStatus.SUPPORTED,
        Capability.MENU: CapabilityStatus.SUPPORTED,
        Capability.PRICES: CapabilityStatus.SUPPORTED,
        Capability.AVAILABILITY: CapabilityStatus.NOT_VERIFIED,
        Capability.PAUSE: CapabilityStatus.UNSUPPORTED,          # غير مدعوم في هذا المحاكي حاليًا
        Capability.RECONCILIATION: CapabilityStatus.UNSUPPORTED,  # مؤجل لمرحلة لاحقة (القسم 16)
        Capability.IDEMPOTENCY: CapabilityStatus.SUPPORTED,
        Capability.STATUS_UPDATES: CapabilityStatus.SUPPORTED,
        Capability.SCHEDULING: CapabilityStatus.UNSUPPORTED,
        Capability.QUERY: CapabilityStatus.SUPPORTED,
    },
)


@dataclasses.dataclass
class SimulatedOrderEvent:
    event_id: str
    external_order_id: str
    tenant_id: str
    branch_id: str
    connection_id: str
    items: list
    total_minor_units: int
    currency: str
    source_created_at: float  # وقت المصدر (لو توفر) — أساس مؤشرات الأداء


class RateLimitedError(Exception):
    """يحاكي 429 من التطبيق."""
    def __init__(self, retry_after_seconds: float):
        super().__init__(f"429 rate limited, retry_after={retry_after_seconds}")
        self.retry_after_seconds = retry_after_seconds


class TokenExpiredError(Exception):
    """يحاكي انتهاء صلاحية توكن الاتصال."""


class ConnectorDemoSimulator:
    """محاكي حالة قابلة للضبط: يمكن جعل الطلب التالي يفشل بـ429 أو
    بتوكن منتهٍ، أو يصل مكررًا، أو يصل إلغاؤه قبل حدث إنشائه.
    """

    def __init__(self):
        self._next_failure: Optional[str] = None  # "429" | "token_expired" | None
        self._retry_after = 2.0

    def force_next_failure(self, kind: str, retry_after: float = 2.0):
        assert kind in ("429", "token_expired")
        self._next_failure = kind
        self._retry_after = retry_after

    def emit(self, event: SimulatedOrderEvent) -> SimulatedOrderEvent:
        if self._next_failure == "429":
            self._next_failure = None
            raise RateLimitedError(self._retry_after)
        if self._next_failure == "token_expired":
            self._next_failure = None
            raise TokenExpiredError()
        return event

    def emit_duplicate(self, event: SimulatedOrderEvent, times: int) -> list:
        """نفس event_id يصل عدة مرات (تكرار webhook حقيقي)."""
        return [event for _ in range(times)]
