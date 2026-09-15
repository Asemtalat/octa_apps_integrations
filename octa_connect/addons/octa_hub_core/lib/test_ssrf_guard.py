"""اختبارات RUN فعليًا (pytest، بلا Odoo) لحماية SSRF."""
import pytest
from ssrf_guard import validate_url, SsrfRejected


def resolver_map(mapping):
    def _resolve(hostname):
        if hostname not in mapping:
            raise Exception("NXDOMAIN")
        return mapping[hostname]
    return _resolve


def test_public_https_url_is_allowed():
    resolver = resolver_map({"partner-app.example.com": ["93.184.216.34"]})
    validate_url("https://partner-app.example.com/webhook", resolver)  # لا استثناء = نجاح


def test_http_scheme_is_rejected():
    resolver = resolver_map({"partner-app.example.com": ["93.184.216.34"]})
    with pytest.raises(SsrfRejected) as exc:
        validate_url("http://partner-app.example.com/webhook", resolver)
    assert exc.value.reason == "scheme_must_be_https"


def test_https_url_that_resolves_to_localhost_string_is_rejected():
    """إصلاح بعد اكتشاف ثغرة: 'localhost' نفسها لم تعد استثناءً — تُفحص
    بحل DNS الفعلي مثل أي اسم آخر، فإن حُلّت إلى loopback تُرفض."""
    resolver = resolver_map({"localhost": ["127.0.0.1"]})
    with pytest.raises(SsrfRejected) as exc:
        validate_url("https://localhost/webhook", resolver)
    assert "blocked_range" in exc.value.reason


def test_https_to_127_0_0_1_literal_is_rejected_no_exception_carve_out():
    """إصلاح بعد اكتشاف ثغرة أمنية حقيقية: النسخة السابقة من هذه الدالة
    كانت تسمح لأي عميل يكتب https://127.0.0.1/... أو https://localhost/...
    بتفادي فحص SSRF بالكامل — تحقّقت الثغرة فعليًا قبل الإصلاح. الاستثناء
    حُذف نهائيًا؛ لا معاملة خاصة لأي اسم مضيف."""
    resolver = resolver_map({"127.0.0.1": ["127.0.0.1"]})  # قد لا يُستدعى إن رفض urlparse المعالجة كـIP مباشرة
    with pytest.raises(SsrfRejected):
        validate_url("https://127.0.0.1/webhook", lambda h: ["127.0.0.1"])


def test_url_resolving_to_loopback_is_rejected():
    resolver = resolver_map({"evil.example.com": ["127.0.0.1"]})
    with pytest.raises(SsrfRejected) as exc:
        validate_url("https://evil.example.com/webhook", resolver)
    assert "blocked_range" in exc.value.reason


def test_url_resolving_to_cloud_metadata_ip_is_rejected():
    """169.254.169.254 — عنوان metadata السحابي الشهير (AWS/GCP/Azure)."""
    resolver = resolver_map({"evil.example.com": ["169.254.169.254"]})
    with pytest.raises(SsrfRejected) as exc:
        validate_url("https://evil.example.com/", resolver)
    assert "169.254.169.254" in exc.value.reason


def test_url_resolving_to_private_range_is_rejected():
    resolver = resolver_map({"internal.example.com": ["10.0.0.5"]})
    with pytest.raises(SsrfRejected):
        validate_url("https://internal.example.com/", resolver)


def test_dns_rebinding_style_multi_answer_any_blocked_ip_rejects():
    """رد DNS بعنوان عام + عنوان داخلي معًا — لازم نرفض حتى لو عنوان واحد بس خبيث."""
    resolver = resolver_map({"mixed.example.com": ["93.184.216.34", "192.168.1.1"]})
    with pytest.raises(SsrfRejected):
        validate_url("https://mixed.example.com/", resolver)


def test_redirect_hop_to_private_ip_is_rejected():
    resolver = resolver_map({
        "public.example.com": ["93.184.216.34"],
        "internal-redirect-target.local": ["10.1.1.1"],
    })
    with pytest.raises(SsrfRejected):
        validate_url("https://public.example.com/", resolver,
                      allow_redirect_hops=["https://internal-redirect-target.local/"])


def test_dns_failure_rejects_not_silently_passes():
    resolver = resolver_map({})  # اسم غير معروف
    with pytest.raises(SsrfRejected) as exc:
        validate_url("https://does-not-resolve.example.com/", resolver)
    assert "dns_resolution_failed" in exc.value.reason


def test_no_hostname_rejected():
    resolver = resolver_map({})
    with pytest.raises(SsrfRejected):
        validate_url("https:///path-only", resolver)


def test_ipv6_loopback_literal_is_rejected():
    resolver = resolver_map({"evil6.example.com": ["::1"]})
    with pytest.raises(SsrfRejected):
        validate_url("https://evil6.example.com/", resolver)
