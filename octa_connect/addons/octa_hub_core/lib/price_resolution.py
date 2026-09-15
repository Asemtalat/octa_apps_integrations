"""
مصفوفة أسعار الفروع والتطبيقات (OC05-08، P0) — Gate E.

أولوية الحل صريحة (كما ينص البند حرفيًا):
    تخصيص الفرع+القناة  >  القناة  >  الفرع  >  الأساس
تُطبَّق فقط السجلات المتوافقة في العملة ونمط الضريبة. لا تحويل عملة أو
ضريبة صامت. null = "يورّث من المستوى الأعلى"، وصفر سعر فعلي شيء مختلف
تمامًا يحتاج سماحًا صريحًا (allow_zero=True) وإلا يُرفض كقيمة مشبوهة.

المبالغ Decimal دائمًا (لا float) — القسم 9 يشترط هذا صراحة للحسابات المالية.
"""
from __future__ import annotations

import dataclasses
from decimal import Decimal
from typing import Optional


class PriceConflictError(Exception):
    """تعديل متزامن على نسخة قديمة (version mismatch) — القبول ينص عليه حرفيًا."""
    def __init__(self, scope, stored_version, incoming_version):
        super().__init__(f"conflict at {scope}: stored version={stored_version}, incoming version={incoming_version}")
        self.scope = scope
        self.stored_version = stored_version
        self.incoming_version = incoming_version


class ZeroPriceNotAllowedError(Exception):
    def __init__(self, scope):
        super().__init__(f"zero price at {scope} requires explicit allow_zero=True")
        self.scope = scope


class CurrencyOrTaxMismatchError(Exception):
    def __init__(self, scope, reason):
        super().__init__(f"currency/tax mismatch at {scope}: {reason}")


@dataclasses.dataclass(frozen=True)
class PriceOverride:
    product_id: str
    branch_id: Optional[str]   # None = ينطبق على كل الفروع (مستوى القناة أو الأساس)
    channel_id: Optional[str]  # None = ينطبق على كل القنوات (مستوى الفرع أو الأساس)
    amount: Optional[Decimal]  # None = null صريح = "يرث من المستوى الأعلى"
    currency: str
    tax_inclusive: bool
    version: int
    source: str = "manual"
    allow_zero: bool = False

    def priority_rank(self) -> int:
        # أقل رقم = أعلى أولوية (يُفحص أولًا)
        if self.branch_id and self.channel_id:
            return 0  # تخصيص الفرع والقناة معًا
        if self.channel_id:
            return 1  # القناة فقط
        if self.branch_id:
            return 2  # الفرع فقط
        return 3      # الأساس


@dataclasses.dataclass
class ResolvedPrice:
    amount: Decimal
    currency: str
    tax_inclusive: bool
    origin_rank: int
    origin_source: str
    origin_version: int


def resolve_price(overrides: list[PriceOverride], branch_id: str, channel_id: str,
                   base_currency: str, base_tax_inclusive: bool) -> ResolvedPrice:
    """يحسم السعر الفعّال لفرع/قناة محددين وفق ترتيب الأولوية الصريح.

    يتجاهل صامتًا أي override بعملة أو نمط ضريبة مختلفين عن السياق المطلوب
    (بدل تحويل صامت) — لكنه لا يُخفي هذا: القيمة origin_source واضحة لمن
    يستدعي، والتجاهل نفسه سلوك موثق لا تحويل مختلق.
    """
    applicable = [
        o for o in overrides
        if (o.branch_id in (None, branch_id)) and (o.channel_id in (None, channel_id))
        and o.currency == base_currency and o.tax_inclusive == base_tax_inclusive
    ]
    if not applicable:
        raise LookupError(f"لا يوجد سعر قابل للتطبيق لـ (branch={branch_id}, channel={channel_id}) "
                           f"بعملة {base_currency} ونمط ضريبة {base_tax_inclusive}")

    # الأولوية: الأقل رقمًا يفوز؛ عند تعادل الرتبة، الأحدث إصدارًا يفوز
    best = min(applicable, key=lambda o: (o.priority_rank(), -o.version))

    if best.amount is None:
        # null صريح = "يرث" — نبحث عن أفضل مرشح آخر أدنى تخصيصًا يحمل قيمة فعلية
        fallback_candidates = [o for o in applicable if o.amount is not None and o is not best]
        if not fallback_candidates:
            raise LookupError(f"القيمة الوحيدة القابلة للتطبيق null (وراثة) بلا مصدر أعلى يحمل رقمًا فعليًا")
        best = min(fallback_candidates, key=lambda o: (o.priority_rank(), -o.version))

    if best.amount == 0 and not best.allow_zero:
        raise ZeroPriceNotAllowedError((branch_id, channel_id))

    return ResolvedPrice(
        amount=best.amount, currency=best.currency, tax_inclusive=best.tax_inclusive,
        origin_rank=best.priority_rank(), origin_source=best.source, origin_version=best.version,
    )


def check_no_overlapping_conflicting_periods(overrides: list[PriceOverride],
                                              valid_from: dict, valid_to: dict) -> None:
    """يمنع فترات صلاحية متداخلة متعارضة لنفس (product, branch, channel) — القبول
    ينص على هذا حرفيًا. valid_from/valid_to: قواميس {override: datetime}."""
    from itertools import combinations
    by_scope: dict = {}
    for o in overrides:
        key = (o.product_id, o.branch_id, o.channel_id)
        by_scope.setdefault(key, []).append(o)
    for scope, group in by_scope.items():
        for a, b in combinations(group, 2):
            a_from, a_to = valid_from.get(a), valid_to.get(a)
            b_from, b_to = valid_from.get(b), valid_to.get(b)
            if a_from is None or b_from is None:
                continue
            a_to = a_to or float("inf")
            b_to = b_to or float("inf")
            if a.amount != b.amount and a_from < b_to and b_from < a_to:
                raise ValueError(f"فترات متداخلة متعارضة لنفس النطاق {scope}: أسعار مختلفة في نفس الوقت")


# إصلاح بعد مراجعة عاشرة: القسم 6 يشترط صراحة اختبار "التقريب" ولم يكن أي
# منطق تقريب موجودًا في هذه الوحدة إطلاقًا. عدد الخانات العشرية بعد الفاصلة
# لكل عملة موثَّق صراحة (لا افتراض عالمي أن كل عملة لها خانتان — بعض
# العملات ليس لها كسور، وبعضها ثلاث خانات).
CURRENCY_MINOR_UNIT_EXPONENT = {
    "SAR": 2, "USD": 2, "EUR": 2, "AED": 2, "EGP": 2,
    "KWD": 3,  # الدينار الكويتي: 3 خانات عشرية، ليس 2 — استثناء حقيقي شائع
    "JPY": 0,  # الين الياباني: بلا كسور إطلاقًا
}


def round_to_currency_precision(amount: Decimal, currency: str) -> Decimal:
    """تقريب صريح بحسب دقة العملة الفعلية، لا افتراض عالمي بخانتين. يستخدم
    ROUND_HALF_UP (تقريب تجاري قياسي للمبالغ النقدية عند نقطة البيع)."""
    from decimal import ROUND_HALF_UP
    exponent = CURRENCY_MINOR_UNIT_EXPONENT.get(currency)
    if exponent is None:
        raise ValueError(f"دقة التقريب غير معروفة للعملة {currency} — يجب تسجيلها صراحة قبل التقريب")
    quant = Decimal(1).scaleb(-exponent) if exponent > 0 else Decimal(1)
    return amount.quantize(quant, rounding=ROUND_HALF_UP)
