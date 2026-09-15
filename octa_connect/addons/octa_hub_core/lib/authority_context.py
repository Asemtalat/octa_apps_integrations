"""
منع اتحاد امتيازات الهيئات المختلفة (القسم 6: "الهيئات ثلاث: التاجر،
الشريك التقني، أوكتاتيك... ليست مجرد قوائم مختلفة لنفس الصلاحيات" و"لا
تجمع امتيازات هيئات مختلفة عند تعدد العضوية").

اكتُشف بإعادة قراءة membership.py سطرًا سطرًا: كان يوجد حقل
`active_membership_id` وتعليق يقول إنه "يُفحص صراحة في كل طلب سيرفري بدل
اتحاد كل عضويات المستخدم" — لكن لا شيء في المستودع كله كان يقرأ هذا الحقل
فعليًا (لا record_rules.xml ولا has_permission). يعني الادعاء في التعليق
كان **غير صحيح عمليًا**. الإصلاح الجذري المختار هنا: منع وجود عضويات فعالة
من أكثر من party_type واحد لنفس المستخدم من الأساس (قيد صارم)، بدل الاعتماد
على "سياق نشط" لم يكن أحد يفحصه فعليًا. هذا يجعل خطر الاتحاد بين الهيئات
الثلاث مستحيلاً بنيويًا، لا مجرد "مُفترَض ألا يحدث".

ملاحظة صادقة: هذا لا يمنع اتحاد الرؤية بين عضويتين من **نفس** party_type
(مثال: محاسب يخدم عميلين مختلفين بنفس الدور) — القسم 6 يتكلم عن "هيئات
مختلفة" تحديدًا، وهذه الحالة (تعدد عملاء بنفس الهيئة) قرار منتج مفتوح غير
محسوم، موثّق في docs/decisions.md.
"""
from __future__ import annotations


class DualAuthorityError(Exception):
    def __init__(self, user_id, existing_party_types, new_party_type):
        super().__init__(
            f"user {user_id} already holds active membership(s) of type(s) "
            f"{existing_party_types}; cannot also hold {new_party_type!r} — "
            f"pick a single authority per user (Phase_1.md §6)"
        )
        self.user_id = user_id
        self.existing_party_types = existing_party_types
        self.new_party_type = new_party_type


def would_violate_single_authority(existing_active_party_types: set[str], new_party_type: str) -> bool:
    """existing_active_party_types: مجموعة party_type لعضويات المستخدم
    الفعالة الحالية (بدون العضوية الجديدة/المعدَّلة نفسها). يُرجع True إن
    كانت إضافة new_party_type ستُدخل هيئة ثانية مختلفة للمستخدم نفسه.
    """
    others = existing_active_party_types - {new_party_type}
    return bool(others)


def check_single_authority_or_raise(user_id, existing_active_party_types: set[str], new_party_type: str) -> None:
    if would_violate_single_authority(existing_active_party_types, new_party_type):
        raise DualAuthorityError(user_id, existing_active_party_types, new_party_type)


class MixedRoleWithinAuthorityError(Exception):
    """إصلاح بعد مراجعة V2 المستقلة: خطر حقيقي اكتُشف أثناء تصحيح خطأ
    توثيقي عن دلالات Odoo (OR/AND بين قواعد الصلاحيات) — تحقَّقت من مصدر
    Odoo 19 الحقيقي (odoo/addons/base/models/ir_rule.py::_compute_domain)
    أن **كل** قواعد المجموعات (بصرف النظر عن كونها لنفس المجموعة أو
    لمجموعات مختلفة) تُدمَج بـOR. القيد أعلاه (check_single_authority_or_raise)
    يمنع فقط تعدد الهيئات الثلاث الكبرى (تاجر/شريك/أوكتاتيك)، لكن **لا يمنع
    تعدد الأدوار داخل نفس الهيئة** — مستخدم بعضوية merchant_owner
    وmerchant_branch_manager معًا لنفس العميل كان سيرى نتيجة OR الأوسع بين
    قاعدة "كل فروع العميل" (owner) وقاعدة "فروعه المحددة فقط" (branch_manager)
    — أي يرى العميل كله بدل فرعه، رغم أن أحد أدواره مقيَّد صراحة بفرع واحد.
    """
    def __init__(self, user_id, party_type, existing_roles, new_role):
        super().__init__(
            f"user {user_id} already holds role(s) {existing_roles} within authority "
            f"{party_type!r}; cannot also hold {new_role!r} — mixing roles within the "
            f"same authority causes unintended OR-widening in Odoo record rules "
            f"(verified against odoo/addons/base/models/ir_rule.py)"
        )
        self.user_id = user_id
        self.party_type = party_type
        self.existing_roles = existing_roles
        self.new_role = new_role


def would_violate_single_role_within_authority(existing_active_roles_same_party_type: set[str],
                                                 new_role_code: str) -> bool:
    """existing_active_roles_same_party_type: أدوار المستخدم الفعالة
    الحالية **ضمن نفس party_type فقط** (لا عبر الهيئات — ذاك القيد أعلاه
    منفصل ومُختبَر مسبقًا). يُرجع True فقط لو الدور الجديد **مختلف** عن كل
    الأدوار القائمة — نفس الدور مكرر (محاسب يخدم عميلين بنفس الدور) **مسموح
    صراحة** ولا يُعتبر انتهاكًا، لأنه لا يسبب OR-widening (نفس قاعدة ir.rule
    تنطبق بنفس النطاق على الاثنين، لا تعارض اتساع)."""
    others = existing_active_roles_same_party_type - {new_role_code}
    return bool(others)


def check_single_role_within_authority_or_raise(user_id, party_type: str,
                                                  existing_active_roles_same_party_type: set[str],
                                                  new_role_code: str) -> None:
    if would_violate_single_role_within_authority(existing_active_roles_same_party_type, new_role_code):
        raise MixedRoleWithinAuthorityError(user_id, party_type, existing_active_roles_same_party_type, new_role_code)
