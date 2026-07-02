"""Canned format / checksum validators for :class:`FormatRuleDef`.

Each validator is a pure ``Callable[[str], bool]`` that takes the raw field value
(already stringified by the interpreter) and returns whether it conforms. Every
validator is TOTAL — it never raises; malformed input simply returns ``False``.

These are best-effort *structural* checks, not authoritative registry lookups: a
value can satisfy the mod-97 / mod-10 arithmetic here yet not correspond to a real
registered identifier. The interpreter skips (emits no check) when the field is
absent, so a validator only ever sees a present, non-null value.
"""

from __future__ import annotations

import re
from collections.abc import Callable

# --- regex-based validators (compiled once) -----------------------------------

_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_URL_RE = re.compile(r"https?://[^\s]+")
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_DIGITS_RE = re.compile(r"\d+")
_ALNUM_RE = re.compile(r"[A-Za-z0-9]+")


def _fullmatch(pattern: re.Pattern[str], value: str) -> bool:
    return pattern.fullmatch(value.strip()) is not None


# --- checksum validators ------------------------------------------------------


def _mod97_ok(value: str) -> bool:
    """ISO 13616 mod-97 structural check (used for the international account format).

    Strip spaces, uppercase, require length 15-34 and a leading 2-letter country +
    2-digit check. Move the first four characters to the end, map each letter A-Z to
    10-35, read the result as one integer and require ``int % 97 == 1``.
    """
    s = value.replace(" ", "").upper()
    if not (15 <= len(s) <= 34) or not s[:2].isalpha() or not s[2:4].isdigit():
        return False
    if not s.isalnum():
        return False
    rearranged = s[4:] + s[:4]
    digits: list[str] = []
    for ch in rearranged:
        if ch.isdigit():
            digits.append(ch)
        elif "A" <= ch <= "Z":
            digits.append(str(ord(ch) - 55))  # A -> 10 ... Z -> 35
        else:
            return False
    try:
        return int("".join(digits)) % 97 == 1
    except ValueError:  # pragma: no cover - guarded by isalnum above
        return False


def _mod10_ok(value: str) -> bool:
    """Generic mod-10 checksum over a digit string (spaces/hyphens ignored).

    Requires at least two digits and an all-digit body once separators are removed.
    """
    s = value.replace(" ", "").replace("-", "")
    if len(s) < 2 or not s.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(s)):
        d = ord(ch) - 48
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# --- reference-data sets (uppercase codes) ------------------------------------

# ISO 3166-1 alpha-2 assigned codes.
_COUNTRY_A2 = frozenset(
    "AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL "
    "BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV "
    "CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD "
    "GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM "
    "IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK "
    "LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW "
    "MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR "
    "PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS "
    "ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY "
    "UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW".split()
)

# ISO 4217 active alpha-3 currency codes.
_CURRENCY_A3 = frozenset(
    "AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BRL "
    "BSD BTN BWP BYN BZD CAD CDF CHF CLP CNY COP CRC CUP CVE CZK DJF DKK DOP DZD EGP "
    "ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF GTQ GYD HKD HNL HRK HTG HUF IDR ILS "
    "INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT LAK LBP LKR LRD "
    "LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MYR MZN NAD NGN NIO NOK "
    "NPR NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK "
    "SGD SHP SLE SLL SOS SRD SSP STN SVC SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS "
    "UAH UGX USD UYU UZS VES VND VUV WST XAF XCD XOF XPF YER ZAR ZMW ZWL".split()
)


def _in_set(codes: frozenset[str]) -> Callable[[str], bool]:
    return lambda value: value.strip().upper() in codes


# --- registry -----------------------------------------------------------------

FORMAT_VALIDATORS: dict[str, Callable[[str], bool]] = {
    "iban": _mod97_ok,
    "luhn": _mod10_ok,
    "email": lambda v: _fullmatch(_EMAIL_RE, v),
    "url": lambda v: _fullmatch(_URL_RE, v),
    "uuid": lambda v: _fullmatch(_UUID_RE, v),
    "digits": lambda v: _fullmatch(_DIGITS_RE, v),
    "alphanumeric": lambda v: _fullmatch(_ALNUM_RE, v),
    "iso_country": _in_set(_COUNTRY_A2),
    "iso_currency": _in_set(_CURRENCY_A3),
}

FORMAT_KEYS: tuple[str, ...] = tuple(sorted(FORMAT_VALIDATORS))

__all__ = ["FORMAT_VALIDATORS", "FORMAT_KEYS"]
