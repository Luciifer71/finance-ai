"""Refunds: suggestions and linking a refund to its original purchase."""

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.schemas.ledger import RefundLinkIn, RefundSuggestionOut, RefundSuggestions
from app.schemas.transactions import TransactionOut
from app.services import refunds as service
from app.services.transactions import to_out

router = APIRouter(prefix="/refunds", tags=["refunds"])


@router.get("/suggestions", response_model=RefundSuggestions)
def suggestions(user: CurrentUser, session: DbSession) -> RefundSuggestions:
    return RefundSuggestions(
        items=[
            RefundSuggestionOut(
                refund=to_out(s.refund), original=to_out(s.original), merchant=s.merchant
            )
            for s in service.suggestions(session, user.id)
        ]
    )


@router.post("", response_model=TransactionOut)
def link(body: RefundLinkIn, user: CurrentUser, session: DbSession) -> TransactionOut:
    refund = service.link(
        session, user.id, body.refund_transaction_id, body.original_transaction_id
    )
    return to_out(refund)
