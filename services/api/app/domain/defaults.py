"""Categories and categorization rules every new user starts with (handoff section 10).

All seed rules are synthetic examples of common Indian merchants. A rule's
pattern matches whole words of the normalized merchant name, so "OLA" matches
"OLA CABS" but not "COCA COLA".
"""

from typing import Final

UNCATEGORIZED: Final = "Uncategorized"
CASH_WITHDRAWAL: Final = "Cash withdrawal"

DEFAULT_EXPENSE_CATEGORIES: Final[tuple[str, ...]] = (
    "Food & Dining",
    "Groceries",
    "Transport",
    "Fuel",
    "Shopping",
    "Bills & Utilities",
    "Rent",
    "Entertainment",
    "Subscriptions",
    "Health",
    "Education",
    "Travel",
    "Personal Care",
    "Gifts & Donations",
    "Fees & Charges",
    CASH_WITHDRAWAL,
    UNCATEGORIZED,
)

DEFAULT_INCOME_CATEGORIES: Final[tuple[str, ...]] = (
    "Salary",
    "Interest",
    "Refunds & Cashback",
    "Other income",
)

# pattern -> category name. Patterns are upper-case merchant words.
SEED_RULES: Final[dict[str, str]] = {
    "SWIGGY": "Food & Dining",
    "ZOMATO": "Food & Dining",
    "DOMINOS": "Food & Dining",
    "BLINKIT": "Groceries",
    "ZEPTO": "Groceries",
    "BIGBASKET": "Groceries",
    "UBER": "Transport",
    "OLA": "Transport",
    "RAPIDO": "Transport",
    "IRCTC": "Travel",
    "NETFLIX": "Subscriptions",
    "SPOTIFY": "Subscriptions",
    "HOTSTAR": "Subscriptions",
    "AMAZON": "Shopping",
    "FLIPKART": "Shopping",
    "MYNTRA": "Shopping",
}
