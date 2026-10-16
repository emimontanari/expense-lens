from datetime import date

import pytest
from expense_lens.normalize import (
    cuit_is_valid,
    normalize_amount,
    normalize_cuit,
    normalize_currency,
    normalize_date,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1.234,56", "1234.56"),
        ("$ 1.234,56", "1234.56"),
        ("12.345.678,9", "12345678.9"),
        ("1234,56", "1234.56"),
        ("0,50", "0.50"),
        ("1,234.56", "1234.56"),
        ("1234.56", "1234.56"),
        ("121", "121"),
        ("12.345.678", "12345678"),
        ("US$ 99,90", "99.90"),
        ("-150,00", "150.00"),
        ("(150,00)", "150.00"),
    ],
)
def test_normalizes_argentine_and_canonical_amounts(raw, expected):
    assert normalize_amount(raw) == (expected, None)


@pytest.mark.parametrize("raw", ["1.234", "1,234"])
def test_single_three_digit_group_is_ambiguous_not_guessed(raw):
    assert normalize_amount(raw) == (None, "ambiguous_amount")


@pytest.mark.parametrize(
    "raw", ["1,2345", "12.34.56", "abc", "1.23,4.5", "10000000000,00", "1e2"]
)
def test_unparseable_amounts_become_null(raw):
    assert normalize_amount(raw) == (None, "unparseable_amount")


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_absent_amount_has_no_issue(raw):
    assert normalize_amount(raw) == (None, None)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026-10-15", date(2026, 10, 15)),
        ("15/10/2026", date(2026, 10, 15)),
        ("5/3/2026", date(2026, 3, 5)),
    ],
)
def test_normalizes_day_first_dates(raw, expected):
    assert normalize_date(raw) == (expected, None)


@pytest.mark.parametrize("raw", ["30/02/2026", "10/15/2026", "ayer"])
def test_invalid_dates_become_null(raw):
    assert normalize_date(raw) == (None, "invalid_date")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("ARS", ("ARS", None)),
        ("pesos", ("ARS", None)),
        ("$", ("ARS", "currency_inferred_from_symbol")),
        ("US$", ("USD", None)),
        ("U$S", ("USD", None)),
        ("usd", ("USD", None)),
        ("€", ("EUR", None)),
        ("BRL", (None, "unknown_currency")),
        (None, (None, None)),
    ],
)
def test_normalizes_currency_without_converting(raw, expected):
    assert normalize_currency(raw) == expected


def test_cuit_checksum_uses_official_weights():
    assert cuit_is_valid("30000000007")
    assert cuit_is_valid("20123456786")
    assert not cuit_is_valid("20123456780")
    assert not cuit_is_valid("2012345678")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("30-00000000-7", ("30000000007", None)),
        ("30 00000000 7", ("30000000007", None)),
        ("20-12345678-0", (None, "invalid_cuit")),
        ("123", (None, "invalid_cuit")),
        (None, (None, None)),
    ],
)
def test_normalizes_cuit(raw, expected):
    assert normalize_cuit(raw) == expected
