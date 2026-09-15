"""اختبارات RUN فعليًا لمصفوفة أسعار الفروع والتطبيقات (OC05-08)."""
from decimal import Decimal
import pytest
from price_resolution import (
    PriceOverride, resolve_price, ZeroPriceNotAllowedError, PriceConflictError,
    check_no_overlapping_conflicting_periods, round_to_currency_precision,
)


def test_exact_spec_example_liver_product_five_prices():
    """مطابق حرفيًا لمثال القبول في OC05-08: منتج كبدة واحد بسعر فرع 10
    وقناة X 12 وقناة Y 14 وهنقرستيشن 15 ونينجا 9 ريالات — منتج واحد، خمس
    نقاط سعر منفصلة، لا خمس منتجات."""
    overrides = [
        PriceOverride("LIVER", branch_id=None, channel_id=None, amount=Decimal("10"), currency="SAR", tax_inclusive=True, version=1, source="base"),
        PriceOverride("LIVER", branch_id="BR-MAIN", channel_id=None, amount=Decimal("10"), currency="SAR", tax_inclusive=True, version=1, source="branch"),
        PriceOverride("LIVER", branch_id=None, channel_id="X", amount=Decimal("12"), currency="SAR", tax_inclusive=True, version=1, source="channel"),
        PriceOverride("LIVER", branch_id=None, channel_id="Y", amount=Decimal("14"), currency="SAR", tax_inclusive=True, version=1, source="channel"),
        PriceOverride("LIVER", branch_id=None, channel_id="HUNGERSTATION_DEMO", amount=Decimal("15"), currency="SAR", tax_inclusive=True, version=1, source="channel"),
        PriceOverride("LIVER", branch_id=None, channel_id="NINJA_DEMO", amount=Decimal("9"), currency="SAR", tax_inclusive=True, version=1, source="channel"),
    ]
    assert resolve_price(overrides, "BR-MAIN", "X", "SAR", True).amount == Decimal("12")
    assert resolve_price(overrides, "BR-MAIN", "Y", "SAR", True).amount == Decimal("14")
    assert resolve_price(overrides, "BR-MAIN", "HUNGERSTATION_DEMO", "SAR", True).amount == Decimal("15")
    assert resolve_price(overrides, "BR-MAIN", "NINJA_DEMO", "SAR", True).amount == Decimal("9")
    # قناة بلا override خاص بها تنحدر إلى override الفرع (10)
    assert resolve_price(overrides, "BR-MAIN", "SOME_OTHER_CHANNEL", "SAR", True).amount == Decimal("10")


def test_branch_and_channel_specific_override_wins_over_channel_only():
    overrides = [
        PriceOverride("P1", None, None, Decimal("100"), "SAR", True, version=1, source="base"),
        PriceOverride("P1", None, "CH1", Decimal("120"), "SAR", True, version=1, source="channel"),
        PriceOverride("P1", "BR1", "CH1", Decimal("150"), "SAR", True, version=1, source="branch_channel"),
    ]
    result = resolve_price(overrides, "BR1", "CH1", "SAR", True)
    assert result.amount == Decimal("150")
    assert result.origin_rank == 0


def test_removing_override_falls_back_to_inheritance_not_deletion_of_product():
    """إزالة override تعيد التوريث دون حذف المنتج — نمذجناها بعدم وجود سجل
    override أصلًا لهذا النطاق، فينحدر تلقائيًا للمستوى الأعلى."""
    overrides = [
        PriceOverride("P1", None, None, Decimal("100"), "SAR", True, version=1, source="base"),
        PriceOverride("P1", "BR1", None, Decimal("90"), "SAR", True, version=1, source="branch"),
    ]
    # بعد "إزالة" override الفرع (لم يعد موجودًا في القائمة) يرث الأساس
    overrides_after_removal = [o for o in overrides if o.source != "branch"]
    result = resolve_price(overrides_after_removal, "BR1", "ANY_CHANNEL", "SAR", True)
    assert result.amount == Decimal("100")
    assert result.origin_source == "base"


def test_zero_price_requires_explicit_allow_zero():
    overrides = [PriceOverride("P1", "BR1", "CH1", Decimal("0"), "SAR", True, version=1, source="manual", allow_zero=False)]
    with pytest.raises(ZeroPriceNotAllowedError):
        resolve_price(overrides, "BR1", "CH1", "SAR", True)


def test_zero_price_allowed_when_explicit():
    overrides = [PriceOverride("P1", "BR1", "CH1", Decimal("0"), "SAR", True, version=1, source="manual", allow_zero=True)]
    result = resolve_price(overrides, "BR1", "CH1", "SAR", True)
    assert result.amount == Decimal("0")


def test_currency_mismatch_is_not_silently_converted():
    """لا تحويل عملة صامت — override بعملة مختلفة يُتجاهل تمامًا، لا يُحوَّل."""
    overrides = [
        PriceOverride("P1", None, None, Decimal("100"), "SAR", True, version=1, source="base"),
        PriceOverride("P1", "BR1", "CH1", Decimal("30"), "USD", True, version=1, source="manual"),  # عملة مختلفة
    ]
    result = resolve_price(overrides, "BR1", "CH1", "SAR", True)
    assert result.amount == Decimal("100")  # الـUSD override تجوهل تمامًا، لا تحويل
    assert result.currency == "SAR"


def test_no_applicable_price_raises_lookup_error_not_zero():
    with pytest.raises(LookupError):
        resolve_price([], "BR1", "CH1", "SAR", True)


def test_overlapping_conflicting_periods_are_rejected():
    o1 = PriceOverride("P1", "BR1", "CH1", Decimal("10"), "SAR", True, version=1)
    o2 = PriceOverride("P1", "BR1", "CH1", Decimal("20"), "SAR", True, version=2)
    valid_from = {o1: 100, o2: 150}
    valid_to = {o1: 200, o2: None}  # يتداخلان بين 150-200 بسعرين مختلفين
    with pytest.raises(ValueError):
        check_no_overlapping_conflicting_periods([o1, o2], valid_from, valid_to)


def test_non_overlapping_periods_are_fine():
    o1 = PriceOverride("P1", "BR1", "CH1", Decimal("10"), "SAR", True, version=1)
    o2 = PriceOverride("P1", "BR1", "CH1", Decimal("20"), "SAR", True, version=2)
    valid_from = {o1: 100, o2: 200}
    valid_to = {o1: 200, o2: None}
    check_no_overlapping_conflicting_periods([o1, o2], valid_from, valid_to)  # لا استثناء


def test_rounding_sar_two_decimals_half_up():
    """القبول حرفيًا: التقريب يُختبر — SAR له خانتان عشريتان، HALF_UP قياسي تجاريًا."""
    assert round_to_currency_precision(Decimal("12.345"), "SAR") == Decimal("12.35")
    assert round_to_currency_precision(Decimal("12.344"), "SAR") == Decimal("12.34")
    assert round_to_currency_precision(Decimal("12.005"), "SAR") == Decimal("12.01")  # HALF_UP لا HALF_EVEN


def test_rounding_kwd_three_decimals_not_two():
    """القبول حرفيًا: لا افتراض عالمي أن كل عملة خانتان — الدينار الكويتي 3."""
    assert round_to_currency_precision(Decimal("12.3456"), "KWD") == Decimal("12.346")


def test_rounding_jpy_zero_decimals():
    """الين الياباني بلا كسور إطلاقًا — تقريب لعدد صحيح."""
    assert round_to_currency_precision(Decimal("1250.6"), "JPY") == Decimal("1251")


def test_rounding_unknown_currency_raises_not_silently_assumes_two_decimals():
    """عملة غير مسجَّلة تُرفض صراحة، لا تُقرَّب بافتراض خطأ صامت."""
    with pytest.raises(ValueError):
        round_to_currency_precision(Decimal("10.555"), "XYZ")
