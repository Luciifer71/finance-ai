from typing import Literal
from uuid import UUID

from app.schemas.common import ApiModel
from app.schemas.transactions import TransactionOut


class TransferPairIn(ApiModel):
    debit_transaction_id: UUID
    credit_transaction_id: UUID


class CashWithdrawalIn(ApiModel):
    transaction_id: UUID
    cash_account_id: UUID


class TransferOut(ApiModel):
    transfer_group_id: UUID
    transactions: list[TransactionOut]


class TransferSuggestion(ApiModel):
    debit: TransactionOut
    credit: TransactionOut
    days_apart: int
    has_self_transfer_hint: bool
    candidates_for_debit: int
    candidates_for_credit: int


class CashWithdrawalSuggestion(ApiModel):
    transaction: TransactionOut
    action: Literal[
        "transfer_to_cash_account", "categorize_as_cash_withdrawal", "choose_cash_account"
    ]
    cash_account_ids: list[UUID]
    category_id: UUID | None


class TransferSuggestions(ApiModel):
    pairs: list[TransferSuggestion]
    cash_withdrawals: list[CashWithdrawalSuggestion]


class RefundLinkIn(ApiModel):
    refund_transaction_id: UUID
    original_transaction_id: UUID


class RefundSuggestionOut(ApiModel):
    refund: TransactionOut
    original: TransactionOut
    merchant: str


class RefundSuggestions(ApiModel):
    items: list[RefundSuggestionOut]
