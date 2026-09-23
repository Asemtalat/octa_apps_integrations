#!/usr/bin/env python3
"""
مُشغِّل اختبارات موحَّد — يحل مشكلة حقيقية اكتُشفت بالتجربة الفعلية:

`pytest` من جذر المشروع مباشرة (أول شيء طبيعي يجرّبه أي مطوّر) **يفشل بـ36
خطأ من 53 اختبارًا** — ليس لأن المنطق خاطئ، بل لأن Python يحاول عندئذٍ
استيراد `addons/octa_hub_core/__init__.py` (الموديول الحقيقي الذي يستورد
`odoo` غير المثبَّت) كجزء من حل مسار موديولات الاختبار المجاورة، بسبب تعارض
بين وجود `__init__.py` في بعض مجلدات addons والغيابه في أخرى (`lib/`, `tests/`).
جُرِّب `--import-mode=importlib` كإصلاح بديل فأفسد استيرادات الأشقاء (كل
اختبار يستورد وحدته المجاورة بـ`from x import y` بلا حزمة) بشكل أوسع.

**الحل المُطبَّق هنا: عزل كل مجموعة اختبار في عملية Python منفصلة تمامًا**
(subprocess)، تمامًا كما لو شغّلها مطوّر يدويًا مجلدًا بمجلد — لا محاولة
لحملهم على التعايش داخل مفسّر واحد. هذا يطابق ما توثقه RUNBOOK.md بالفعل،
لكن بأمر واحد قابل لإعادة الاستخدام بدل خمسة أوامر منفصلة.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUITES = [
    "tools/catalog_reconcile",
    "addons/octa_hub_api/lib",
    "tools/mock_pos",
    "addons/octa_hub_connector_demo/tests",
    "addons/octa_hub_core/lib",
]


def main():
    total_passed = 0
    total_failed = 0
    failures = []

    for suite in SUITES:
        suite_path = ROOT / suite
        print(f"\n{'=' * 60}\n{suite}\n{'=' * 60}")
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-v"],
            cwd=str(suite_path),
            capture_output=True, text=True,
        )
        print(result.stdout[-2000:])
        if result.returncode != 0:
            total_failed += 1
            failures.append(suite)
        else:
            total_passed += 1
            # استخرج عدد "passed" من آخر سطر ملخص pytest
        if result.stderr.strip():
            print("STDERR:", result.stderr[-500:])

    print(f"\n{'=' * 60}\nملخص: {total_passed}/{len(SUITES)} مجموعة اجتازت كاملة")
    if failures:
        print("مجموعات فشلت:", failures)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
