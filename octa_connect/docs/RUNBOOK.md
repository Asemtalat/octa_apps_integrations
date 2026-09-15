# RUNBOOK — الإعداد والتشغيل والترقية وإعادة الاختبار

## 1. تشغيل ما لا يحتاج Odoo (يعمل الآن، في أي بيئة Python 3.10+)

**الطريقة الموصى بها — أمر واحد يشغّل كل شيء بأمان:**
```bash
python3 -m pip install pytest pyyaml
python3 tools/run_all_tests.py
```
هذا يشغّل كل مجموعة في عملية منفصلة (subprocess) عمدًا — تشغيلها جميعًا في
جلسة `pytest` واحدة من الجذر **يفشل** بتعارض استيراد حقيقي بين `lib/`
و`addons/*/__init__.py` (تفاصيل كاملة في `docs/audit-findings.md#F-TEST-01`).
لا تحاول دمجهم في استدعاء pytest واحد.

**أو يدويًا، مجموعة بمجموعة (نفس ما يفعله السكربت أعلاه داخليًا):**
```bash
cd tools/catalog_reconcile        && python3 -m pytest -v   # 10 اختبارات
cd ../../addons/octa_hub_api/tests && python3 -m pytest -v   # 8 اختبارات
cd ../../../tools/mock_pos          && python3 -m pytest -v   # 7 اختبارات
cd ../../addons/octa_hub_connector_demo/tests && python3 -m pytest -v  # 3 اختبارات
cd ../../octa_hub_core/lib          && python3 -m pytest -v   # 29 اختبارًا
```
النتيجة المتوقعة: 57 passed، صفر failed.

تشغيل خدمة POS التجريبية يدويًا (للتجربة اليدوية):
```bash
cd tools/mock_pos && python3 mock_pos_service.py
# → mock_pos listening on http://127.0.0.1:8765
```

فحص تباين الألوان:
```bash
python3 tools/design_check/contrast_check.py
```

## 2. تثبيت Odoo 19 + PostgreSQL (مطلوب لكل ما تبقى)

هذا القسم **لم يُشغَّل في هذه الجلسة** (لا صلاحيات root في بيئة التطوير).
الخطوات التالية موثّقة من المعرفة العامة بـOdoo، **غير مُتحقَّق منها هنا**:

```bash
# على جهاز/سيرفر بصلاحيات root:
sudo apt-get update
sudo apt-get install -y postgresql postgresql-contrib python3-pip \
    build-essential libxml2-dev libxslt1-dev libldap2-dev libsasl2-dev \
    libtiff5-dev libjpeg8-dev libopenjp2-7-dev zlib1g-dev

sudo -u postgres createuser -s $(whoami)
createdb octa_test

git clone https://github.com/odoo/odoo.git --branch 19.0 --depth 1
python3 -m pip install -r odoo/requirements.txt --break-system-packages
```

## 3. تثبيت موديولات Octa Connect على Odoo

```bash
python3 odoo/odoo-bin -d octa_test \
  --addons-path=odoo/addons,./addons \
  -i octa_hub_core,octa_hub_api,octa_hub_connector_demo,octa_hub_ui \
  --stop-after-init
```

**نقاط فشل متوقعة يجب فحصها فورًا عند أول تشغيل حقيقي** (بصدق، لأنها
NOT VERIFIED في هذه الجلسة):
- استيراد `ir.model.access.csv`: تأكد أن `model_id:id` بلا بادئة موديول يُحل صحيحًا ضمن نفس الموديول.
- `record_rules.xml`: تحقق فعليًا هل قواعد مجموعات مختلفة تتحد بـOR كما هو موثّق في تعليقات الملف — هذا افتراض غير مؤكد.
- `models/membership.py::_check_single_authority_per_user`: يستورد من `../lib` عبر `sys.path.insert` — تأكد أن هذا يعمل مع آلية تحميل موديولات Odoo (قد يحتاج تحويل `lib/` إلى حزمة فرعية داخل الموديول بدل مسار نسبي هش).
- نفس الملاحظة تنطبق على كل استيراد `sys.path.insert(0, "../lib")` في: `order.py` (مرتين: create/write)، `branch.py`، `activation_wizard.py`، `api_controller.py`.

## 4. تشغيل اختبارات Odoo الحقيقية

```bash
python3 odoo/odoo-bin -d octa_test \
  --addons-path=odoo/addons,./addons \
  -i octa_hub_core --test-enable --stop-after-init \
  --log-level=test 2>&1 | tee odoo_test_output.log
```
راجع `odoo_test_output.log` لـ`test_isolation.py` و`test_invitation.py`.
**لا تُصلح اختبارًا بتخفيف تأكيداته لإخفاء فشل حقيقي** — إن فشل، شخّص
السبب الجذري أولاً (راجع قائمة "نقاط فشل متوقعة" أعلاه كبداية).

## 5. إعادة الاختبار بعد أي تعديل لاحق

أي تعديل على `lib/*.py` يستوجب إعادة تشغيل مجموعته المقابلة فورًا (الأوامر
في القسم 1). أي تعديل على `models/*.py` يستوجب إعادة القسمين 3 و4 كاملين.
لا تعتبر نجاح `py_compile` وحده كافيًا أبدًا.

## 6. الترقية (Upgrade) على قاعدة بيانات قائمة

```bash
python3 odoo/odoo-bin -d octa_test \
  --addons-path=odoo/addons,./addons \
  -u octa_hub_core,octa_hub_api,octa_hub_connector_demo,octa_hub_ui \
  --stop-after-init
```
**غير مُختبَر في هذه الجلسة إطلاقًا** — لا قاعدة بيانات قائمة للترقية منها.

## 7. نقاط اعتمادية Odoo الأساسية وسببها

| الاعتمادية | السبب |
|---|---|
| `base` | كل نماذج Odoo الأساسية (`res.users`, `res.currency`, `res.country`) |
| `web` | أصول OWL/QWeb للواجهة (`octa_hub_ui`) |
| `mail` | `mail.thread` في `organization.py` لسجل النشاط/التتبع |

**لا اعتماد على** `point_of_sale`, `sale`, `stock`, `account` — تحقَّق منه
فعليًا بـ`grep` على كل `__manifest__.py` (صفر نتائج، موثّق في audit-findings.md).

## 8. استكشاف أعطال شائعة متوقعة (استباقي، NOT VERIFIED)

| العرض | السبب المحتمل | الإجراء |
|---|---|---|
| فشل تثبيت `octa_hub_core` بخطأ ACL | `model_id:id` بلا بادئة | جرّب `octa_hub_core.model_octa_hub_organization` |
| `ImportError` عند تحميل `order.py` | مسار `sys.path.insert` النسبي لا يعمل ضمن سياق تحميل Odoo | انقل محتوى `lib/*.py` داخل حزمة فرعية من الموديول نفسه بدل مسار خارجي |
| القيد الفريد لا يُنشأ | تعارض اسم قيد مع قيد موجود مسبقًا | راجع `_sql_constraints` بأسماء فريدة عالميًا |

---

## تحديث حرج — تعليمات تثبيت حقيقية مُتحقَّقة فعليًا (الجولة العشرون)

كل ما يلي **شُغِّل فعليًا بنجاح** ضد Odoo 19 حقيقي + PostgreSQL 16 حقيقي —
ليس تخمينًا. البيئة السابقة افترضت خطأً عدم توفر root/PostgreSQL — كلاهما
متاح فعليًا في بيئة تطوير حاوية عادية بصلاحيات جذر.

### 1. تثبيت PostgreSQL (Ubuntu/Debian، بصلاحيات جذر)
```bash
apt-get update
apt-get install -y postgresql postgresql-contrib libpq-dev libldap2-dev libsasl2-dev
service postgresql start   # أو: pg_ctlcluster 16 main start
su - postgres -c "createuser -s <اسم_مستخدمك>"
createdb octa_test
```

### 2. تثبيت اعتماديات Odoo 19 الحقيقية
```bash
git clone --depth 1 --branch 19.0 --filter=blob:none https://github.com/odoo/odoo.git
cd odoo
pip install -r requirements.txt --break-system-packages
```

### 3. تثبيت موديولات Octa Connect (استبدل المسار بمسار هذا المشروع)
```bash
python3 odoo-bin -d octa_test \
  --addons-path=odoo/addons,addons,/path/to/octa_connect/addons \
  -i octa_hub_core,octa_hub_api,octa_hub_connector_demo,octa_hub_ui \
  --stop-after-init \
  --db_host=localhost --db_user=<مستخدمك> --db_password=<كلمتك>
```
**النتيجة المُتحقَّقة فعليًا**: تثبيت نظيف بصفر أخطاء، 4/4 موديولات
`installed` في `ir_module_module`، 26 جدولًا فعليًا في قاعدة البيانات.

### 4. تشغيل اختبارات Odoo الحقيقية (كانت جميعها مكتوبة NOT RUN لـ20 جولة)
```bash
python3 odoo-bin -d octa_test \
  --addons-path=odoo/addons,addons,/path/to/octa_connect/addons \
  -i octa_hub_core,octa_hub_api,octa_hub_connector_demo,octa_hub_ui \
  --test-enable --test-tags /octa_hub_core --stop-after-init \
  --db_host=localhost --db_user=<مستخدمك> --db_password=<كلمتك>
```
**النتيجة المُتحقَّقة فعليًا**: `0 failed, 0 error(s) of 29 tests`.

### ملاحظات مهمة من التشغيل الفعلي
- استخدم `--test-tags /octa_hub_core` لتشغيل اختبارات هذا الموديول فقط
  (بدون هذا، `--test-enable` يشغّل أيضًا مئات اختبارات Odoo الأساسية نفسها).
- 4 عيوب حرجة/عالية و4 اختبارات خاطئة اكتُشفت **فقط** بهذا التشغيل الفعلي
  ولم تكتشفها 19 جولة قراءة كود سابقة — راجع `docs/audit-findings.md`
  قسم "مراجعة عشرون" للتفاصيل الكاملة قبل الاعتماد على أي ادعاء "لم
  يُختبر بعد" في ملفات أقدم دون التحقق أولًا.
