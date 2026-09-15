# المعمارية

## الهيكل
```
octa_connect/
  addons/
    octa_hub_core/       # Organization/Branch/Membership/Role/PartnerGrant/Invitation/AuditLog/Order (Gate A)
    octa_hub_api/        # عقد API/Webhooks + نواة idempotency مختبرة (Gate B)
    octa_hub_connector_demo/  # محاكي تطبيق توصيل معلن (Gate B)
    octa_hub_ui/          # بوابة التاجر - design tokens + OWL أولي (Gate C)
  tools/
    mock_pos/             # خدمة POS تجريبية HTTP مستقلة تمامًا عن Odoo (Gate B)
    catalog_reconcile/     # منطق تسوية الكتالوج pure-Python (Gate D)
  docs/                   # هذا المجلد
```

## القرار المعماري الأهم: فصل النواة المنطقية عن Odoo

القسم 19 يشترط دليلًا حقيقيًا على التشغيل، وبيئة التطوير الحالية لا تملك Odoo.
لذلك عزلنا كل منطق حرج (idempotency، تسوية الكتالوج) في وحدات Python نقية
(pure) بلا `import odoo`، بحيث:
1. تُختبر فعليًا بـ pytest عاديّ في أي بيئة (وقد اختُبرت: 24/24 PASS).
2. تُستدعى من نماذج Odoo (`octa_hub_api/controllers/api_controller.py`,
   `octa_hub_core/wizards/activation_wizard.py`) كطبقة رقيقة فقط تربط
   القاعدة بالتخزين — لا تعيد كتابة القواعد.
3. عند توفر Odoo 19 فعلي، الاستبدال هو "توصيل" (wiring) لا "إعادة بناء".

## نموذج الهيئات (Gate A)
`Organization` (tenant/merchant، ليس res.company) ← `Branch` (فرع مستقل) ←
`Membership` (مستخدم + party_type + role_code + branches مسموحة) ←
`Permission` (فعل دقيق منفصل عن الدور) ← `PartnerGrant` (تفويض شريك محدود
بعميل/فروع/أفعال/مدة). العزل: `security/record_rules.xml` (ORM) +
`OctaHubPermission.has_permission()` (تحقق سيرفري صريح قبل أي فعل حساس).

## نموذج الطلب (Gate B)
`octa.hub.order` (لقطة ثابتة) + `octa.hub.order.event` (سجل أحداث) +
`octa.hub.delivery.attempt` (كل محاولة). ثلاثة محاور حالة مستقلة:
transport_state / commercial_state / payment_state — لا يُشتق أحدها من
الآخر (القسم 9).

## آلية Queue
**لم تُختر بعد.** القسم 11 يشترط "اختيار آلية queue واحدة بعد التحقق من
Odoo19" — هذا التحقق نفسه غير ممكن بدون Odoo فعلي حاليًا (لا نعرف بالتأكيد
حالة `queue_job` OCA على فرع 19، ولا نفترضها كما يحذر القسم 3). القرار
مؤجَّل لحين توفر بيئة Odoo 19 حقيقية — مسجّل كبند مفتوح في `docs/decisions.md`.

## التصميم (Gate C)
design tokens في `octa_hub_ui/static/src/scss/design_tokens.scss` مستخرجة
حرفيًا من جدول 3 في الوثيقة الأصلية. مكوّن OWL واحد أولي (`dashboard.js`)
كنقطة بداية معمارية (استخدام `useState`, `onWillStart`, تحميل مستقل لكل
بطاقة حتى لا يمحو فشل قسم بقية الصفحة) — **غير مُصوَّر وغير مُختبر بمتصفح**.

## Gate E — طبقة منطق أعمال إضافية (بعد مراجعة FeedUs، v1.2/v0.5)

نفس نمط الفصل المعماري أعلاه (نواة pure-Python معزولة عن Odoo) طُبِّق على
6 وحدات جديدة في `addons/octa_hub_core/lib/`:

- `price_resolution.py` — حسم سعر بأولوية صريحة (فرع+قناة > قناة > فرع > أساس)
- `modifier_rules.py` — قواعد مجموعات الإضافات (min/max/mandatory/repeat)
- `availability_state.py` — توفر desired مقابل confirmed، partial عبر الوجهات
- `external_mapping.py` — تعميم المطابقة الخارجية لـ8 أنواع كيانات
- `connector_capabilities.py` — فصل ConnectorDefinition/MerchantConnection/BranchChannelBinding
- `reliability_metrics.py` — median/p95/p99 حقيقية، مربوطة فعليًا بـ`order.py::get_dashboard_metrics`

هذه الوحدات **جاهزة للربط** بموديلات Odoo لكن **لم تُربَط بعد** (باستثناء
`reliability_metrics.py` المربوطة جزئيًا) — الأولوية التالية هي بناء
موديلات Odoo فعلية (`octa.hub.price.override`, `octa.hub.modifier.group`,
`octa.hub.availability`, إلخ) تستدعي هذا المنطق المُختبَر، بدل إعادة كتابته.
