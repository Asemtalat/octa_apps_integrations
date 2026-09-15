"""
Catalog reconciliation core logic — Gate D (المرحلة الأولى، البوابة D).

هذا المنطق مستقل عن Odoo عمدًا (pure Python) حتى يمكن اختباره فعليًا
في أي بيئة بدون تشغيل Odoo/PostgreSQL. الموديول octa_hub_core يستدعي
هذه الدوال من داخل نموذج odoo (انظر addons/octa_hub_core/models/catalog_import.py)
بدل إعادة كتابة نفس القواعد مرتين.

القواعد الملزمة من الوثيقتين المرجعيتين:
- مفتاح الـ upsert = (tenant_id, branch_id, source_scope, source_type, external_id).
  SKU مساعد فقط عندما external_id غير متاح، وله حد تفرد صريح لكل مصدر.
- لا دمج بالاسم إطلاقًا (تشابه أسماء صنفين لا يعني أنهما نفس المنتج).
- إعادة استيراد نفس الدفعة عدة مرات لا تضاعف السجلات (idempotent upsert).
- عدم ظهور عنصر في دفعة جزئية لا يعني حذفه (soft: نعلّمه missing_this_batch
  فقط، لا نحذفه ولا نعطّله تلقائيًا).
- كل حقل له مصدر (source_of_truth) وإصدار (version)؛ التعارض يُكشف لا يُكتب
  فوق القيمة الصامتة.
- أسعار القنوات/الفروع مستقلة عن بعضها ولا "تُدمج" في رقم واحد.
"""
from __future__ import annotations

import dataclasses
import enum
import time
from typing import Optional


class ItemStatus(str, enum.Enum):
    NEW = "new"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    CONFLICT = "conflict"
    MISSING_THIS_BATCH = "missing_this_batch"


class ConflictReason(str, enum.Enum):
    SAME_KEY_DIFFERENT_STABLE_FIELD = "same_key_different_stable_field"
    FIELD_SOURCE_MISMATCH = "field_source_mismatch"
    DUPLICATE_SKU_DIFFERENT_EXTERNAL_ID = "duplicate_sku_different_external_id"


@dataclasses.dataclass(frozen=True)
class CatalogKey:
    """مفتاح upsert فريد. SKU ليس جزءًا من المفتاح الأساسي أبدًا."""

    tenant_id: str
    branch_id: str
    source_scope: str  # مثال: "pos:hayatradwa_main" أو "channel:hungerstation"
    source_type: str  # "item" | "modifier" | "category"
    external_id: str

    def as_tuple(self):
        return (self.tenant_id, self.branch_id, self.source_scope, self.source_type, self.external_id)


@dataclasses.dataclass
class CatalogRecord:
    key: CatalogKey
    sku: Optional[str]
    name_ar: str
    name_en: str
    price_minor_units: int  # integer minor units — لا float للمال أبدًا
    currency: str
    version: int
    payload: dict = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class ReconcileResultItem:
    key_tuple: tuple
    status: ItemStatus
    reason: Optional[ConflictReason] = None
    diff: Optional[dict] = None


@dataclasses.dataclass
class ImportBatchResult:
    batch_id: str
    started_at: float
    finished_at: float
    items: list  # list[ReconcileResultItem]

    def counts(self) -> dict:
        out = {s.value: 0 for s in ItemStatus}
        for it in self.items:
            out[it.status.value] += 1
        return out


class CatalogStore:
    """تمثيل بسيط لمخزن الكتالوج (staging + committed) في الذاكرة.

    في الإنتاج هذا يقابل جداول Odoo (octa.hub.catalog.item) لكن القواعد
    هنا مستقلة عن نوع التخزين، وهذا ما يجعلها قابلة للاختبار بدون Odoo.
    """

    def __init__(self):
        # key_tuple -> CatalogRecord (committed / معتمد)
        self._committed: dict[tuple, CatalogRecord] = {}
        # sku -> external_id لضبط تفرد SKU داخل نفس (tenant, branch, source_scope, source_type)
        self._sku_index: dict[tuple, str] = {}

    def get(self, key: CatalogKey) -> Optional[CatalogRecord]:
        return self._committed.get(key.as_tuple())

    def commit(self, record: CatalogRecord):
        self._committed[record.key.as_tuple()] = record
        if record.sku:
            sku_scope = (record.key.tenant_id, record.key.branch_id, record.key.source_scope, record.key.source_type, record.sku)
            self._sku_index[sku_scope] = record.key.external_id

    def sku_conflict(self, record: CatalogRecord) -> bool:
        if not record.sku:
            return False
        sku_scope = (record.key.tenant_id, record.key.branch_id, record.key.source_scope, record.key.source_type, record.sku)
        existing_external_id = self._sku_index.get(sku_scope)
        return existing_external_id is not None and existing_external_id != record.key.external_id

    def all_committed_keys_for_scope(self, tenant_id, branch_id, source_scope, source_type):
        return {
            k for k in self._committed
            if k[0] == tenant_id and k[1] == branch_id and k[2] == source_scope and k[3] == source_type
        }


def _record_changed(old: CatalogRecord, new: CatalogRecord) -> Optional[dict]:
    diff = {}
    for f in ("name_ar", "name_en", "price_minor_units", "currency", "sku"):
        old_v, new_v = getattr(old, f), getattr(new, f)
        if old_v != new_v:
            diff[f] = {"old": old_v, "new": new_v}
    return diff or None


def reconcile_batch(store: CatalogStore, batch_id: str, incoming: list[CatalogRecord],
                     tenant_id: str, branch_id: str, source_scope: str, source_type: str) -> ImportBatchResult:
    """يطبّق دفعة استيراد على الـ store بشكل idempotent وآمن للإعادة.

    - لا يحذف أي سجل غير موجود في الدفعة (يعلّمه MISSING_THIS_BATCH فقط).
    - لا يدمج بالاسم أبدًا — المطابقة فقط عبر external_id (source_scope+type).
    - يرصد تعارض SKU المكرر بمعرف خارجي مختلف بدل الدمج الصامت.
    """
    started = time.monotonic()
    results: list[ReconcileResultItem] = []
    seen_keys_this_batch = set()

    for rec in incoming:
        assert rec.key.tenant_id == tenant_id
        assert rec.key.branch_id == branch_id
        assert rec.key.source_scope == source_scope
        assert rec.key.source_type == source_type

        key_tuple = rec.key.as_tuple()
        seen_keys_this_batch.add(key_tuple)

        if store.sku_conflict(rec):
            results.append(ReconcileResultItem(
                key_tuple=key_tuple,
                status=ItemStatus.CONFLICT,
                reason=ConflictReason.DUPLICATE_SKU_DIFFERENT_EXTERNAL_ID,
            ))
            continue  # لا نكتب فوق حالة تعارض بصمت

        existing = store.get(rec.key)
        if existing is None:
            store.commit(rec)
            results.append(ReconcileResultItem(key_tuple=key_tuple, status=ItemStatus.NEW))
            continue

        if existing.version > rec.version:
            # نسخة الوارد أقدم من المعتمدة — لا نكتب فوقها صامتين
            results.append(ReconcileResultItem(
                key_tuple=key_tuple,
                status=ItemStatus.CONFLICT,
                reason=ConflictReason.SAME_KEY_DIFFERENT_STABLE_FIELD,
                diff={"stored_version": existing.version, "incoming_version": rec.version},
            ))
            continue

        diff = _record_changed(existing, rec)
        if diff is None:
            results.append(ReconcileResultItem(key_tuple=key_tuple, status=ItemStatus.UNCHANGED))
        else:
            store.commit(rec)
            results.append(ReconcileResultItem(key_tuple=key_tuple, status=ItemStatus.UPDATED, diff=diff))

    # عناصر معتمدة سابقًا ولم تظهر في هذه الدفعة الجزئية
    prior_keys = store.all_committed_keys_for_scope(tenant_id, branch_id, source_scope, source_type)
    for missing_key in prior_keys - seen_keys_this_batch:
        results.append(ReconcileResultItem(key_tuple=missing_key, status=ItemStatus.MISSING_THIS_BATCH))

    finished = time.monotonic()
    return ImportBatchResult(batch_id=batch_id, started_at=started, finished_at=finished, items=results)
