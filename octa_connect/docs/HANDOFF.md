# Current checkpoint — 2026-09-23: POS integration pilot

This section supersedes historical status statements below.

## Verified
- Restaurant connector branch `codex/octa-pos-connector`, commit `ddf856847f4cfdc9363d68d92123f69b30001f30`: Odoo 18 build 38542332 reports **0 failed, 0 errors of 9 tests**. Remaining warning: alert div lacks accessibility role.
- Hub catalog importer commit `c1f9b61ce52ce23f8000b1fdb91656ce4889dba1`: Odoo 19 build 38542565 reports **0 failed, 0 errors of 52 tests** (44 existing + 8 importer tests).
- Hub delivery pilot commit `4b3d599324b35dc17a32311590455294c39102c2` deployed in build 38542952; Odoo.sh shows Test: Warning, app menu loads. Four new delivery tests were added. Exact final test summary for this commit was NOT captured; do not claim 56 PASS.
- Restaurant `test` fast-forwarded to ddf85684. Its existing "Update current build" setting preserved database/build 37082073; Odoo.sh shows successful update. Production main unchanged.
- In the restaurant test database, activated developer mode and clicked Apps > Update Apps List > Update. Subsequent verification was blocked, so completion of list refresh is NOT confirmed. Connector installation on this database has NOT been demonstrated.

## Precise blocker
Browser automatic approval review failed due to account usage limit, not unsafe action or user rejection. Last blocked action: reading restaurant staging screen after Update Apps List. Do not circumvent with alternate browser surfaces or raw requests. Resume live verification only after the limit/access problem is resolved.

## Resume sequence
1. Inspect restaurant staging Apps list; search technical module `octa_pos_connector`, install only this module if not installed.
2. Confirm first Aziziya POS config id 4 / company مطعم العزيزيه. Do not use inactive second Aziziya POS.
3. Disable physical printer and kitchen integrations in the test configuration before any actual order exercise. Existing staging includes real printer addresses. No paid or real kitchen order is authorized by the pilot.
4. Configure a disabled bridge scoped to this POS, export catalog and inspect actual item counts, default/Hunger/keta prices, taxes, photos and modifiers. No actual merchant menu has yet been exported/imported.
5. Configure hub sandbox endpoint/storefront and explicit pricelist mappings; pair a scoped API key securely. No API key has yet been issued or copied.
6. Import catalog; repeat and verify IDs/counts, changed prices and archived missing items.
7. Prepare persisted one-item test delivery, send only to staging, verify POS draft, visible cashier notification, receipt timestamps, then repeat same delivery to confirm no duplicate. No cross-system order has yet been sent.
8. Read complete logs for build 38542952. Newly added delivery tests mock HTTP; they do not replace real cross-system proof.
9. Fix alert accessibility roles in both modules during next code change; rerun final tests after substantive changes.

## Pilot limits / review findings
- Manual sandbox delivery only, not production cron/worker or delivery-app connectivity.
- Orders with modifiers, tracked items or combos are explicitly rejected pending mapping.
- Display acknowledgment is not cashier acceptance. Timestamps are second-resolution; full stage-by-stage millisecond telemetry remains incomplete.
- Source binding needs strengthening for order dispatch if endpoint URL/API key changes after catalog import.
- Delivery response parser should explicitly reject non-object JSON; currently a JSON list can cause AttributeError.
- Catalog full snapshots archive missing items, but removed modifier options and removed channel mappings still need reconciliation rules.
- Do not expose pairing secrets or merchant data in repository documentation.

## Optional Claude collaboration
Use one feature branch per writer. Claude submits a commit SHA, changed-file list, requirement-to-test coverage and explicit NOT RUN cases. Reviewer checks the exact commit and runs Odoo acceptance tests. No simultaneous edits to the same files, no direct main pushes, and no shared production credentials. This workflow can divide work but does not guarantee lower total token usage.

---

# Current handoff — 2026-09-22

Branch: `codex/security-reliability-audit`; draft PR #1. Main remains unchanged.

## Verified
- Security/reliability batch: 190 isolated Python tests; 37 actual Odoo tests.
- Backend orders search/reset/empty states rendered and exercised in Odoo.sh.
- Merchant portal first build `dfb9f8ad`: 42 actual Odoo tests, zero failures/errors,
  including five authenticated HTTP tests with a non-internal Portal user.
- `/octa/start` is the branded entry, `/octa/portal` the authenticated merchant workspace.
  This is separate from the Odoo backend; existing Odoo authentication is reused.
- Read-only overview, orders, application connections and account/branches are implemented.
- Additional tenant/branch HTTP fixtures and demo-only preview deployed in `734137cc`;
  its 44 tests passed (including populated data isolation), but demo XML loading failed.
  Corrected the invalid XML comment in 65fd460e: build 38489007 SUCCESS, 44 tests,
  zero failures/errors. Dashboard, populated orders, exact search, connection flags and
  account/branches viewed in the real browser. Screenshot delivered to the user.

## Next acceptance work / unresolved
- Explicit merchant provisioning UI + invitations and enforced multi-step verification.
  The new entry does not implement MFA or certify email delivery.
- Full negative ORM/RPC permission matrix, beyond portal controller domain checks.
- Order detail/timeline, menu management/publishing, English and mobile visual acceptance.
- Reliable transaction boundaries and real POS/provider adapters; outbound cron stays disabled.
- Core currently loads test fixtures through its data list, not demo: separate these safely
  before production; do not delete records on a populated database without migration planning.
- Portal demo preview uses the existing development administrator and TEST merchant only,
  loads under demo mode, creates no credentials, and sends no orders or mail externally.

Historical notes below are retained as history and may describe superseded environment limits.

---

# HANDOFF — نقطة الاستئناف (بعد المراجعة الواحدة والعشرين)

## أهم ما تغيّر هذه الجولة (الواحدة والعشرون — أول عطل من نشر فعلي حقيقي)
المستخدم نشر المشروع فعليًا على Odoo.sh (`dev.odoo.com`) ورفع صورة شاشة
حقيقية لعطل: `TypeError: v1.onAction is not a function` عند فتح النظرة
العامة. تتبعت السبب بدقة: زر في `EmptyState` يستدعي `onAction` غير
مُمرَّرة. أُصلح إصلاحين (تحصين عام + سلوك صادق). تفاصيل كاملة في
`docs/audit-findings.md#مراجعة-واحدة-وعشرون`.

**قيد بيئي جديد موثَّق**: لا متصفح headless متاح هنا (Chromium عبر apt
مجرد stub لـsnap غير مفعَّل؛ Playwright يحتاج تنزيل ثنائيات من نطاقات غير
مسموحة) — أي عطل واجهة مستقبلي يحتاج نفس أسلوب التتبع اليدوي الدقيق
لرسالة الخطأ، لا تحقق بصري آلي كامل.

## الأولوية القصوى للجولة القادمة
1. **إن استمر المستخدم بالتجربة على النشر الفعلي**: توقّع بلاغات أعطال
   إضافية مشابهة — أي مكوّن آخر بأزرار/تفاعلات لم تُختبَر بصريًا بعد
   (order_list.js، order_detail.js) قد يحمل نفس فئة الخطأ. راجعها استباقيًا
   بنفس الدقة (كل prop اختيارية تُستدعى كدالة، تأكد من تمريرها فعليًا في
   كل نقطة استخدام).
2. باقي أولويات الجولة العشرين (اختبار octa_hub_api/octa_hub_ui، الأقسام
   2.4/2.6/3.4/4 الموسَّع، تكامل POS إنتاجي حقيقي) لا تزال قائمة.

## نقطة الاستئناف (المراجعة العشرون، سياق سابق)

## تصحيح بيئي جوهري — اقرأ هذا أولًا قبل أي شيء آخر
**كل الجولات من 1 إلى 19 افترضت خطأً "لا صلاحيات جذر متاحة".** هذا غير
صحيح. البيئة تعمل فعليًا كـ`root` (`whoami` → `root`). `sudo: not found`
كان يعني فقط أن أداة `sudo` نفسها غير مثبَّتة — ليس غياب الصلاحيات. هذا
يعني: **PostgreSQL وOdoo 19 الحقيقيان قابلان للتشغيل الفعلي في هذه البيئة**،
عكس كل الافتراض السابق عبر 19 جولة. راجع `docs/RUNBOOK.md` للتعليمات
المُتحقَّقة بالكامل (شُغِّلت فعليًا بنجاح، ليست نظرية).

## أهم ما تغيّر هذه الجولة (العشرون)
ثُبِّتت PostgreSQL 16 واعتماديات Odoo 19 فعليًا. كل الأربع موديولات
ثُبِّتت بنجاح على Odoo 19 حقيقي. **29/29 اختبار Odoo TransactionCase
(مكتوبة NOT RUN منذ جولات عديدة) شُغِّلت فعليًا لأول مرة: 0 failed, 0
error(s).** اكتُشفت وأُصلحت **9 عيوب حقيقية** لم تكتشفها 19 جولة مراجعة
سابقة ولا مراجعتان مستقلتان خارجيتان، أهمها:
- موديول كامل (`octa_hub_connector_demo`) بلا `__manifest__.py` — كان
  Odoo يرفضه بصمت منذ الجولة الأولى.
- نظام الدعوات بأكمله كان معطوبًا كليًا (ديكوريتر `create()` خاطئ).
- **الأهم أمنيًا**: لا ربط كان موجودًا بين نموذج العضوية المخصص وصلاحيات
  Odoo الفعلية — منح "عضوية" لم يكن يمنح صلاحية حقيقية إطلاقًا طوال 19
  جولة. تفاصيل كاملة في `docs/audit-findings.md#مراجعة-عشرون`.

## الأولوية القصوى للجولة القادمة
1. **الاستمرار في استخدام Odoo حقيقي فعليًا** للتحقق من أي تعديل جديد —
   البيئة تدعم هذا الآن، لا عذر للعودة لـ"NOT RUN" كافتراض افتراضي بعد اليوم.
2. تشغيل اختبارات `octa_hub_api`/`octa_hub_ui` الحقيقية إن وُجدت (لم
   تُفحَص بـ`--test-tags` منفصلة هذه الجولة، فقط `octa_hub_core`).
3. اختبار الواجهة (screens) فعليًا عبر متصفح حقيقي — لم يُحاوَل بعد رغم
   توفر Odoo فعليًا الآن؛ يحتاج تشغيل خادم Odoo (`--http-port`) بدل
   `--stop-after-init` فقط.
4. باقي أولويات الجولات 16-19 (القسم 2.4/2.6، 3.4، توسيع القسم 4، تكامل
   POS إنتاجي حقيقي) لا تزال قائمة.
5. **ملاحظة بيئية**: قاعدة بيانات `octa_test` ومجلد Odoo المُستنسَخ في
   `/tmp/odoo19_src` قد لا يبقيا بين الجلسات (`/tmp` وحالة PostgreSQL قد
   يُعاد تعيينهما) — أعد تشغيل خطوات RUNBOOK.md من الصفر عند الحاجة، لا
   تفترض بقاءهما.

## نقطة الاستئناف (المراجعة التاسعة عشرة، سياق سابق)

## أهم ما تغيّر هذه الجولة (التاسعة عشرة — إكمال محوِّل حقيقي)
بنيت محوِّل حقيقي فعلي (`lib/mock_pos_adapter.py`) يثبت أن آلية outbox
كاملة تعمل من طرف إلى طرف ضد خادم HTTP حقيقي (6 اختبارات جديدة). تحققت
من مصدر Odoo 19 أن قيود التفرّد الجديدة من الجولة السابقة سليمة فعليًا.
**189/189 pytest PASS (كان 183)**، استقرار مُتحقَّق بـ3 تشغيلات متتالية.

## الأولوية القصوى للجولة القادمة
1. **تكامل مع موصل POS إنتاجي حقيقي** — لا يزال NOT_STARTED؛ المحوِّل
   الحالي لأداة اختبار (mock_pos) فقط، ليس نظامًا حقيقيًا.
2. باقي أولويات الجولتين 17/18 (القسم 2.4/2.6، 3.4، توسيع القسم 4، ربط
   report_access.py، تشغيل test_catalog.py فعليًا) لا تزال قائمة.
3. **تثبيت Odoo 19 حقيقي** يبقى الشرط الأسبق لكل شيء.

## نقطة الاستئناف (المراجعة الثامنة عشرة، سياق سابق)

## أهم ما تغيّر هذه الجولة (الثامنة عشرة — إصلاحات مستهدفة، طلب صريح بلا نطاق جديد)
أُصلح النجاح الوهمي في العامل جذريًا (عقد ثلاثي الحالة + دورة استعلام
منفصلة بنيويًا، مع دليل تكامل حقيقي ضد خادم HTTP فعلي). أُصلح allow_zero
المُسقَط صامتًا، مُنعت الأسعار السالبة، أُكملت هوية مجموعات الإضافات
ومنع تكرارها بالنطاق الصحيح، أُضيف قيد اتساق تاجر. أُضيفت 18 اختبار Odoo
TransactionCase حقيقي جديد (NOT RUN). **183/183 pytest PASS (كان 177)**.
تفاصيل كاملة مع تمييز صريح مكتوب/مختبر في `docs/audit-findings.md` قسم
"مراجعة ثامنة عشرة".

## الأولوية القصوى للجولة القادمة
1. **بناء محوِّل موصل حقيقي فعلي** (dispatch_fn/query_fn حقيقيتان تتصلان
   بنظام POS فعلي أو حتى mock_pos كخطوة أولى) لتفعيل cron الطابور —
   معطَّل الآن عمدًا لعدم وجوده.
2. **تشغيل test_catalog.py الجديد فعليًا** فور توفر Odoo 19 + PostgreSQL.
3. باقي أولويات الجولة السابعة عشرة (القسم 2.4/2.6، القسم 3.4، توسيع
   القسم 4، ربط report_access.py) لا تزال قائمة — لم تُعالَج هذه الجولة
   بناءً على طلب التركيز على الإصلاح لا الإضافة.
4. **تثبيت Odoo 19 حقيقي** يبقى الشرط الأسبق لكل شيء.

## نقطة الاستئناف (المراجعة السابعة عشرة، سياق سابق)

## أهم ما تغيّر هذه الجولة (السابعة عشرة — نماذج Odoo فعلية للمنيو)
نُفِّذت الأولوية القصوى من آخر جولة: 4 نماذج Odoo جديدة للمنيو والإضافات
والأسعار (`models/catalog.py`)، مرتبطة بـstorefront، تستدعي المنطق
المُختبَر مسبقًا بدل تكراره. `base.SAR` تحقَّق كحقيقي فعليًا (لم يعد
افتراضًا معلَّقًا). **177/177 اختبار PASS (بلا تغيير عددي)**.

## الأولوية القصوى للجولة القادمة
1. **القسم 2.4**: ربط `channel_supports_repeat_or_reject` (مبني ومُختبَر
   في `modifier_rules.py`) بنموذج `octa.hub.modifier.group` الجديد فعليًا.
2. **القسم 2.6**: معاينة فروق النشر + نتيجة نشر لكل storefront — لا شيء بُني بعد.
3. **القسم 3.4**: سبب إلغاء مصنَّف + جهة مسؤولة على `octa.hub.order`.
4. **القسم 4**: توسيع مؤشرات السرعة لبقية المراحل الست المتبقية.
5. **ربط `report_access.py`** بنموذج Odoo فعلي.
6. **تثبيت Odoo 19 حقيقي** يبقى الشرط الأسبق لكل شيء — لا شيء من كل هذا شُغِّل فعليًا.

## نقطة الاستئناف (المراجعة السادسة عشرة، سياق سابق)

## أهم ما تغيّر هذه الجولة (السادسة عشرة — مراجعة بوابة هنقرستيشن)
جدول تصنيف كامل في `docs/hungerstation-gap-review.md` (26 بندًا). نُفِّذ:
storefront (تعدد براندات لموقع واحد)، تصحيح حالة بعد نهائية بحدث موثوق،
مواعيد التشغيل (نطاق جديد بالكامل)، إعادة فحص صلاحيات المستندات (السيناريو
المطلوب حرفيًا). **177/177 اختبار PASS (كان 157؛ +20 جديدة)**. تفاصيل
كاملة في `docs/audit-findings.md` قسم "مراجعة سادسة عشرة".

## الأولوية القصوى للجولة القادمة
1. **القسم 2 كموديل Odoo فعلي**: `price_resolution.py`/`modifier_rules.py`
   لا تزال منطقًا معزولًا فقط — تحتاج `octa.hub.catalog.item` و
   `octa.hub.modifier.group` كنماذج Odoo حقيقية مرتبطة بـ`storefront_id`.
2. **ربط report_access.py بموديل Odoo فعلي** — المنطق مُختبَر لكن غير
   مربوط بنموذج "مستند مُولَّد" حقيقي أو `ir.attachment`.
3. **توسيع مؤشرات القسم 4** — لا يزال مرحلتين فقط (dispatch/registered)
   من ثماني مراحل مطلوبة (استقبال→حفظ→طابور→POS→قبول آلي/بشري→رجوع→تحضير→مندوب).
4. باقي أولويات الجولة الخامسة عشرة (R13 الإرسال الفعلي لنظام POS) لا تزال قائمة.
5. **تثبيت Odoo 19 حقيقي** يبقى الشرط الأسبق لكل شيء — لا شيء من كل هذا شُغِّل فعليًا.

## نقطة الاستئناف (المراجعة الخامسة عشرة، سياق سابق)

## أهم ما تغيّر هذه الجولة (الخامسة عشرة — تدقيق ذاتي على كود الجولة السابقة)
بدل نطاق جديد، راجعت بعناية أكبر ما كتبته بنفسي مباشرة في الجولة السابقة.
لقيت مشكلتين حقيقيتين: (1) لا ربط تلقائي بين اتصال جديد وتعريف قدرته
(R12) — أُصلح؛ (2) `claim_batch()` كانت تستخدم `lock_for_update()` الخاطئة
لسياق دفعة (ترفع استثناء للكل بدل تجاهل المشغول بصمت) — أُصلحت بـ
`try_lock_for_update()` الصحيحة. **157/157 اختبار PASS (بلا تغيير عددي).**
تفاصيل كاملة في `docs/audit-findings.md` قسم "مراجعة خامسة عشرة".

## نقطة الاستئناف (المراجعة الرابعة عشرة، سياق سابق)

## أهم ما تغيّر هذه الجولة (الرابعة عشرة — إغلاق الفجوات الأربع المتبقية)
طلب صريح بمتابعة فجوات الجولة السابقة. **157/157 اختبار PASS (كان 145)**:
- اتحاد أدوار التاجر عبر OR: **CLOSED**.
- R12 (تعريف قدرة مؤقت): **CLOSED** — نموذجا Odoo دائمان + بيانات حقيقية.
- R13 (لا queue/worker): **PARTIAL** — نمط outbox كامل مُختبَر (8/8، تزامن
  20 thread حقيقي) + نموذج دائم + cron حقيقي + إدراج فعلي من الـcontroller،
  **لكن الإرسال الفعلي لنظام POS من داخل العامل لا يزال NOT_STARTED**.
- R14 عمق: حقلا توقيت صريحان يستبدلان اشتقاق write_date/create_date.

تفاصيل كاملة في `docs/audit-findings.md` قسم "مراجعة رابعة عشرة".

## الأولوية القصوى للجولة القادمة
1. **إكمال R13**: ربط `run_worker_batch()` بموصل فعلي حقيقي (استدعاء HTTP
   حقيقي لنظام POS، وليس `item.mark_done()` صوريًا كما هو الآن) — البنية
   كاملة، هذا آخر جزء مفقود لإغلاق أكبر فجوة بنيوية في المشروع بالكامل.
2. **تثبيت Odoo 19 حقيقي** يبقى الشرط الأسبق لكل شيء آخر — لا شيء من
   إصلاحات هذه الجولة أو سابقاتها شُغِّل فعليًا على تثبيت حي.
3. عمق R14 المتبقي: تغطية "استلام الحدث" و"حفظه" كمرحلتين زمنيتين
   منفصلتين صراحة (القسم 10)، لا فقط dispatch→registered.

## نقطة الاستئناف (المراجعة الثالثة عشرة، سياق سابق)

## أهم ما تغيّر هذه الجولة (الثالثة عشرة — رد فعلي على مراجعة V2 مستقلة)
مراجعة V2 قدّمت أدلة تنفيذية حقيقية (تشغيل runner فعلي + استخراج AST فعلي
لإثبات مسار نجاح كاذب). تحقَّقت كل ملاحظة حرجة بدليل مستقل (مصدر Odoo 19 أو
تجربة فعلية) قبل الإصلاح. **145/145 اختبار PASS (كان 135؛ +10 جديدة، 6
مجموعات لا 5)**. أهم إصلاح: نجاح استقبال وهمي حقيقي (200 + order_id=None)
أُصلح جذريًا مع فصل منطق القرار لوحدة مُختبَرة بالكامل بعد اكتشاف أن جزءًا
من استجابة psycopg2 (`.diag`) غير قابل للتلفيق في اختبار معزول. تفاصيل
كاملة في `docs/audit-findings.md` قسم "مراجعة ثالثة عشرة".

**تحقق هوية مهم**: اختلاف بصمة الأرشيف بين الجولتين كان أثر تغليف zip فقط
(تحقَّق بـ`diff -rq` فعليًا، صفر اختلاف محتوى). أُضيف
`docs/SOURCE_MANIFEST.sha256` (بصمة كل ملف على حدة) — **استخدم هذا الملف
لا بصمة الزيب الكلية** للتحقق من الهوية في المراجعات القادمة.

## الأولوية القصوى للجولة القادمة
1. **R13 — لا queue/worker حقيقي**: أكبر فجوة بنيوية متبقية في المشروع
   كله. استقبال الحدث لا يزال متزامنًا بالكامل داخل نفس طلب HTTP، بلا
   طابور دائم أو عامل خلفي فعلي يربط الاستقبال بالإرسال الفعلي لنظام POS.
2. **اتحاد أدوار التاجر عبر OR** (مُكتشَف هذه الجولة، موثَّق في
   `record_rules.xml` وaudit-findings.md): مستخدم بعضوية تاجر متعددة
   الأدوار (owner+branch_manager لعميل واحد) يرى نطاق العميل كله بدل فرعه
   فقط فقط. يحتاج إما منع تعدد الأدوار داخل هيئة التاجر نفسها (توسيع
   `_check_single_authority_per_user`)، أو إعادة تصميم القواعد لتعتمد
   `active_membership_id` صراحة.
3. **cron لتحديث `is_currently_valid`**: الحقل الجديد في `partner_grant.py`
   لا يتحدّث تلقائيًا لمجرد مرور الوقت بلا كتابة على السجل — يحتاج مهمة
   مجدولة دورية (مرتبط بـR13).
4. **عمق R14**: `get_dashboard_metrics` لا يزال يحسب من `write_date -
   create_date` — تقريب خام، يحتاج حقول توقيت صريحة لكل مرحلة في
   `octa.hub.order.event`.
5. باقي أولويات الجولة الثانية عشرة (R12 تعريف قدرة مؤقت) لا تزال قائمة.

## نقطة الاستئناف (المراجعة الثانية عشرة، سياق سابق)

## أهم ما تغيّر هذه الجولة (الثانية عشرة — تحقق فعلي من مصدر Odoo 19)
استُلمت مراجعة مستقلة خارجية حقيقية (Codex/أداة أخرى حاولت التثبيت
فعليًا). تنزّل مصدر Odoo 19 الحقيقي (`git clone --branch 19.0`) والتحقق
المباشر من 16 ملاحظة. **12 مؤكَّدة بدليل مصدري وأُصلحت** — أخطرها: كل
`_sql_constraints` في المشروع (8 قيود، 6 ملفات) كانت **ستُتجاهَل صامتًا**
في Odoo 19 الحقيقي (تحذير موثَّق حرفيًا في `odoo/orm/model_classes.py`)،
يعني القيد الأهم في تصميم منع تكرار الطلبات لم يكن ليعمل أبدًا. حُوِّلت
لـ`models.Constraint`. كذلك: `fields._tz_get` (غير موجودة)،
`res.groups.category_id` (صار `privilege_id`)، 7 موديلات بلا عزل، `type=
"json"` (لا يضبط HTTP حقيقي)، `rec.field is None` (يفشل دائمًا — Odoo
يُرجع False)، قبول الدعوة الوهمي، اختبارات Odoo غير قابلة للاكتشاف،
مكوّنات واجهة بلا مسار تنقّل. **135/135 اختبار PASS (كان 131).**

## المتبقي من هذه الجولة (لم يتسع الوقت)
R05 (أمان مفتاح API — لا حماية timing-attack ولا تدوير)، R12
(`_enforce_orders_capability` تبني تعريفًا مؤقتًا، لا تخزينًا حقيقيًا)،
R13 (**أكبر فجوة بنيوية متبقية**: لا queue/worker حقيقي يربط استقبال API
بإرسال فعلي غير متزامن لـPOS). هذه الثلاثة هي الأولوية القادمة الأعلى.

## نقطة الاستئناف (المراجعة الحادية عشرة، سياق سابق)

## أهم ما تغيّر هذه الجولة (الحادية عشرة — مراجعة قبول نهائية)
لم يُرفَع ملف جديد؛ اعتُمد آخر ZIP مُسلَّم فعليًا (بصمة SHA-256:
`abf1c05e26a2dd5aa7e68a8992587cfbd1f050e06918790f1ac5921765bbda8c`)،
فُكَّ في مسار معزول، وقورن (مطابق 100% لمجلد العمل). أُنشئ
`docs/file-review-register.md` جديد يغطي 76 ملف مصدري. 5 مشاكل حقيقية
جديدة اكتُشفت وأُصلحت (`except` عام يخفي أخطاء، capability enforcement
غير موصول، 5×ValueError خاطئ، حقل superseded_by_id ميت، مسار استعادة
كلمة مرور مفقود بالكامل) — تفاصيل في `audit-findings.md`. **131/131
اختبار PASS (بلا تغيير عددي؛ الإصلاحات بنيوية في كود Odoo NOT RUN).**

## نقطة الاستئناف (المراجعة العاشرة، سياق سابق)

## أهم ما تغيّر هذه الجولة (العاشرة — تماسك العقود، لا نطاق جديد)
بدل بناء المزيد من OC05، فُحص التماسك بين كل ما بُني سابقًا. 4 تعارضات
حقيقية اكتُشفت وأُصلحت (قدرات الموصل، أحداث الطلب، عرض مؤشرات التوقيت،
تقريب العملات) — تفاصيل كاملة في `docs/audit-findings.md` قسم "مراجعة
عاشرة". **131/131 اختبار PASS (كان 124).**

## نقطة الاستئناف (المراجعة التاسعة، سياق سابق)

## العائق الثابت عبر كل الجولات
لا Odoo 19، لا PostgreSQL، لا root/sudo، لا متصفح — في بيئة chat sandbox
هذه. الدليل بالأوامر الفعلية في `docs/test-results.md`. هذا لم يتغيّر.

## أهم ما تغيّر هذه الجولة (الثامنة — Gate E)
استُلم تحديث نطاق صريح (v1.2/v0.5) يضيف 22 بند "OC05" من مراجعة تنافسية
لـFeedUs. صُنِّف كل بند فعليًا بالكود قبل التعديل. نُفِّذت 6 وحدات
pure-Python جديدة مُختبَرة بالكامل (47 اختبار PASS) لأكثر بنود P0 قابلية
للتنفيذ: حل الأسعار، قواعد الإضافات، حالة التوفر، تعميم المطابقة، مصفوفة
قدرات الموصلات، مؤشرات الموثوقية (ومربوطة فعليًا بالداشبورد). أُضيف
`octa.hub.brand`. **15 من 22 بند OC05 لا تزال NOT_STARTED** — مذكورة
صراحة، أهمها: مركز تفعيل التاجر بحقوله الكاملة (OC05-03)، النشر والمقارنة
(OC05-13)، توسعة رحلة الطلب (OC05-14)، إعادة المعالجة (OC05-15)، مركز
الاستثناءات (OC05-18).

## أهم ما تغيّر في الجولة السابعة (سابقًا)
1. **اكتُشف وأُصلح**: تشغيل كل الاختبارات معًا من جذر المشروع (أول شيء
   طبيعي يجرّبه أي مطوّر) كان يفشل بـ36 خطأ من 53. أُصلح بـ
   `tools/run_all_tests.py` (يعزل كل مجموعة بعملية منفصلة). راجع
   `audit-findings.md#F-TEST-01`.
2. سيناريوهان حديّان جديدان في `reconcile.py` اختُبرا ووُثِّقا (تكرار داخل
   نفس الدفعة: آمن؛ نفس الإصدار بمحتوى مختلف: يُعامَل كتحديث لا كتعارض —
   قرار ضمني كان غير موثَّق، موثَّق الآن).
3. اختبارا إجهاد جديدان: 200 thread متزامن (10 أضعاف الحد الأدنى)، و20
   اتصال HTTP حقيقي متزامن فعليًا ضد mock_pos — كلاهما نجح بلا أي تصادم.

## الحالة الرقمية الحالية
1. **فُتحت 11 صورة مرجعية داخل الـdocx لأول مرة** بعد 5 جولات استخرجت النص
   فقط. النتيجة: اكتشاف أن الألوان الحقيقية (كحلي داكن + teal) مختلفة عمّا
   بُني (أزرق فاتح) — صُحِّح جزئيًا. اكتُشف أيضًا نطاق ضخم غير مُقدَّر سابقًا
   للوحة التشغيل الداخلية (شاشات 29-32) وبوابة الشريك (25-28).
2. **ثغرة أمنية حرجة اكتُشفت وأُصلحت** في `ssrf_guard.py` (كانت من إنتاج
   الجولة السابقة نفسها) — تفاصيل كاملة في `audit-findings.md#F-SEC-05`.
3. **تنظيف معماري**: `sys.path.insert` كان يتكرر داخل كل نداء دالة في 4
   ملفات — انتقل لمرة واحدة عند تحميل الموديل.
4. **إعادة هيكلة التوثيق بالكامل** إلى: `requirements-coverage.md` (جدول
   بالأعمدة السبعة المطلوبة بالضبط)، `audit-findings.md` (جديد)،
   `test-results.md` (جديد، بيئة ونسخ حقيقية)، `RUNBOOK.md` (جديد).

## الحالة الرقمية الحالية
- **131/131 اختبار حقيقي PASS** عبر تشغيل موحَّد آمن (`python3 tools/run_all_tests.py`).
- **0 اختبار Odoo فعلي RUN.**
- **0 screenshot من متصفح Odoo حقيقي.** (توجد معاينتان HTML مستقلتان عُرضتا
  في المحادثة، بالألوان القديمة ثم المصححة — ليستا جزءًا من الموديول).
- **4 من 32 شاشة مبنية جزئيًا** (05-08)، 28 غير مبنية كواجهة.

## الخطوة التالية الدقيقة (بالأولوية، مُحدَّثة بعد Gate E)
1. **وفّر Odoo 19 + PostgreSQL حقيقيين** — لا يزال الشرط الأول لكل شيء آخر.
2. اربط الوحدات الـ6 الجديدة (price_resolution، modifier_rules،
   availability_state، external_mapping، connector_capabilities) بموديلات
   Odoo فعلية (حاليًا جاهزة منطقيًا لكن غير موصولة، عدا reliability_metrics
   الموصولة جزئيًا بالفعل).
3. ~~أعد تصميم activation_wizard.py~~ **تم** (نماذج دائمة جديدة `activation.py`).
4. اربط `lib/order_trace.py` الجديد بحقول `octa.hub.order.event` فعلية
   (لا تزال الحقول الصريحة لكل مرحلة غير مُضافة كأعمدة Odoo).
5. ابنِ `PublishJob`/`PublishTarget` (OC05-13) — لا شيء منها موجود بعد.
6. ابنِ واجهة (screen 04) فعلية تستهلك `octa.hub.activation.checklist` الجديد.
7. باقي الأولويات من الجولة السابعة (توقيع Webhook F-SEC-07، عزل RPC/التصدير F-ISO-01) لا تزال قائمة، لم تُحل بعد.

## الخطوة التالية الدقيقة (الجولة السابعة، سياق تاريخي)
1. **وفّر Odoo 19 + PostgreSQL حقيقيين** (Docker أو خادم بصلاحيات root) —
   شرط مسبق لكل شيء آخر. الخطوات في `RUNBOOK.md` القسم 2.
2. عند أول تشغيل فعلي، افحص فورًا نقاط الفشل المتوقعة المذكورة في
   `RUNBOOK.md` القسم 3 (خاصة أسلوب استيراد `lib/` من داخل موديلات Odoo —
   نمط `sys.path.insert` قد يحتاج تحويلاً لحزمة فرعية حقيقية).
3. ابنِ توقيع Webhook (`F-SEC-07` في audit-findings.md) — أعلى أولوية أمنية
   متبقية غير محلولة.
4. أغلق فجوة عزل RPC/التصدير/المرفقات (`F-ISO-01`) — بند إلزامي صريح لم يُغلق.
5. صحّح المجموعة اللونية الداكنة فعليًا على الشاشات 05-08 (المتغيرات مُضافة
   في `design_tokens.scss` لكن غير مُطبَّقة على أي مكوّن OWL بعد).
6. صمّم من جديد `activation_wizard.py` (D1) ليطابق نمط checklist-بمسؤولين
   الحقيقي من صورة الشاشة 04، بدل حقل "step" الحالي.
7. ابنِ نموذج `octa.hub.modifier.group` (D11) — الصورة (شاشة 10) تُظهره
   بتفصيل دقيق (حد أدنى/أقصى/إلزامي) لم يُبنَ إطلاقًا بعد.

## لا يوجد commit git، لا أسرار حقيقية
كما في كل الجولات السابقة — لا مستودع Git مُهيّأ بهدف، كل بيانات الاختبار
مُعلَّمة `[TEST]`، لا كلمات مرور أو مفاتيح حقيقية في أي مكان.
