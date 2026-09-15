"""اختبارات RUN فعليًا لقاعدة منع الهيئات المزدوجة."""
import pytest
from authority_context import would_violate_single_authority, check_single_authority_or_raise, DualAuthorityError


def test_first_membership_ever_is_fine():
    assert would_violate_single_authority(set(), "merchant") is False


def test_second_membership_same_authority_is_fine():
    """محاسب يخدم عميلين مختلفين — نفس party_type، لا اتحاد هيئات."""
    assert would_violate_single_authority({"merchant"}, "merchant") is False


def test_adding_partner_authority_while_merchant_active_is_rejected():
    assert would_violate_single_authority({"merchant"}, "partner") is True


def test_adding_octatech_authority_while_partner_active_is_rejected():
    assert would_violate_single_authority({"partner"}, "octatech") is True


def test_raise_helper_actually_raises_with_useful_context():
    with pytest.raises(DualAuthorityError) as exc:
        check_single_authority_or_raise(42, {"merchant"}, "octatech")
    assert exc.value.user_id == 42
    assert exc.value.new_party_type == "octatech"


def test_raise_helper_does_not_raise_when_safe():
    check_single_authority_or_raise(42, {"merchant"}, "merchant")  # لا استثناء
    check_single_authority_or_raise(42, set(), "partner")  # لا استثناء


def test_same_role_twice_within_authority_is_allowed_multi_org_accountant():
    """محاسب يخدم عميلين مختلفين بنفس الدور — لا يسبب OR-widening، مسموح صراحة."""
    from authority_context import would_violate_single_role_within_authority
    assert would_violate_single_role_within_authority({"merchant_accountant"}, "merchant_accountant") is False


def test_owner_and_branch_manager_together_is_rejected_prevents_or_widening():
    """هذا بالضبط الخطر الذي اكتُشف: owner + branch_manager معًا كانا
    سيسببان OR-widening (رؤية العميل كله بدل الفرع المحدد فقط)."""
    from authority_context import (
        would_violate_single_role_within_authority, check_single_role_within_authority_or_raise,
        MixedRoleWithinAuthorityError,
    )
    assert would_violate_single_role_within_authority({"merchant_owner"}, "merchant_branch_manager") is True
    import pytest
    with pytest.raises(MixedRoleWithinAuthorityError):
        check_single_role_within_authority_or_raise(42, "merchant", {"merchant_owner"}, "merchant_branch_manager")


def test_octatech_roles_stay_separated_too():
    """يعمم على أوكتاتيك أيضًا — يعزز نفس مبدأ القسم 6 الأصلي (أدوار منفصلة
    عمدًا، لا مشرف واحد يجمعها)."""
    from authority_context import would_violate_single_role_within_authority
    assert would_violate_single_role_within_authority({"octatech_security"}, "octatech_identity_admin") is True


def test_first_role_ever_is_always_fine():
    from authority_context import would_violate_single_role_within_authority
    assert would_violate_single_role_within_authority(set(), "merchant_owner") is False
