"""Transfers between your own accounts: suggestions, pair, unpair, cash withdrawals."""

from collections import Counter
from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.ledger import (
    CashWithdrawalIn,
    CashWithdrawalSuggestion,
    TransferOut,
    TransferPairIn,
    TransferSuggestion,
    TransferSuggestions,
)
from app.services import transfers as service
from app.services.transactions import to_out

router = APIRouter(prefix="/transfers", tags=["transfers"])


def _group_out(session: DbSession, user_id: UUID, group_id: UUID) -> TransferOut:
    rows = service.group_rows(session, user_id, group_id)
    return TransferOut(transfer_group_id=group_id, transactions=[to_out(r) for r in rows])


@router.get("/suggestions", response_model=TransferSuggestions)
def suggestions(user: CurrentUser, session: DbSession) -> TransferSuggestions:
    candidates = service.candidate_pairs(session, user.id)
    per_row: Counter[UUID] = Counter()
    for c in candidates:
        per_row[c.debit.id] += 1
        per_row[c.credit.id] += 1
    return TransferSuggestions(
        pairs=[
            TransferSuggestion(
                debit=to_out(c.debit),
                credit=to_out(c.credit),
                days_apart=c.days_apart,
                has_self_transfer_hint=c.has_hint,
                candidates_for_debit=per_row[c.debit.id],
                candidates_for_credit=per_row[c.credit.id],
            )
            for c in candidates
        ],
        cash_withdrawals=[
            CashWithdrawalSuggestion(
                transaction=to_out(s.transaction),
                action=s.action,
                cash_account_ids=s.cash_account_ids,
                category_id=s.category_id,
            )
            for s in service.cash_withdrawal_suggestions(session, user.id)
        ],
    )


@router.post("", response_model=TransferOut, status_code=status.HTTP_201_CREATED)
def pair(body: TransferPairIn, user: CurrentUser, session: DbSession) -> TransferOut:
    group_id = service.pair(session, user.id, body.debit_transaction_id, body.credit_transaction_id)
    return _group_out(session, user.id, group_id)


@router.post("/cash-withdrawals", response_model=TransferOut, status_code=status.HTTP_201_CREATED)
def confirm_cash_withdrawal(
    body: CashWithdrawalIn, user: CurrentUser, session: DbSession
) -> TransferOut:
    """Record the cash arriving in your cash account and pair it with the bank withdrawal."""
    group_id = service.confirm_cash_withdrawal(
        session, user.id, body.transaction_id, body.cash_account_id
    )
    return _group_out(session, user.id, group_id)


@router.delete("/{group_id}", response_model=TransferOut)
def unpair(group_id: UUID, user: CurrentUser, session: DbSession) -> TransferOut:
    """Undo a pairing. Each side gets back its previous type and category (audited)."""
    rows = service.unpair(session, user.id, group_id)
    return TransferOut(transfer_group_id=group_id, transactions=[to_out(r) for r in rows])
