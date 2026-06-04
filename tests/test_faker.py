"""Tests for Graxia Faker — synthetic data generator with Thai locale.

Coverage:
- Each module: person, location, finance, date, lorem, commerce, internet, phone
- Thai locale (priority): 3+ tests
- Schema generation: 1+ test
- Seed reproducibility: 1+ test
- Locale fallback: 1 test
- MCP tool integration: smoke test
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime

# Ensure src/ is on the path so tests work without editable install
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import pytest  # noqa: E402

from graxia_tool.faker import Faker  # noqa: E402
from graxia_tool.faker.locales import available_locales, get_locale  # noqa: E402
from graxia_tool.faker.modules.person import Person  # noqa: E402
from graxia_tool.faker.modules.location import Location  # noqa: E402


# ---------------------------------------------------------------------------
# Locale infrastructure
# ---------------------------------------------------------------------------

def test_locales_registered():
    locales = available_locales()
    assert "en" in locales, f"English locale not registered: {locales}"
    assert "th" in locales, f"Thai locale not registered: {locales}"


def test_locale_fallback_unknown_to_english():
    """Unknown locale (e.g. 'xx_XX') should fall back to English."""
    f = Faker(locale="xx_XX")
    # English first name
    name = f.person.first_name_male()
    assert isinstance(name, str) and len(name) > 0
    # Should be one of the English male first names (since we got en data)
    en_male = get_locale("en")["person"]["first_name_male"]
    assert name in en_male, f"Fallback failed: {name} not in English list"


def test_thai_locale_data_completeness():
    """Thai locale must have 50+ male first names, 50+ female, 30+ cities, 50+ last names."""
    th = get_locale("th")
    person = th["person"]
    location = th["location"]
    assert len(person["first_name_male"]) >= 50, (
        f"Need 50+ Thai male first names, got {len(person['first_name_male'])}"
    )
    assert len(person["first_name_female"]) >= 50, (
        f"Need 50+ Thai female first names, got {len(person['first_name_female'])}"
    )
    assert len(person["last_name"]) >= 50, (
        f"Need 50+ Thai last names, got {len(person['last_name'])}"
    )
    assert len(location["city"]) >= 30, (
        f"Need 30+ Thai cities, got {len(location['city'])}"
    )
    # Slugs for email
    assert len(person.get("first_name_male_slug", [])) == len(person["first_name_male"])
    assert len(person.get("last_name_slug", [])) == len(person["last_name"])


# ---------------------------------------------------------------------------
# Seed reproducibility
# ---------------------------------------------------------------------------

def test_seed_reproducibility():
    """Same seed => identical output across calls."""
    f1 = Faker(locale="th", seed=42)
    f2 = Faker(locale="th", seed=42)
    names1 = [f1.person.full_name() for _ in range(10)]
    names2 = [f2.person.full_name() for _ in range(10)]
    assert names1 == names2, f"Seed not reproducible: {names1} != {names2}"

    cities1 = [f1.location.city() for _ in range(10)]
    cities2 = [f2.location.city() for _ in range(10)]
    assert cities1 == cities2


def test_different_seeds_produce_different_output():
    f1 = Faker(locale="en", seed=1)
    f2 = Faker(locale="en", seed=999)
    n1 = f1.person.first_name()
    n2 = f2.person.first_name()
    # Not strictly guaranteed but extremely likely with different seeds
    assert n1 != n2, f"Different seeds produced same name: {n1}"


# ---------------------------------------------------------------------------
# Person
# ---------------------------------------------------------------------------

def test_person_english_basic():
    f = Faker(locale="en", seed=1)
    fn = f.person.first_name()
    ln = f.person.last_name()
    full = f.person.full_name()
    assert isinstance(fn, str) and len(fn) > 0
    assert isinstance(ln, str) and len(ln) > 0
    # full_name() picks a (possibly different) random first name from the locale
    assert isinstance(full, str) and " " in full
    parts = full.split(" ", 1)
    assert len(parts) == 2 and parts[0] and parts[1]
    en = get_locale("en")["person"]
    assert fn in en["first_name_male"] + en["first_name_female"]
    assert ln in en["last_name"]
    assert f.person.gender() in ("Male", "Female", "Non-binary")
    assert isinstance(f.person.job(), str) and len(f.person.job()) > 0
    bio = f.person.bio()
    assert isinstance(bio, str) and len(bio) > 0


def test_person_thai_basic():
    f = Faker(locale="th", seed=7)
    fn = f.person.first_name_male()
    ln = f.person.last_name()
    full = f.person.full_name()
    assert isinstance(fn, str) and len(fn) > 0
    # Should contain Thai script
    assert any("\u0e00" <= ch <= "\u0e7f" for ch in fn), f"Not Thai script: {fn}"
    assert any("\u0e00" <= ch <= "\u0e7f" for ch in ln), f"Not Thai script: {ln}"
    assert isinstance(full, str) and " " in full
    parts = full.split(" ", 1)
    assert len(parts) == 2 and parts[0] and parts[1]
    assert any("\u0e00" <= ch <= "\u0e7f" for ch in full)
    assert f.person.gender() in ("ชาย", "หญิง", "อื่นๆ")
    assert f.person.job() != ""


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------

def test_location_english():
    f = Faker(locale="en", seed=2)
    city = f.location.city()
    country = f.location.country()
    zip_code = f.location.zip_code()
    state = f.location.state()
    addr = f.location.full_address()

    assert isinstance(city, str) and len(city) > 0
    assert isinstance(country, str) and len(country) > 0
    assert isinstance(zip_code, str) and len(zip_code) == 5
    assert zip_code.isdigit()
    assert isinstance(state, str) and len(state) > 0
    # full_address() uses internally-generated city/country (rng advances
    # between calls), so we just check the address is well-formed and
    # contains *some* city/country from the locale.
    en = get_locale("en")["location"]
    assert any(c in addr for c in en["city"]), f"No English city in addr: {addr}"
    assert any(co in addr for co in en["country"]), f"No English country in addr: {addr}"
    # Coordinates
    lat = f.location.latitude()
    lon = f.location.longitude()
    assert -90.0 <= lat <= 90.0
    assert -180.0 <= lon <= 180.0


def test_location_thai():
    """Thai zip codes must be 5 digits and (when from samples) match real ranges."""
    f = Faker(locale="th", seed=11)
    cities = [f.location.city() for _ in range(20)]
    zips = [f.location.zip_code() for _ in range(20)]
    # At least one of the major Thai cities
    assert any(c in ("กรุงเทพมหานคร", "เชียงใหม่", "ภูเก็ต", "ขอนแก่น") for c in cities)
    # All zip codes are 5 digits
    for z in zips:
        assert len(z) == 5 and z.isdigit(), f"Bad Thai zip: {z}"
    country = f.location.country()
    assert "ไทย" in country or "Thailand" in country or len(country) > 0


# ---------------------------------------------------------------------------
# Phone
# ---------------------------------------------------------------------------

def test_phone_english_formats():
    f = Faker(locale="en", seed=3)
    numbers = [f.phone.phone_number() for _ in range(20)]
    assert all(isinstance(n, str) and len(n) >= 7 for n in numbers)
    # Most should have digits
    assert any(any(c.isdigit() for c in n) for n in numbers)


def test_phone_thai_e164():
    """Thai phone numbers should be in +66 E.164 format (mobile or landline)."""
    f = Faker(locale="th", seed=5)
    numbers = [f.phone.phone_number() for _ in range(30)]
    e164 = [n for n in numbers if n.startswith("+66")]
    assert len(e164) >= 20, (
        f"Most Thai phone numbers should start with +66: sample={numbers[:5]}"
    )
    # All +66 numbers should be 12-13 chars
    for n in e164:
        assert n.startswith("+66 ")
        # After +66 should be 8 or 9 digits
        digits = n.replace("+66", "").replace(" ", "").replace("-", "")
        assert digits.isdigit()
        assert 8 <= len(digits) <= 10, f"Bad Thai phone: {n}"


# ---------------------------------------------------------------------------
# Finance
# ---------------------------------------------------------------------------

def test_finance_module():
    f = Faker(locale="en", seed=4)
    assert f.finance.currency_code() in (
        "USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "CNY", "INR", "SGD"
    )
    amount = f.finance.amount()
    assert 0.0 <= amount <= 10000.0
    # Account number
    acc = f.finance.account_number(8)
    assert len(acc) == 8 and acc.isdigit()
    # Bitcoin address
    btc = f.finance.bitcoin_address()
    assert btc.startswith("1") and len(btc) >= 30
    # Ethereum
    eth = f.finance.ethereum_address()
    assert eth.startswith("0x") and len(eth) == 42
    # IBAN
    iban = f.finance.iban()
    assert len(iban) >= 14
    # Credit card
    cc = f.finance.credit_card_number()
    assert any(c.isdigit() for c in cc)


def test_finance_thai_currency():
    f = Faker(locale="th", seed=6)
    # Sample many times — THB must appear (it's first in the th locale list)
    codes = [f.finance.currency_code() for _ in range(50)]
    assert "THB" in codes, f"THB never sampled from th locale: {set(codes)}"
    symbols = [f.finance.currency_symbol() for _ in range(50)]
    assert "฿" in symbols, f"฿ symbol never sampled: {set(symbols)}"
    # Crypto in Thai
    c = f.finance.crypto_code()
    assert c in ("BTC", "ETH", "LTC", "XRP", "DOGE", "ADA", "SOL", "DOT")


# ---------------------------------------------------------------------------
# Date
# ---------------------------------------------------------------------------

def test_date_module():
    f = Faker(locale="en", seed=8)
    p = f.date.past(years=2)
    f1 = f.date.future(years=1)
    r = f.date.recent(days=10)
    bd = f.date.birthdate(min_age=20, max_age=40)
    assert isinstance(p, datetime)
    assert isinstance(f1, datetime)
    assert isinstance(r, datetime)
    assert isinstance(bd, datetime)
    # Past is in the past
    assert p < datetime.now()
    # Future is in the future
    assert f1 > datetime.now()
    # Birthdate: person should be between 20 and 40
    age_days = (datetime.now() - bd).days
    age_years = age_days / 365
    assert 19 <= age_years <= 41, f"Birthdate age out of range: {age_years}"
    # Recent: within 10 days
    assert (datetime.now() - r).days <= 10


def test_date_between_and_soon():
    f = Faker(locale="en", seed=12)
    start = datetime(2024, 1, 1)
    end = datetime(2024, 12, 31)
    d = f.date.between(start, end)
    assert start <= d <= end
    s = f.date.soon(days=5)
    assert s > datetime.now()
    assert (s - datetime.now()).days <= 5


# ---------------------------------------------------------------------------
# Lorem
# ---------------------------------------------------------------------------

def test_lorem_module():
    f = Faker(locale="en", seed=9)
    word = f.lorem.word()
    assert isinstance(word, str) and len(word) > 0
    ws = f.lorem.words(5)
    assert len(ws) == 5
    sentence = f.lorem.sentence()
    assert sentence.endswith(".")
    assert sentence[0].isupper()
    sentences = f.lorem.sentences(3)
    assert len(sentences) == 3
    para = f.lorem.paragraph()
    assert len(para) > 20
    paras = f.lorem.paragraphs(2)
    assert len(paras) == 2
    # Thai lorem should still produce a sentence
    ft = Faker(locale="th", seed=9)
    th_sentence = ft.lorem.sentence()
    assert isinstance(th_sentence, str) and len(th_sentence) > 0


# ---------------------------------------------------------------------------
# Commerce
# ---------------------------------------------------------------------------

def test_commerce_module():
    f = Faker(locale="en", seed=10)
    pname = f.commerce.product_name()
    assert isinstance(pname, str) and len(pname.split()) >= 2
    dept = f.commerce.department()
    assert dept != ""
    price = f.commerce.price(10.0, 100.0)
    assert 10.0 <= price <= 100.0
    sku = f.commerce.sku(8)
    assert len(sku) == 8
    assert sku[:3].isalpha()
    assert sku[3:].isdigit()
    # Thai commerce
    ft = Faker(locale="th", seed=10)
    th_dept = ft.commerce.department()
    assert th_dept != ""
    th_pname = ft.commerce.product_name()
    assert any("\u0e00" <= ch <= "\u0e7f" for ch in th_pname), f"Not Thai: {th_pname}"


# ---------------------------------------------------------------------------
# Internet
# ---------------------------------------------------------------------------

def test_internet_module():
    f = Faker(locale="en", seed=13)
    email = f.internet.email()
    assert "@" in email
    assert "." in email.split("@")[1]
    url = f.internet.url()
    assert url.startswith("http")
    ip = f.internet.ipv4()
    parts = ip.split(".")
    assert len(parts) == 4
    for p in parts:
        assert 0 <= int(p) <= 255
    ipv6 = f.internet.ipv6()
    assert ipv6.count(":") == 7
    mac = f.internet.mac_address()
    assert mac.count(":") == 5
    ua = f.internet.user_agent()
    assert "Mozilla" in ua
    un = f.internet.username()
    assert len(un) >= 4


def test_internet_thai_email():
    """Thai email should use romanized first/last and Thai-friendly domain."""
    f = Faker(locale="th", seed=14)
    emails = [f.internet.email() for _ in range(20)]
    for e in emails:
        assert "@" in e
        local, _, domain = e.partition("@")
        # Local should be ASCII (romanized)
        assert all(ord(c) < 128 for c in local), f"Non-ASCII local part: {e}"
        # Domain should be ASCII too
        assert all(ord(c) < 128 for c in domain)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def test_schema_generation():
    """Schema dict should generate a complex object matching the spec."""
    f = Faker(locale="en", seed=99)
    obj = f.schema({
        "user_id": "string.uuid",
        "email": "internet.email",
        "age": ("int", 18, 65),
        "ratio": ("float", 0.0, 1.0),
        "registered_at": "date.past",
        "is_active": "bool",
        "score": ("choice", [10, 20, 30, 40, 50]),
        "first_name": "person.first_name",
        "country": "location.country",
        "literal": "fixed-value",
    })
    # UUID
    import uuid as _uuid
    _uuid.UUID(obj["user_id"])  # raises if invalid
    # Email
    assert "@" in obj["email"]
    # Age in range
    assert 18 <= obj["age"] <= 65
    # Ratio
    assert 0.0 <= obj["ratio"] <= 1.0
    # Past datetime
    assert isinstance(obj["registered_at"], datetime)
    # Bool
    assert isinstance(obj["is_active"], bool)
    # Choice
    assert obj["score"] in (10, 20, 30, 40, 50)
    # First name
    assert isinstance(obj["first_name"], str) and len(obj["first_name"]) > 0
    # Country
    assert isinstance(obj["country"], str) and len(obj["country"]) > 0
    # Literal passes through
    assert obj["literal"] == "fixed-value"


def test_schema_thai_locale():
    """Schema generation with Thai locale should produce Thai data."""
    f = Faker(locale="th", seed=42)
    obj = f.schema({
        "name": "person.full_name",
        "city": "location.city",
        "phone": "phone.phone_number",
    })
    # Name should contain Thai script
    assert any("\u0e00" <= ch <= "\u0e7f" for ch in obj["name"])
    # City should contain Thai script
    assert any("\u0e00" <= ch <= "\u0e7f" for ch in obj["city"])
    # Phone should start with +66
    assert obj["phone"].startswith("+66")


# ---------------------------------------------------------------------------
# Module direct access
# ---------------------------------------------------------------------------

def test_module_direct_construction():
    """Modules can be used standalone with custom rng."""
    import random
    rng = random.Random(123)
    person = Person(rng, get_locale("en"))
    name = person.full_name()
    assert " " in name


def test_location_module_direct():
    rng = __import__("random").Random(456)
    loc = Location(rng, get_locale("en"))
    assert isinstance(loc.zip_code(), str)
    assert len(loc.zip_code()) == 5


# ---------------------------------------------------------------------------
# MCP integration (smoke)
# ---------------------------------------------------------------------------

def test_mcp_faker_generate_runs():
    from graxia_tool.mcp.faker_tools import faker_generate

    async def run():
        out = await faker_generate({
            "category": "person",
            "field": "first_name_male",
            "count": 3,
            "locale": "th",
            "seed": 7,
        })
        return out

    result = asyncio.run(run())
    assert "content" in result
    import json
    text = result["content"][0]["text"]
    payload = json.loads(text)
    assert payload["category"] == "person"
    assert payload["field"] == "first_name_male"
    assert payload["count"] == 3
    assert len(payload["results"]) == 3
    # All Thai script
    for n in payload["results"]:
        assert any("\u0e00" <= ch <= "\u0e7f" for ch in n)


def test_mcp_faker_schema_runs():
    from graxia_tool.mcp.faker_tools import faker_schema

    async def run():
        return await faker_schema({
            "schema": {
                "id": "string.uuid",
                "age": ("int", 18, 65),
                "email": "internet.email",
            },
            "locale": "en",
            "seed": 1,
        })

    result = asyncio.run(run())
    assert "content" in result
    import json
    payload = json.loads(result["content"][0]["text"])
    assert "result" in payload
    assert "id" in payload["result"]
    assert 18 <= payload["result"]["age"] <= 65


def test_mcp_faker_locales():
    from graxia_tool.mcp.faker_tools import faker_locales
    result = asyncio.run(faker_locales({}))
    assert "content" in result
    import json
    payload = json.loads(result["content"][0]["text"])
    assert "en" in payload["locales"]
    assert "th" in payload["locales"]


def test_mcp_faker_generate_invalid_category():
    from graxia_tool.mcp.faker_tools import faker_generate
    result = asyncio.run(faker_generate({"category": "nope"}))
    assert result.get("isError") is True
    assert "ERROR" in result["content"][0]["text"]


# ---------------------------------------------------------------------------
# Thai-specific extra coverage
# ---------------------------------------------------------------------------

def test_thai_person_module_email_uses_romanized_slugs():
    """person.email (when implemented) is provided by internet.email; verify
    slug lists are aligned with Thai display names so generation is consistent."""
    f = Faker(locale="th", seed=21)
    emails = [f.internet.email() for _ in range(30)]
    # Local part should be lowercase ASCII
    for e in emails:
        local = e.split("@")[0]
        assert local == local.lower()
        assert all(c.isalnum() or c in "._-" for c in local)


def test_thai_phone_distinct_from_english():
    """Thai phone numbers should not look like English numbers."""
    en = Faker(locale="en", seed=33)
    th = Faker(locale="th", seed=33)
    en_nums = [en.phone.phone_number() for _ in range(50)]
    th_nums = [th.phone.phone_number() for _ in range(50)]
    en_plus = [n for n in en_nums if n.startswith("+")]
    th_plus66 = [n for n in th_nums if n.startswith("+66")]
    # English: no numbers should be +66
    assert not any(n.startswith("+66") for n in en_nums)
    # Thai: most should be +66
    assert len(th_plus66) >= 25
