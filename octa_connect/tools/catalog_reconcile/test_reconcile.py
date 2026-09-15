"""
اختبارات فعلية (تُشغَّل بـ pytest بدون أي اعتماد على Odoo) لمنطق مطابقة
الكتالوج المطلوب في القسم 12 ومصفوفة القبول في القسم 14 من ملف
Octa_Connect_Claude_Phase_1.md، وجدول رقم 6 في الوثيقة الأصلية.

هذه الاختبارات RUN فعليًا في هذه الجلسة (انظر docs/test-report.md للنتيجة
والأمر المستخدم). أي اختبار Odoo/متصفح منفصل غير هذا يبقى NOT RUN.
"""
from reconcile import CatalogKey, CatalogRecord, CatalogStore, ItemStatus, ConflictReason, reconcile_batch

TENANT = "t_hayat_radwa"
BRANCH = "b_main"
SCOPE = "pos:ezee_main"
TYPE = "item"


def _rec(external_id, name_ar, name_en, price, sku=None, version=1, currency="SAR", scope=SCOPE):
    return CatalogRecord(
        key=CatalogKey(TENANT, BRANCH, scope, TYPE, external_id),
        sku=sku,
        name_ar=name_ar,
        name_en=name_en,
        price_minor_units=price,
        currency=currency,
        version=version,
    )


def test_first_import_creates_new_items():
    store = CatalogStore()
    batch = [_rec("EXT-1", "كبدة", "Liver", 1000)]
    result = reconcile_batch(store, "b1", batch, TENANT, BRANCH, SCOPE, TYPE)
    counts = result.counts()
    assert counts[ItemStatus.NEW.value] == 1
    assert store.get(batch[0].key).name_ar == "كبدة"


def test_reimporting_identical_batch_twice_does_not_duplicate():
    """إعادة استيراد نفس الكتالوج مرتين لا تضاعف البيانات."""
    store = CatalogStore()
    batch = [_rec("EXT-1", "كبدة", "Liver", 1000, sku="SKU-1")]
    reconcile_batch(store, "b1", batch, TENANT, BRANCH, SCOPE, TYPE)
    result2 = reconcile_batch(store, "b2", batch, TENANT, BRANCH, SCOPE, TYPE)
    counts = result2.counts()
    assert counts[ItemStatus.UNCHANGED.value] == 1
    assert counts[ItemStatus.NEW.value] == 0
    assert len(store._committed) == 1  # لا نسخة ثانية


def test_similar_names_do_not_merge():
    """صنفان متشابها الاسم لا يُدمجان — المفتاح الوحيد هو external_id."""
    store = CatalogStore()
    batch = [
        _rec("EXT-1", "كبدة اسكندراني", "Liver Alex", 1000),
        _rec("EXT-2", "كبدة اسكندراني", "Liver Alex", 1200),  # نفس الاسم، معرف مختلف
    ]
    result = reconcile_batch(store, "b1", batch, TENANT, BRANCH, SCOPE, TYPE)
    assert result.counts()[ItemStatus.NEW.value] == 2
    assert len(store._committed) == 2  # سجلان منفصلان، لا دمج بالاسم


def test_channel_price_differences_are_preserved_independently():
    """مثال الوثيقة: نفس الصنف بسعر مختلف حسب الفرع/القناة — لا تُدمج في رقم واحد."""
    store_branch = CatalogStore()
    store_channel_a = CatalogStore()
    store_channel_b = CatalogStore()

    base = _rec("EXT-LIVER", "كبدة", "Liver", 3000, scope=SCOPE)  # 30 ريال بالفرع
    ch_a = _rec("EXT-LIVER", "كبدة", "Liver", 4000, scope="channel:hungerstation")   # 40 ريال بقناة X
    ch_b = _rec("EXT-LIVER", "كبدة", "Liver", 3500, scope="channel:ninja")   # 35 ريال بقناة Y

    reconcile_batch(store_branch, "b1", [base], TENANT, BRANCH, SCOPE, TYPE)
    reconcile_batch(store_channel_a, "b1", [ch_a], TENANT, BRANCH, "channel:hungerstation", TYPE)
    reconcile_batch(store_channel_b, "b1", [ch_b], TENANT, BRANCH, "channel:ninja", TYPE)

    assert store_branch.get(base.key).price_minor_units == 3000
    assert store_channel_a.get(ch_a.key).price_minor_units == 4000
    assert store_channel_b.get(ch_b.key).price_minor_units == 3500


def test_partial_batch_does_not_delete_missing_items():
    """عدم ظهور عنصر في دفعة جزئية لا يعني حذفه."""
    store = CatalogStore()
    reconcile_batch(store, "b1", [_rec("EXT-1", "أ", "A", 100), _rec("EXT-2", "ب", "B", 200)],
                     TENANT, BRANCH, SCOPE, TYPE)
    result2 = reconcile_batch(store, "b2", [_rec("EXT-1", "أ", "A", 100)],  # EXT-2 غاب عن الدفعة
                               TENANT, BRANCH, SCOPE, TYPE)
    counts = result2.counts()
    assert counts[ItemStatus.MISSING_THIS_BATCH.value] == 1
    # يبقى محفوظًا في الـ store، لم يُحذف:
    assert store.get(CatalogKey(TENANT, BRANCH, SCOPE, TYPE, "EXT-2")) is not None


def test_duplicate_sku_different_external_id_is_conflict_not_merge():
    store = CatalogStore()
    reconcile_batch(store, "b1", [_rec("EXT-1", "أ", "A", 100, sku="SKU-9")],
                     TENANT, BRANCH, SCOPE, TYPE)
    result2 = reconcile_batch(store, "b2", [_rec("EXT-2", "أ2", "A2", 150, sku="SKU-9")],
                               TENANT, BRANCH, SCOPE, TYPE)
    conflicts = [i for i in result2.items if i.status == ItemStatus.CONFLICT]
    assert len(conflicts) == 1
    assert conflicts[0].reason == ConflictReason.DUPLICATE_SKU_DIFFERENT_EXTERNAL_ID
    # EXT-2 لم يُكتب فوق EXT-1 بصمت:
    assert store.get(CatalogKey(TENANT, BRANCH, SCOPE, TYPE, "EXT-2")) is None


def test_stale_version_does_not_overwrite_newer_committed_record():
    store = CatalogStore()
    reconcile_batch(store, "b1", [_rec("EXT-1", "جديد", "New", 500, version=3)],
                     TENANT, BRANCH, SCOPE, TYPE)
    result2 = reconcile_batch(store, "b2", [_rec("EXT-1", "قديم", "Old", 100, version=1)],
                               TENANT, BRANCH, SCOPE, TYPE)
    assert result2.counts()[ItemStatus.CONFLICT.value] == 1
    assert store.get(CatalogKey(TENANT, BRANCH, SCOPE, TYPE, "EXT-1")).name_ar == "جديد"


def test_update_when_price_changes():
    store = CatalogStore()
    reconcile_batch(store, "b1", [_rec("EXT-1", "أ", "A", 100, version=1)],
                     TENANT, BRANCH, SCOPE, TYPE)
    result2 = reconcile_batch(store, "b2", [_rec("EXT-1", "أ", "A", 150, version=2)],
                               TENANT, BRANCH, SCOPE, TYPE)
    updated = [i for i in result2.items if i.status == ItemStatus.UPDATED]
    assert len(updated) == 1
    assert updated[0].diff["price_minor_units"] == {"old": 100, "new": 150}


def test_duplicate_external_id_within_same_batch_does_not_create_two_records():
    """اختبار جديد (مراجعة سابعة): لم يُختبر من قبل إطلاقًا. نفس external_id
    يظهر مرتين في نفس استدعاء reconcile_batch (بدل دفعتين منفصلتين). النتيجة
    الفعلية المُتحقَّق منها: الظهور الأول NEW، والثاني UNCHANGED (يقارن مقابل
    ما التزم به الأول توًا داخل نفس الدفعة) — سجل واحد فقط يُخزَّن، لا تضاعف."""
    store = CatalogStore()
    batch = [_rec("EXT-DUP", "أ", "A", 100), _rec("EXT-DUP", "أ", "A", 100)]
    result = reconcile_batch(store, "b1", batch, TENANT, BRANCH, SCOPE, TYPE)
    statuses = [i.status for i in result.items]
    assert statuses == [ItemStatus.NEW, ItemStatus.UNCHANGED]
    assert len(store._committed) == 1


def test_same_version_different_content_is_treated_as_update_not_conflict():
    """اختبار جديد (مراجعة سابعة) يوثّق سلوكًا كان ضمنيًا وغير مُختبر:
    القاعدة الصريحة الوحيدة (D7) هي 'نسخة أقدم لا تكتب فوق أحدث' — أي
    existing.version > incoming.version فقط. الوثيقتان لا تذكران صراحة ماذا
    يحدث عند تساوي رقم الإصدار بمحتوى مختلف. السلوك الفعلي الحالي: يُعامَل
    كـUPDATED عاديّ (يكتب فوق القديم)، وليس CONFLICT. هذا قرار ضمني موثَّق
    الآن صراحة بدل أن يبقى غير مذكور — قد يحتاج مراجعة منتج لاحقًا إن كان
    تساوي الإصدار بمحتوى مختلف يجب أن يُعامَل كإشارة تعارض بدل تحديث عادي."""
    store = CatalogStore()
    reconcile_batch(store, "b1", [_rec("EXT-SV", "قديم", "Old", 100, version=1)],
                     TENANT, BRANCH, SCOPE, TYPE)
    result2 = reconcile_batch(store, "b2", [_rec("EXT-SV", "جديد", "New", 999, version=1)],
                               TENANT, BRANCH, SCOPE, TYPE)
    assert result2.items[0].status == ItemStatus.UPDATED  # يوثّق السلوك الحالي، لا يحكم بصوابه
    assert store.get(CatalogKey(TENANT, BRANCH, SCOPE, TYPE, "EXT-SV")).price_minor_units == 999
