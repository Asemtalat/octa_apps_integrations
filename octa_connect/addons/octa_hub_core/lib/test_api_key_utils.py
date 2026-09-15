"""اختبارات RUN فعليًا لإصدار وتجزئة مفاتيح API (R05)."""
from api_key_utils import generate_api_key, hash_api_key, looks_like_a_valid_key_format


def test_generated_key_and_fingerprint_are_different_and_deterministic():
    raw, fingerprint = generate_api_key()
    assert raw != fingerprint  # البصمة ليست نسخة من المفتاح الخام
    assert hash_api_key(raw) == fingerprint  # نفس المفتاح ينتج نفس البصمة دائمًا


def test_different_keys_produce_different_fingerprints():
    raw1, fp1 = generate_api_key()
    raw2, fp2 = generate_api_key()
    assert raw1 != raw2
    assert fp1 != fp2


def test_fingerprint_cannot_be_reversed_trivially_is_fixed_length_hex():
    _raw, fingerprint = generate_api_key()
    assert len(fingerprint) == 64  # sha256 hex digest
    int(fingerprint, 16)  # كل الأحرف hex صالحة، لا استثناء


def test_short_or_empty_input_rejected_by_format_check():
    assert looks_like_a_valid_key_format("") is False
    assert looks_like_a_valid_key_format("short") is False


def test_real_generated_key_passes_format_check():
    raw, _fingerprint = generate_api_key()
    assert looks_like_a_valid_key_format(raw) is True
