"""
حماية SSRF (القسم 8/23): "عناوين Webhook التي يدخلها العميل قد تستهدف خدمات
داخلية؛ نتحقق من HTTPS والوجهة وDNS وIPv4/IPv6 وإعادة التوجيه ونمنع عناوين
الشبكات الخاصة والمسارات الحساسة". هذا البند كان NOT_STARTED بالكامل في كل
نسخ التسليم السابقة رغم تكرار ذكره. هذه أول تنفيذ فعلي له، pure Python
ليُختبر بمعزل عن Odoo.

التصميم: دالة resolver قابلة للحقن (dependency injection) بدل استدعاء DNS
حقيقي مباشرة — بيسمح باختبار حتمي وسريع بدون شبكة فعلية، وبيسمح لاحقًا
بربطها بـsocket.getaddrinfo الحقيقي في طبقة Odoo دون تغيير المنطق هنا.
"""
from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

# نطاقات محظورة صراحة (خاصة/محجوزة/loopback/link-local/multicast) — القسم 8
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),      # loopback
    ipaddress.ip_network("10.0.0.0/8"),       # private
    ipaddress.ip_network("172.16.0.0/12"),    # private
    ipaddress.ip_network("192.168.0.0/16"),   # private
    ipaddress.ip_network("169.254.0.0/16"),   # link-local (يشمل AWS/GCP/Azure metadata: 169.254.169.254)
    ipaddress.ip_network("100.64.0.0/10"),    # CGNAT
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),          # loopback v6
    ipaddress.ip_network("fc00::/7"),         # unique local v6
    ipaddress.ip_network("fe80::/10"),        # link-local v6
    ipaddress.ip_network("ff00::/8"),         # multicast v6
]

_MAX_REDIRECTS = 3


class SsrfRejected(Exception):
    def __init__(self, url, reason):
        super().__init__(f"SSRF check rejected {url!r}: {reason}")
        self.url = url
        self.reason = reason


def _ip_is_blocked(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # قيمة غير قابلة للفهم كعنوان — نرفض بحذر، لا نمرر صامتين
    return any(ip in net for net in _BLOCKED_NETWORKS)


def validate_url(url: str, resolver, allow_redirect_hops: list | None = None) -> None:
    """يرفع SsrfRejected إن كان الرابط غير آمن، وإلا لا يُرجع شيئًا (يمر بصمت).

    resolver(hostname) -> list[str] من عناوين IP — حقن التبعية للاختبار.
    allow_redirect_hops: قائمة أهداف إعادة توجيه إضافية (لمحاكاة سلسلة
    التوجيه) تُفحص بنفس القواعد — القسم 8: "منع SSRF... إعادة التوجيه".

    إصلاح حرج بعد مراجعة خامسة: النسخة السابقة من هذه الدالة كانت تحتوي
    استثناءً عامًا غير مشروط لـ`127.0.0.1`/`localhost` (بما فيها مع
    `https://`) بحجة "دعم أدوات الاختبار الداخلية". هذا كان **ثغرة SSRF
    حقيقية وقابلة للاستغلال فعليًا**: هذه الدالة موصولة مباشرة بحقل
    `callback_url` الذي **يُدخله العميل نفسه** (`branch.py`) — فأي عميل
    خبيث كان يقدر يكتب `https://localhost/...` ويتفادى كل الفحص بالكامل
    (لا DNS، لا فحص نطاق) ويجعل خادمنا يستدعي نفسه. تحقّق الثغرة فعليًا
    بتشغيل استدعاء حقيقي قبل الإصلاح (`validate_url("https://localhost/...",
    resolver_يرفض_الاستدعاء)` كان ينجح بصمت). **الاستثناء حُذف بالكامل من
    هذه الدالة العامة** — لا حاجة حقيقية له في أي مسار استدعاء فعلي بالمشروع
    (أداة mock_pos تُستدعى مباشرة في اختباراتها دون المرور بهذه الدالة
    إطلاقًا). لو ظهرت لاحقًا حاجة فعلية لاستثناء بيئة اختبار داخلية، يجب أن
    تكون معاملًا صريحًا (`opt-in` من المستدعي)، لا سلوكًا افتراضيًا صامتًا
    داخل دالة أمان عامة.
    """
    parsed = urlparse(url)

    if parsed.scheme != "https":
        raise SsrfRejected(url, "scheme_must_be_https")

    if not parsed.hostname:
        raise SsrfRejected(url, "no_hostname")

    try:
        resolved_ips = resolver(parsed.hostname)
    except Exception as e:
        raise SsrfRejected(url, f"dns_resolution_failed:{e}")

    if not resolved_ips:
        raise SsrfRejected(url, "dns_resolution_empty")

    for ip in resolved_ips:
        if _ip_is_blocked(ip):
            raise SsrfRejected(url, f"resolved_to_blocked_range:{ip}")

    for hop_url in (allow_redirect_hops or []):
        # كل قفزة إعادة توجيه تخضع لنفس الفحص بالكامل، وليس فقط الرابط الأول
        validate_url(hop_url, resolver)

    if allow_redirect_hops and len(allow_redirect_hops) > _MAX_REDIRECTS:
        raise SsrfRejected(url, "too_many_redirects")
