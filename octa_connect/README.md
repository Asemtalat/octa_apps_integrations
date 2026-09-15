# Octa Connect — المرحلة الأولى (Gates A–D)

⚠️ **هذا ليس منتجًا جاهزًا للإنتاج.** راجع `docs/requirements-coverage.md`
و`docs/test-report.md` و`docs/HANDOFF.md` قبل أي استخدام. جزء كبير من الكود
هنا **مكتوب لكن غير مُشغَّل (NOT RUN)** لعدم توفر Odoo 19/PostgreSQL في بيئة
التطوير التي أُنتِج فيها هذا التسليم.

## ما هو مُثبَت فعليًا بالاختبار (104/104 PASS)
منطق منع التكرار والتزامن (Gate B)، تسوية الكتالوج (Gate D)، وحل الأسعار/
قواعد الإضافات/حالة التوفر/تعميم المطابقة/مصفوفة قدرات الموصلات/مؤشرات
الموثوقية (Gate E — بعد مراجعة FeedUs v1.2/v0.5) — كل هذا Python نقي بمعزل
عن Odoo عمدًا، ومُختبَر فعليًا بأمر واحد:

```bash
python3 -m pip install pytest
python3 tools/run_all_tests.py
```
لا تحاول تشغيل كل شيء في استدعاء pytest واحد من الجذر — هذا يفشل بتعارض
استيراد حقيقي (`docs/audit-findings.md#F-TEST-01`).

## ما هو مكتوب لكن NOT RUN
كل ما تحت `addons/octa_hub_core`, `addons/octa_hub_api/controllers`,
`addons/octa_hub_ui` هو كود Odoo 19 حقيقي (models/security/controllers/OWL)
لم يُشغَّل بعد. لتشغيله:

```bash
# 1. بيئة Odoo 19 حقيقية (Docker مثال):
docker run -d --name octa-pg -e POSTGRES_PASSWORD=odoo -e POSTGRES_USER=odoo postgres:15
git clone https://github.com/odoo/odoo.git --branch 19.0 --depth 1
pip install -r odoo/requirements.txt

# 2. ضع مجلد addons/ من هذا المستودع ضمن addons-path
python3 odoo/odoo-bin -d octa_test \
  --addons-path=odoo/addons,./addons \
  -i octa_hub_core,octa_hub_api,octa_hub_connector_demo,octa_hub_ui \
  --test-enable --stop-after-init \
  --db_host=localhost --db_user=odoo --db_password=odoo
```

راجع `docs/HANDOFF.md` للخطوات التفصيلية والفجوات المعروفة بعد هذا التشغيل.

## بنية المستودع
انظر `docs/architecture.md`.

## التوثيق الكامل
- `docs/requirements-coverage.md` — كل متطلب من الوثائق الأربع (Phase_1 الأصلي، Blueprint v0.4، Phase_1-2 v1.2، Changes v0.5)، مرقّم بحالته الحقيقية.
- `docs/audit-findings.md` — كل عيب حقيقي اكتُشف عبر 8 جولات مراجعة، بشدته وحالة إصلاحه.
- `docs/test-results.md` — كل أمر اختبار ونتيجته الفعلية، والبيئة والنسخ.
- `docs/architecture.md`, `docs/security.md`, `docs/decisions.md`, `docs/design-system.md`, `docs/screen-specs.md`, `docs/migrations.md`
- `docs/api/openapi.yaml` — عقد API أولي.
- `docs/RUNBOOK.md` — تشغيل/تثبيت/ترقية/إعادة اختبار.
- `docs/HANDOFF.md` — نقطة استئناف دقيقة للجولة التالية.
- `CHANGELOG.md` — سجل التغييرات بالجولة.

## بيانات الاختبار
`addons/octa_hub_core/data/demo_data.xml` — عميلان تجريبيان (`[TEST]`)،
3 فروع، اتصال محاكي واحد. لا بيانات عملاء حقيقية إطلاقًا.

## الترخيص والتبعيات
- Odoo 19 نفسه: ترخيصه الخاص (LGPL للـCommunity) — غير مُضمَّن في هذا الـZIP.
- `pytest`: MIT.
- لا تبعيات JS خارجية جديدة أُضيفت (OWL جزء من Odoo web القياسي).
- لم تُنسخ أي أجزاء من "simplify_access_management" المرفق سابقًا للمراجعة —
  هذا البناء أصلي بالكامل (كما يشترط القسم 15 من `Phase_1.md`).
