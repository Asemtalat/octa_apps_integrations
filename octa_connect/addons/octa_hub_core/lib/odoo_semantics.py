"""
دلالات Odoo الحقيقية المتحقَّق منها من المصدر (R07) — Gate تدقيق مستقل.

Odoo يحوّل أي قيمة Python None إلى False قبل وصولها لكود الموديل، لحقول
Datetime/Date/Char/Many2one الفارغة (`odoo/orm/fields.py::Field.convert_to_record`:
`return False if value is None else value`, مُتحقَّق فعليًا من مصدر Odoo 19
بتنزيل حقيقي لفرع 19.0). فحص `is None` على أي حقل Odoo فارغ **يفشل دائمًا
بصمت** (لأن القيمة False فعليًا، لا None) — bug حقيقي وُجد في
`invitation.py::preview_only` وأُصلح، موثَّق هنا بدالة مشتركة لمنع تكراره.
"""
from __future__ import annotations


def is_empty_odoo_field(value) -> bool:
    """الفحص الصحيح لحقل Odoo فارغ (Datetime/Date/Char/Many2one/إلخ) — يتعامل
    مع القيمة الفعلية (False) بدل افتراض None الذي لا يصل أبدًا لكود الموديل."""
    return not value  # False أو None أو '' أو 0 كلها "فارغة" بنفس المعنى هنا


def odoo_field_is_none_bug_example(value) -> bool:
    """يُبقي على النمط الخاطئ هنا فقط للتوثيق/الاختبار المقارن — **لا يُستخدم
    في أي كود إنتاجي**؛ يثبت الاختبار المرفق أنه يعطي نتيجة خاطئة دائمًا."""
    return value is None
