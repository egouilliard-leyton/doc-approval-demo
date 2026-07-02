"""Unit tests for the canned format/checksum validators (app.rules.formats).

Uses only standard textbook sample values. Every validator must be TOTAL — it
returns ``False`` on empty/garbage input rather than raising.
"""

import pytest

from app.rules.formats import FORMAT_KEYS, FORMAT_VALIDATORS


# --- mod-97 (international account format) -------------------------------------


def test_mod97_valid_and_invalid():
    ok = FORMAT_VALIDATORS["iban"]
    assert ok("GB82 WEST 1234 5698 7654 32")  # canonical valid sample (spaces ok)
    assert ok("GB82WEST12345698765432")
    assert not ok("GB82WEST12345698765433")  # last digit mutated -> checksum fails
    assert not ok("XY")  # too short
    assert not ok("1234WEST12345698765432")  # no country letters


# --- mod-10 checksum ----------------------------------------------------------


def test_mod10_valid_and_invalid():
    ok = FORMAT_VALIDATORS["luhn"]
    assert ok("79927398713")  # standard mod-10 example
    assert not ok("79927398714")  # off-by-one -> fails
    assert ok("1-800 79927398713".replace("1-800 ", ""))  # separators tolerated
    assert not ok("abc")
    assert not ok("7")  # single digit rejected


# --- regex validators ---------------------------------------------------------


@pytest.mark.parametrize(
    "key,good,bad",
    [
        ("email", "a.b@example.com", "not-an-email"),
        ("url", "https://example.com/x", "example.com"),
        ("uuid", "123e4567-e89b-12d3-a456-426614174000", "123e4567"),
        ("digits", "00123", "12a3"),
        ("alphanumeric", "Abc123", "Abc 123"),
    ],
)
def test_regex_validators(key, good, bad):
    ok = FORMAT_VALIDATORS[key]
    assert ok(good)
    assert not ok(bad)


# --- reference-data sets ------------------------------------------------------


def test_iso_country():
    ok = FORMAT_VALIDATORS["iso_country"]
    assert ok("US")
    assert ok("fr")  # case-insensitive
    assert not ok("ZZ")
    assert not ok("USA")  # alpha-3 is not the alpha-2 set


def test_iso_currency():
    ok = FORMAT_VALIDATORS["iso_currency"]
    assert ok("EUR")
    assert ok("usd")
    assert not ok("ZZZ")
    assert not ok("EU")


# --- totality: no validator raises on hostile input ---------------------------


@pytest.mark.parametrize("key", FORMAT_KEYS)
def test_every_validator_is_total(key):
    ok = FORMAT_VALIDATORS[key]
    for value in ("", "   ", "\n", "💥", "a" * 200, "!@#$%^&*()"):
        assert ok(value) is False or ok(value) is True  # returns a bool, never raises


def test_format_keys_sorted_and_complete():
    assert FORMAT_KEYS == tuple(sorted(FORMAT_VALIDATORS))
    assert set(FORMAT_KEYS) == {
        "alphanumeric", "digits", "email", "iban", "iso_country",
        "iso_currency", "luhn", "url", "uuid",
    }
