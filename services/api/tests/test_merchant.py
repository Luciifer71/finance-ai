"""Merchant normalization (handoff 6.12): table-driven, synthetic descriptions."""

import pytest

from app.domain.merchant import contains_word, normalize_merchant


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("UPI/SWIGGY/402711112222/FOOD", "SWIGGY FOOD"),
        ("UPI/AMAZON/402711116666/ORDER", "AMAZON"),
        ("UPI/AMAZON/402711117777/REFUND", "AMAZON"),
        ("upi/swiggy/402711112222/swiggy@ybl/Payment", "SWIGGY"),
        ("UPI-ZOMATO-zomato@okaxis-402711119999", "ZOMATO"),
        ("UPI/BLINKIT/402711113333/GROCERY", "BLINKIT GROCERY"),
        ("NEFT/RENT/LANDLORD SYNTH", "RENT LANDLORD SYNTH"),
        ("IMPS/SELF/OWN A/C 4321", "SELF OWN"),
        ("ATM CASH WDL MG ROAD", "CASH WDL MG"),
        ("POS 412345XXXXXX6789 BIGBAZAAR BLR", "XXXXXX6789 BIGBAZAAR BLR"),
        ("ACH D- NETFLIX ENTERTAINMENT-NFLX12345678", "NETFLIX ENTERTAINMENT NFLX"),
        ("NACH/SPOTIFY INDIA/SUBSCRIPTION", "SPOTIFY INDIA SUBSCRIPTION"),
        ("UPI/UBER/402711114444/RIDE", "UBER RIDE"),
        ("UPI/OLA CABS/402711121111/RIDE", "OLA CABS RIDE"),
        ("SALARY OCT ACME SYNTHETIC LTD", "SALARY OCT ACME"),
        ("INTEREST CREDIT", "INTEREST"),
        ("ELECTRICITY BILL BESCOM SYNTH", "ELECTRICITY BILL BESCOM"),
        ("  upi   /  chai   point  ", "CHAI POINT"),
        ("UPI/CHAI POINT/402700001111", "CHAI POINT"),
        ("BIL/ONL/000123456/AIRTEL PREPAID", "AIRTEL PREPAID"),
        ("RTGS CR-SYNTH CORP LTD-UTIB0000123", "SYNTH CORP LTD"),
        ("Payment to merchant@paytm", "MERCHANT"),
        ("123456789012", ""),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_merchant(description: str | None, expected: str):
    assert normalize_merchant(description) == expected


def test_purchase_and_refund_share_a_merchant():
    assert normalize_merchant("UPI/MYNTRA/402799990001/ORDER") == normalize_merchant(
        "UPI/MYNTRA/402799990002/REFUND"
    )


def test_normalization_is_stable_under_case_and_spacing():
    assert normalize_merchant("UPI/Swiggy/402711112222") == normalize_merchant(
        "upi / SWIGGY / 402711113333"
    )


@pytest.mark.parametrize(
    ("text", "word", "found"),
    [
        ("IMPS/SELF/OWN A/C 4321", "SELF", True),
        ("IMPS/SELFIE STUDIO", "SELF", False),
        ("TRANSFER TO OWN A/C", "OWN A/C", True),
        ("UPI 402711114321", "4321", False),  # part of a longer number
        ("TO A/C XX4321 SAVINGS", "4321", True),
        ("COCA COLA", "OLA", False),
        ("OLA CABS", "OLA", True),
    ],
)
def test_contains_word(text: str, word: str, found: bool):
    assert contains_word(text, word) is found
