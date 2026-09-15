# إصلاح بعد مراجعة مستقلة خارجية (R16)، مُتحقَّق من مصدر Odoo 19 الحقيقي
# (odoo/tests/loader.py::_get_tests_modules): اكتشاف اختبارات Odoo الفعلي
# يستورد حزمة `tests` عبر importlib ثم يبحث في `tests_mod.__dict__` عن
# submodules تبدأ بـ"test_" — وهذا **لا يحدث تلقائيًا لمجرد وجود الملفات**؛
# يتطلب أن يكون شيء ما قد استوردها فعليًا داخل __init__.py هذا. حذف هذا
# الملف (كإصلاح سابق لتعارض pytest، انظر F-TEST-01 في docs/audit-findings.md)
# كان يعني أن Odoo **لن يجد أي اختبار في هذا الموديول إطلاقًا** عند التثبيت
# الفعلي — إصلاح صحيح لمشكلة، تسبَّب في مشكلة مختلفة لم تُكتشف إلا بمراجعة
# مستقلة خارجية قرأت مصدر Odoo نفسه.
#
# آمن الآن لأن tools/run_all_tests.py يعزل كل مجموعة اختبار في subprocess
# منفصل تمامًا (لا يلمس هذا المجلد إطلاقًا ضمن الخمس مجموعات التي يشغّلها)
# — التعارض الأصلي كان فقط عند تشغيل مسارات من addons/octa_hub_core/lib
# وaddons/octa_hub_core/tests معًا في نفس استدعاء pytest واحد من الجذر،
# وهذا لم يعد يحدث.
from . import test_isolation
from . import test_invitation
from . import test_catalog
