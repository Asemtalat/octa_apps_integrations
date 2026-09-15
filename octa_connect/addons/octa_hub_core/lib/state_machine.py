"""
قواعد انتقال الحالة ("الحركات") — Blueprint P240: "نستخدم رقم إصدار حين
يتوفر وقواعد انتقال مع الأحداث الأصلية حين لا يتوفر" + Phase_1.md §9:
"تحديث قديم لا يعيد الطلب لحالة تحضير".

هذا لم يكن موجودًا في أي تسليم سابق: order.py لم يكن يمنع أي انتقال حالة
غير منطقي (مثال: من "مكتمل" إلى "جديد" مباشرة، أو من "ملغي" إلى "قيد
التحضير"). أي كود كان يقدر يكتب أي قيمة حالة مباشرة بلا تحقق. هذا أول
تنفيذ فعلي pure-Python لجدول الانتقالات المسموحة، ليُختبر بمعزل عن Odoo
ثم يُستدعى من `octa_hub_core/models/order.py::write()`.
"""
from __future__ import annotations


class IllegalTransitionError(Exception):
    def __init__(self, field, old_state, new_state):
        super().__init__(f"illegal transition on {field}: {old_state} -> {new_state}")
        self.field = field
        self.old_state = old_state
        self.new_state = new_state


# النقل: محفوظ → ينتظر الإرسال → قيد الإرسال → (تأكد التسجيل | مجهول |
# يحتاج تدخلًا). "مجهول" و"يحتاج تدخلًا" حالتان يمكن الخروج منهما بإعادة
# محاولة أو تدخل يدوي، لكن لا رجوع لـ"محفوظ" (القسم 9).
TRANSPORT_TRANSITIONS = {
    "stored": {"pending_dispatch", "dispatching"},
    "pending_dispatch": {"dispatching", "unknown"},
    "dispatching": {"registered_confirmed", "unknown", "needs_intervention"},
    "unknown": {"registered_confirmed", "needs_intervention", "dispatching"},  # إعادة محاولة بعد unknown مسموحة
    "needs_intervention": {"registered_confirmed", "dispatching"},  # بعد تدخل يدوي فقط
    "registered_confirmed": set(),  # حالة نهائية — لا رجوع منها إطلاقًا
}

# التجاري: جديد → مقبول/مرفوض → قيد التحضير → جاهز → مكتمل، وملغي من أي
# حالة غير نهائية. "مكتمل" و"ملغي" نهائيتان — لا رجوع (القسم 9/§14: "تحديث
# قديم بعد حالة نهائية لا يعيد الطلب لحالة تحضير").
COMMERCIAL_TRANSITIONS = {
    "new": {"accepted", "rejected", "cancelled"},
    "accepted": {"in_preparation", "cancelled"},
    "rejected": set(),          # نهائية
    "in_preparation": {"ready", "cancelled"},
    "ready": {"completed", "cancelled"},
    "completed": set(),         # نهائية — لا رجوع لأي حالة أخرى
    "cancelled": set(),         # نهائية
}

FINAL_COMMERCIAL_STATES = {"rejected", "completed", "cancelled"}
FINAL_TRANSPORT_STATES = {"registered_confirmed"}


def validate_transport_transition(old_state: str, new_state: str) -> None:
    if old_state == new_state:
        return  # لا تغيير — مسموح دائمًا (idempotent write)
    allowed = TRANSPORT_TRANSITIONS.get(old_state, set())
    if new_state not in allowed:
        raise IllegalTransitionError("transport_state", old_state, new_state)


def validate_commercial_transition(old_state: str, new_state: str, is_stale_event: bool = False) -> None:
    """is_stale_event=True يمثل تحديثًا وصل بترتيب زمني قديم (out-of-order) —
    هذا يُرفض بصمت (يُتجاهل) لا بخطأ، حسب Phase_1.md §9. الاستدعاء العادي
    (event بترتيب صحيح لكن حالة غير منطقية) يرفع IllegalTransitionError.
    """
    if old_state == new_state:
        return
    if is_stale_event and old_state in FINAL_COMMERCIAL_STATES:
        raise IllegalTransitionError("commercial_state", old_state, new_state)
    allowed = COMMERCIAL_TRANSITIONS.get(old_state, set())
    if new_state not in allowed:
        raise IllegalTransitionError("commercial_state", old_state, new_state)


def is_final_commercial_state(state: str) -> bool:
    return state in FINAL_COMMERCIAL_STATES


def is_final_transport_state(state: str) -> bool:
    return state in FINAL_TRANSPORT_STATES


# إصلاح بعد مراجعة بوابة هنقرستيشن (القسم 3.3): "ادعم تصحيح الحالة من
# التطبيق بعد حالة نهائية عند وجود حدث موثوق، مع توضيح التصحيح ومنع تكرار
# الأثر على الـPOS". هذا **يختلف جوهريًا** عن `validate_commercial_transition`
# أعلاه — ذاك يمنع أي خروج من حالة نهائية (يعامل كل شيء كـ"تحديث قديم
# محتمل"). المطلوب هنا مسار **منفصل تمامًا**، لا يخفّف القيد الأصلي (الذي
# يبقى صحيحًا لأي تحديث عادي/تلقائي)، بل يفتح استثناءً **صريحًا وموثَّقًا**
# فقط حين يوجد قرار بشري/نظامي واعٍ بأن هذا تصحيح لا تحديث عادي متأخر.
ALL_COMMERCIAL_STATES = set(COMMERCIAL_TRANSITIONS.keys())


class CorrectionRecord:
    """نتيجة تصحيح — كائن منفصل تمامًا عن التحديث العادي، ليسهل على المستدعي
    (order.py) تخزينه بوسم "تصحيح" صريح في سجل الأحداث، لا كتحديث حالة عادي
    يبدو وكأنه انتقال طبيعي عبر TRANSITIONS العادية."""

    def __init__(self, old_state, new_state, reason, suppress_pos_side_effect=True):
        self.old_state = old_state
        self.new_state = new_state
        self.reason = reason
        self.suppress_pos_side_effect = suppress_pos_side_effect
        self.is_correction = True  # علامة صريحة — لا يمكن الخلط مع انتقال عادي


def apply_trusted_correction(old_state: str, new_state: str, reason: str) -> CorrectionRecord:
    """يسمح بالخروج من حالة نهائية **فقط** عبر هذا المسار الصريح — لا عبر
    `validate_commercial_transition` العادية (تبقى ترفض أي خروج من حالة
    نهائية كما هي، بلا تخفيف). وجود `reason` غير فارغ هو إشارة "الموثوقية"
    الدنيا المطلوبة هنا — حدث تلقائي عادي لا يصل أبدًا بسبب بشري مكتوب،
    فغيابه يكفي لرفض المحاولة كتصحيح غير موثَّق. `suppress_pos_side_effect`
    ثابتة True دائمًا لهذا المسار تحديدًا — يمنع بنيويًا (لا مجرد تعليق)
    أي كود مستدعٍ من الافتراض أن تصحيحًا يعيد تشغيل أثر POS، لأن الكائن
    المُرجَع نفسه يحمل هذه العلامة صراحة ليستخدمها المستدعي.

    NOT VERIFIED: الربط الفعلي بـorder.py (تخزين CorrectionRecord في سجل
    أحداث منفصل موسوم "تصحيح") لم يُبنَ بعد في هذه الجولة — هذه الدالة
    تأسيس المنطق المُختبَر فقط، لا الربط الكامل بالنموذج.
    """
    if not reason or not reason.strip():
        raise ValueError("تصحيح حالة بعد نهائية يتطلب سببًا صريحًا موثَّقًا — لا يُقبَل بلا سبب")
    if new_state not in ALL_COMMERCIAL_STATES:
        raise ValueError(f"حالة غير معروفة: {new_state!r}")
    if old_state not in FINAL_COMMERCIAL_STATES:
        raise ValueError(
            f"هذا المسار مخصص للتصحيح بعد حالة نهائية فقط — {old_state!r} ليست نهائية، "
            f"استخدم validate_commercial_transition العادية"
        )
    return CorrectionRecord(old_state, new_state, reason.strip())


def ordinary_update_after_final_is_still_rejected(old_state: str, new_state: str) -> None:
    """يثبت صراحة أن القيد الأصلي **لم يُخفَّف** — أي محاولة عادية (بلا
    المرور عبر apply_trusted_correction) للخروج من حالة نهائية لا تزال
    تُرفض بالضبط كما كانت. هذه الدالة توثيقية/اختبارية بحتة."""
    validate_commercial_transition(old_state, new_state)
