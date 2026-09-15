"""
فحص تباين WCAG فعلي لأزواج ألوان design_tokens.scss (جدول 3 الملزم في
الوثيقة الأصلية). قابل لإعادة التشغيل: `python3 contrast_check.py`.

لم يكن هذا الفحص موجودًا في أي تسليم سابق رغم أن design_tokens.scss يحمل
تعليقًا يقول "تُختبر تباينها الفعلي، وليست ادعاء اجتياز معيار وصول" — هذا
أول تنفيذ فعلي لذلك الاختبار الموعود.
"""


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def relative_luminance(rgb):
    def chan(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast_ratio(hex1, hex2):
    l1 = relative_luminance(hex_to_rgb(hex1))
    l2 = relative_luminance(hex_to_rgb(hex2))
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


# كل زوج نص/خلفية مستخدم فعليًا في design_tokens.scss + الأزرار/الشارات
PAIRS = [
    ("النص الأساسي على الخلفية", "#172B4D", "#F6F8FB"),
    ("النص الأساسي على السطح الأبيض", "#172B4D", "#FFFFFF"),
    ("زر أساسي (نص أبيض على primary)", "#FFFFFF", "#2457C5"),
    ("نجاح: نص على خلفية badge", "#167548", "#E6F4EC"),
    ("تحذير: نص على خلفية badge", "#8A5700", "#FBF1DF"),
    ("خطر: نص على خلفية badge", "#B42318", "#FBE9E7"),
    ("نص مكتوم على الخلفية", "#5A6B8C", "#F6F8FB"),
    ("شريط بيئة الاختبار (أبيض على warning)", "#FFFFFF", "#8A5700"),
]

WCAG_AA_NORMAL = 4.5
WCAG_AA_LARGE_OR_UI = 3.0

if __name__ == "__main__":
    print(f"{'الزوج':45s} {'النسبة':>8s} {'AA عادي':>10s} {'AA كبير/UI':>12s}")
    all_pass = True
    for label, fg, bg in PAIRS:
        ratio = contrast_ratio(fg, bg)
        p_normal = ratio >= WCAG_AA_NORMAL
        p_large = ratio >= WCAG_AA_LARGE_OR_UI
        all_pass = all_pass and p_normal
        print(f"{label:45s} {ratio:8.2f} {'PASS' if p_normal else 'FAIL':>10s} {'PASS' if p_large else 'FAIL':>12s}")
    print()
    print("كل الأزواج تجتاز AA للنص العادي (4.5:1)" if all_pass else "تحذير: زوج واحد أو أكثر لا يجتاز AA للنص العادي")
