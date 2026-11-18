"""Merchant normalization (handoff section 6.12), shared by rules, refunds and recurring.

Bank narrations are noisy: "UPI/SWIGGY/402711112222/swiggy@ybl/Payment" and
"UPI-SWIGGY-ORDER" are the same merchant. ``normalize_merchant`` keeps the
part that names who was paid:

1. upper-case;
2. drop the provider part of UPI handles (``@ybl``, ``@okaxis``...) and the ``UPI`` marker;
3. drop reference numbers (any run of 6+ digits);
4. split on anything that is not a letter or digit, collapse spaces;
5. drop filler words (payment channels, "PAYMENT", "REFUND", ...), single
   characters, short numbers and repeated tokens;
6. keep the first 3 remaining tokens.

So a purchase "UPI/AMAZON/402711116666/ORDER" and its refund
"UPI/AMAZON/402711117777/REFUND" both normalize to "AMAZON".
"""

import re

# The provider part of a UPI handle ("@ybl", "@okaxis"); the name before "@" is kept.
_HANDLE_SUFFIX = re.compile(r"@[A-Z][A-Z0-9.]*", re.IGNORECASE)
_LONG_DIGITS = re.compile(r"\d{6,}")
_SEPARATORS = re.compile(r"[^A-Z0-9]+")

# Words that describe the payment channel or the direction, not the merchant.
FILLER_WORDS = frozenset(
    {
        "UPI", "IMPS", "NEFT", "RTGS", "ACH", "NACH", "ECS", "POS", "ATM", "INB", "MB", "IB",
        "BIL", "BILLPAY", "ONL", "TXN", "TRANSACTION", "REF", "NO", "PAYMENT", "PAY", "PAID",
        "TO", "FROM", "BY", "FOR", "VIA", "THE", "AND", "OF", "DR", "CR", "DEBIT", "CREDIT",
        "REFUND", "REFUNDED", "REVERSAL", "REV", "RETURN", "CASHBACK", "ORDER", "PURCHASE",
        "INR", "RS", "MANDATE", "AUTOPAY", "COLLECT", "REQ", "REQUEST", "SENT", "RECEIVED",
    }
)  # fmt: skip


def merchant_tokens(description: str | None) -> list[str]:
    if not description:
        return []
    text = description.upper()
    text = _HANDLE_SUFFIX.sub(" ", text)
    text = _LONG_DIGITS.sub(" ", text)
    tokens = []
    for token in _SEPARATORS.split(text):
        if not token or token in FILLER_WORDS or len(token) < 2:
            continue
        if token.isdigit():  # short numbers (branch codes, last digits) are not names
            continue
        if token not in tokens:  # "SWIGGY ... swiggy@ybl" names the merchant twice
            tokens.append(token)
    return tokens


def normalize_merchant(description: str | None, max_tokens: int = 3) -> str:
    """A stable merchant key such as "SWIGGY" or "BESCOM ELECTRICITY". May be empty."""
    return " ".join(merchant_tokens(description)[:max_tokens])


def contains_word(text: str, word: str) -> bool:
    """True if ``word`` appears as a whole word. A number (like an account's last 4 digits)
    only needs digit boundaries, so the masked form "XX4321" matches "4321"."""
    boundary = r"\d" if word.isdigit() else r"[A-Z0-9]"
    pattern = rf"(?<!{boundary}){re.escape(word.upper())}(?!{boundary})"
    return re.search(pattern, text.upper()) is not None
