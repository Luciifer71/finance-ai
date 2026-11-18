"""M4: immutable facts, audit events, transfers, refunds, cash withdrawals (handoff 6.4-6.7)."""

import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models import Transaction, TransactionEvent
from tests.conftest import ApiUser
from tests.factories import add_account, add_tx

FIXTURES = Path(__file__).parent / "fixtures" / "statements"
D = Decimal
FACTS = (
    "account_id", "amount", "direction", "posted_on", "occurred_at", "description",
    "source", "external_id", "fingerprint", "import_id",
)  # fmt: skip


def category_id(client: TestClient, user: ApiUser, name: str) -> str:
    items = client.get("/api/v1/categories", headers=user.headers).json()["items"]
    return next(c["id"] for c in items if c["name"] == name)


def patch(client: TestClient, user: ApiUser, tx_id: object, **body: object):
    return client.patch(f"/api/v1/transactions/{tx_id}", json=body, headers=user.headers)


def events(session: Session, tx_id: object) -> list[TransactionEvent]:
    return list(
        session.scalars(
            select(TransactionEvent)
            .where(TransactionEvent.transaction_id == tx_id)
            .order_by(TransactionEvent.seq)
        )
    )


def facts(session: Session, user_id: uuid.UUID) -> dict[uuid.UUID, tuple]:
    rows = session.scalars(select(Transaction).where(Transaction.user_id == user_id)).all()
    return {r.id: tuple(getattr(r, f) for f in FACTS) for r in rows}


# --- immutability ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "assignment",
    [
        "amount = amount + 1",
        "posted_on = posted_on + 1",
        "description = 'rewritten'",
        "direction = 'credit', transaction_type = 'income'",
        "account_id = gen_random_uuid()",
        "fingerprint = repeat('0', 64)",
        "source = 'forged'",
    ],
)
def test_database_rejects_changes_to_source_facts_even_through_raw_sql(
    db_session: Session, user_a: ApiUser, assignment: str
):
    account = add_account(db_session, user_a.id)
    tx = add_tx(db_session, user_a.id, account.id, date(2026, 11, 3), "500.00", description="orig")
    db_session.commit()

    with (
        pytest.raises(DBAPIError, match="source facts cannot be changed"),
        db_session.begin_nested(),
    ):
        db_session.execute(
            text(f"UPDATE transactions SET {assignment} WHERE id = :id"),  # noqa: S608
            {"id": tx.id},
        )


def test_editable_fields_can_change_through_sql(db_session: Session, user_a: ApiUser):
    account = add_account(db_session, user_a.id)
    tx = add_tx(db_session, user_a.id, account.id, date(2026, 11, 3), "500.00")
    db_session.execute(text("UPDATE transactions SET notes = 'ok' WHERE id = :id"), {"id": tx.id})


def test_events_are_append_only(client: TestClient, user_a: ApiUser, db_session: Session):
    account = add_account(db_session, user_a.id)
    tx = add_tx(db_session, user_a.id, account.id, date(2026, 11, 3), "500.00")
    patch(client, user_a, tx.id, notes="first")
    (event,) = events(db_session, tx.id)
    for statement in (
        "UPDATE transaction_events SET reason = 'x' WHERE id = :id",
        "DELETE FROM transaction_events WHERE id = :id",
    ):
        with pytest.raises(DBAPIError, match="append-only"), db_session.begin_nested():
            db_session.execute(text(statement), {"id": event.id})


# --- edits and events -------------------------------------------------------------------------


def test_each_edit_writes_exactly_one_event_with_before_and_after(
    client: TestClient, user_a: ApiUser, db_session: Session
):
    account = add_account(db_session, user_a.id)
    tx = add_tx(db_session, user_a.id, account.id, date(2026, 11, 3), "350.00")
    food = category_id(client, user_a, "Food & Dining")

    response = patch(client, user_a, tx.id, category_id=food)
    assert response.status_code == 200
    body = response.json()
    assert (body["category_id"], body["category_source"]) == (food, "user")
    (event,) = events(db_session, tx.id)
    assert event.event_type == "category_changed"
    assert event.actor == "user"
    assert event.before == {"category_id": None, "category_source": "none"}
    assert event.after == {"category_id": food, "category_source": "user"}

    patch(client, user_a, tx.id, notes="  team lunch  ", is_excluded=True)
    second = events(db_session, tx.id)[1]
    assert second.event_type == "edited"
    assert second.before == {"notes": None, "is_excluded": False}
    assert second.after == {"notes": "team lunch", "is_excluded": True}
    assert len(events(db_session, tx.id)) == 2

    # The detail endpoint and the events endpoint show the same history.
    detail = client.get(f"/api/v1/transactions/{tx.id}", headers=user_a.headers).json()
    listed = client.get(f"/api/v1/transactions/{tx.id}/events", headers=user_a.headers).json()
    assert [e["event_type"] for e in detail["events"]] == ["category_changed", "edited"]
    assert detail["events"] == listed["items"]


def test_no_op_edit_writes_no_event(client: TestClient, user_a: ApiUser, db_session: Session):
    account = add_account(db_session, user_a.id)
    tx = add_tx(db_session, user_a.id, account.id, date(2026, 11, 3), "350.00")
    assert patch(client, user_a, tx.id, notes=None, is_excluded=False).status_code == 200
    assert events(db_session, tx.id) == []


def test_source_facts_are_not_editable_through_the_api(
    client: TestClient, user_a: ApiUser, db_session: Session
):
    account = add_account(db_session, user_a.id)
    tx = add_tx(db_session, user_a.id, account.id, date(2026, 11, 3), "350.00")
    for body in ({"amount": "1.00"}, {"posted_on": "2026-01-01"}, {"description": "x"}):
        assert patch(client, user_a, tx.id, **body).status_code == 422


def test_edit_rules(client: TestClient, user_a: ApiUser, db_session: Session):
    account = add_account(db_session, user_a.id)
    debit = add_tx(db_session, user_a.id, account.id, date(2026, 11, 3), "350.00")
    credit = add_tx(db_session, user_a.id, account.id, date(2026, 11, 4), "99.00", "credit",
                    category_id=uuid.UUID(category_id(client, user_a, "Other income")),
                    category_source="user")  # fmt: skip
    salary = category_id(client, user_a, "Salary")

    assert patch(client, user_a, debit.id, category_id=salary).status_code == 422  # wrong kind
    assert patch(client, user_a, debit.id, transaction_type="income").status_code == 422
    assert patch(client, user_a, debit.id, transaction_type="transfer").status_code == 422
    assert patch(client, user_a, debit.id, notes="x" * 1001).status_code == 422

    # income -> refund on a credit: its income category no longer fits and is cleared.
    response = patch(client, user_a, credit.id, transaction_type="refund")
    assert response.status_code == 200
    assert (response.json()["transaction_type"], response.json()["category_id"]) == ("refund", None)
    (event,) = events(db_session, credit.id)
    assert event.event_type == "edited"
    assert event.before["transaction_type"] == "income"
    assert event.before["category_id"] is not None


def test_excluded_rows_leave_lists_but_still_count_in_the_balance(
    client: TestClient, user_a: ApiUser, db_session: Session
):
    account = add_account(db_session, user_a.id)
    tx = add_tx(db_session, user_a.id, account.id, date(2026, 11, 3), "350.00")
    patch(client, user_a, tx.id, is_excluded=True)

    listed = client.get("/api/v1/transactions", headers=user_a.headers).json()["items"]
    with_excluded = client.get(
        "/api/v1/transactions?include_excluded=true", headers=user_a.headers
    ).json()["items"]
    assert [i["id"] for i in listed] == []
    assert [i["id"] for i in with_excluded] == [str(tx.id)]
    balance = client.get(f"/api/v1/accounts/{account.id}/balance", headers=user_a.headers).json()
    assert balance["balance"] == "-350.00"  # 0 - 350.00: the money really left


# --- refunds ---------------------------------------------------------------------------------


def link(client: TestClient, user: ApiUser, refund_id: object, original_id: object):
    return client.post(
        "/api/v1/refunds",
        json={"refund_transaction_id": str(refund_id), "original_transaction_id": str(original_id)},
        headers=user.headers,
    )


def test_refund_sum_may_equal_the_original_but_not_exceed_it(
    client: TestClient, user_a: ApiUser, db_session: Session
):
    account = add_account(db_session, user_a.id)
    original = add_tx(db_session, user_a.id, account.id, date(2026, 11, 1), "1000.00")
    first = add_tx(db_session, user_a.id, account.id, date(2026, 11, 5), "600.00", "credit")
    second = add_tx(db_session, user_a.id, account.id, date(2026, 11, 6), "400.00", "credit")
    third = add_tx(db_session, user_a.id, account.id, date(2026, 11, 7), "0.01", "credit")

    assert link(client, user_a, first.id, original.id).status_code == 200
    # 600.00 + 400.00 = 1000.00: exactly equal is allowed
    response = link(client, user_a, second.id, original.id)
    assert response.status_code == 200
    assert (response.json()["transaction_type"], response.json()["refund_of_id"]) == (
        "refund",
        str(original.id),
    )
    # 1000.00 + 0.01 = 1000.01: one paisa more is rejected
    rejected = link(client, user_a, third.id, original.id)
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "refund.exceeds_original"
    assert rejected.json()["already_refunded"] == "1000.00"
    assert events(db_session, third.id) == []


def test_single_refund_larger_than_the_original_is_rejected(
    client: TestClient, user_a: ApiUser, db_session: Session
):
    account = add_account(db_session, user_a.id)
    original = add_tx(db_session, user_a.id, account.id, date(2026, 11, 1), "1000.00")
    big = add_tx(db_session, user_a.id, account.id, date(2026, 11, 2), "1000.01", "credit")
    assert link(client, user_a, big.id, original.id).json()["code"] == "refund.exceeds_original"


def test_refund_link_rules(client: TestClient, user_a: ApiUser, db_session: Session):
    account = add_account(db_session, user_a.id)
    original = add_tx(db_session, user_a.id, account.id, date(2026, 11, 1), "500.00")
    other = add_tx(db_session, user_a.id, account.id, date(2026, 11, 1), "500.00")
    income = add_tx(db_session, user_a.id, account.id, date(2026, 11, 1), "50.00", "credit")
    refund = add_tx(db_session, user_a.id, account.id, date(2026, 11, 3), "100.00", "credit")

    assert (
        link(client, user_a, refund.id, income.id).json()["code"] == "refund.original_not_expense"
    )
    assert link(client, user_a, other.id, original.id).json()["code"] == "refund.not_a_credit"
    assert link(client, user_a, refund.id, refund.id).json()["code"] == "refund.same_transaction"
    assert link(client, user_a, refund.id, original.id).status_code == 200
    assert link(client, user_a, refund.id, original.id).status_code == 200  # same link: no-op
    assert len(events(db_session, refund.id)) == 1
    assert link(client, user_a, refund.id, other.id).json()["code"] == "refund.already_linked"


def test_refund_suggestions_pick_the_most_recent_matching_purchase(
    client: TestClient, user_a: ApiUser, db_session: Session
):
    account = add_account(db_session, user_a.id)
    other_account = add_account(db_session, user_a.id, "Other")
    add_tx(db_session, user_a.id, account.id, date(2026, 9, 1), "999.00",
           description="UPI/MYNTRA/402799990000/ORDER")  # fmt: skip  # 66 days before: too old
    older = add_tx(db_session, user_a.id, account.id, date(2026, 10, 10), "999.00",
                   description="UPI/MYNTRA/402799990001/ORDER")  # fmt: skip
    newer = add_tx(db_session, user_a.id, account.id, date(2026, 10, 20), "999.00",
                   description="UPI/MYNTRA/402799990002/ORDER")  # fmt: skip
    add_tx(db_session, user_a.id, other_account.id, date(2026, 11, 1), "999.00",
           description="UPI/MYNTRA/402799990003/ORDER")  # fmt: skip  # different account
    refund = add_tx(db_session, user_a.id, account.id, date(2026, 11, 6), "499.00", "credit",
                    description="UPI/MYNTRA/402799990009/REFUND")  # fmt: skip
    add_tx(db_session, user_a.id, account.id, date(2026, 11, 6), "499.00", "credit",
           description="UPI/AJIO/402799990010/REFUND")  # fmt: skip  # no AJIO purchase

    items = client.get("/api/v1/refunds/suggestions", headers=user_a.headers).json()["items"]

    assert [(i["refund"]["id"], i["original"]["id"], i["merchant"]) for i in items] == [
        (str(refund.id), str(newer.id), "MYNTRA")
    ]
    assert older.id != newer.id


# --- transfers -------------------------------------------------------------------------------


def pair(client: TestClient, user: ApiUser, debit_id: object, credit_id: object):
    return client.post(
        "/api/v1/transfers",
        json={"debit_transaction_id": str(debit_id), "credit_transaction_id": str(credit_id)},
        headers=user.headers,
    )


def test_pair_and_unpair_restores_previous_types_and_categories(
    client: TestClient, user_a: ApiUser, db_session: Session
):
    bank = add_account(db_session, user_a.id)
    wallet = add_account(db_session, user_a.id, "Wallet", "wallet")
    shopping = uuid.UUID(category_id(client, user_a, "Shopping"))
    debit = add_tx(db_session, user_a.id, bank.id, date(2026, 11, 3), "5000.00",
                   category_id=shopping, category_source="user")  # fmt: skip
    credit = add_tx(db_session, user_a.id, wallet.id, date(2026, 11, 4), "5000.00", "credit")

    response = pair(client, user_a, debit.id, credit.id)
    assert response.status_code == 201
    group = response.json()["transfer_group_id"]
    sides = response.json()["transactions"]
    assert [s["transaction_type"] for s in sides] == ["transfer", "transfer"]
    assert [s["direction"] for s in sides] == ["debit", "credit"]
    assert all(s["category_id"] is None for s in sides)

    undone = client.delete(f"/api/v1/transfers/{group}", headers=user_a.headers)
    assert undone.status_code == 200
    db_session.expire_all()
    restored_debit = db_session.get(Transaction, debit.id)
    restored_credit = db_session.get(Transaction, credit.id)
    assert (restored_debit.transaction_type, restored_debit.category_id) == ("expense", shopping)
    assert (restored_credit.transaction_type, restored_credit.transfer_group_id) == ("income", None)
    assert [e.event_type for e in events(db_session, debit.id)] == [
        "transfer_paired",
        "transfer_unpaired",
    ]
    assert client.delete(f"/api/v1/transfers/{group}", headers=user_a.headers).status_code == 404


def test_invalid_pairs_are_rejected(client: TestClient, user_a: ApiUser, db_session: Session):
    bank = add_account(db_session, user_a.id)
    wallet = add_account(db_session, user_a.id, "Wallet", "wallet")
    debit = add_tx(db_session, user_a.id, bank.id, date(2026, 11, 3), "5000.00")
    unequal = add_tx(db_session, user_a.id, wallet.id, date(2026, 11, 3), "4999.99", "credit")
    same_account = add_tx(db_session, user_a.id, bank.id, date(2026, 11, 3), "5000.00", "credit")
    other_debit = add_tx(db_session, user_a.id, wallet.id, date(2026, 11, 3), "5000.00")
    good = add_tx(db_session, user_a.id, wallet.id, date(2026, 11, 3), "5000.00", "credit")

    assert pair(client, user_a, debit.id, unequal.id).json()["code"] == "transfer.amount_mismatch"
    assert pair(client, user_a, debit.id, same_account.id).json()["code"] == "transfer.same_account"
    assert pair(client, user_a, debit.id, other_debit.id).json()["code"] == (
        "transfer.wrong_directions"
    )
    assert pair(client, user_a, debit.id, good.id).status_code == 201
    assert pair(client, user_a, debit.id, good.id).json()["code"] == "transfer.already_paired"


def test_refunded_purchase_cannot_become_a_transfer(
    client: TestClient, user_a: ApiUser, db_session: Session
):
    bank = add_account(db_session, user_a.id)
    wallet = add_account(db_session, user_a.id, "Wallet", "wallet")
    debit = add_tx(db_session, user_a.id, bank.id, date(2026, 11, 3), "500.00")
    refund = add_tx(db_session, user_a.id, bank.id, date(2026, 11, 4), "100.00", "credit")
    credit = add_tx(db_session, user_a.id, wallet.id, date(2026, 11, 3), "500.00", "credit")
    link(client, user_a, refund.id, debit.id)
    assert pair(client, user_a, debit.id, credit.id).json()["code"] == "transfer.has_refund_link"


def test_database_rejects_a_broken_transfer_group(db_session: Session, user_a: ApiUser):
    bank = add_account(db_session, user_a.id)
    group = uuid.uuid4()
    add_tx(db_session, user_a.id, bank.id, date(2026, 11, 3), "10.00", "debit", "transfer",
           transfer_group_id=group)  # fmt: skip
    # Only one side, and checked at commit: force the deferred check to run now.
    with pytest.raises(DBAPIError, match="transfer group must be"), db_session.begin_nested():
        db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def test_transfer_suggestions(client: TestClient, user_a: ApiUser, db_session: Session):
    bank = add_account(db_session, user_a.id)
    wallet = add_account(db_session, user_a.id, "Wallet", "wallet")
    debit = add_tx(db_session, user_a.id, bank.id, date(2026, 11, 3), "2000.00",
                   description="NEFT TO WALLET")  # fmt: skip
    credit = add_tx(db_session, user_a.id, wallet.id, date(2026, 11, 6), "2000.00", "credit")
    add_tx(db_session, user_a.id, wallet.id, date(2026, 11, 7), "2000.00", "credit")  # 4 days

    pairs = client.get("/api/v1/transfers/suggestions", headers=user_a.headers).json()["pairs"]

    assert [(p["debit"]["id"], p["credit"]["id"], p["days_apart"]) for p in pairs] == [
        (str(debit.id), str(credit.id), 3)
    ]
    assert pairs[0]["has_self_transfer_hint"] is False


# --- automatic pairing at import ------------------------------------------------------------


def _import_clean(client: TestClient, user: ApiUser, account_id: object) -> dict:
    preview = client.post(
        "/api/v1/imports",
        files={"file": ("s.csv", (FIXTURES / "clean_12_rows.csv").read_bytes(), "text/csv")},
        data={"account_id": str(account_id), "profile_id": "generic_indian_bank_v1"},
        headers=user.headers,
    ).json()
    return client.post(f"/api/v1/imports/{preview['id']}/commit", headers=user.headers).json()


def test_import_auto_pairs_a_single_candidate_with_a_self_hint(
    client: TestClient, user_a: ApiUser, db_session: Session
):
    bank = add_account(db_session, user_a.id)
    savings = add_account(db_session, user_a.id, "Savings")
    # The clean file has "IMPS/SELF/OWN A/C 4321" 10,000.00 out on 20 Oct.
    credit = add_tx(db_session, user_a.id, savings.id, date(2026, 10, 21), "10000.00", "credit")

    _import_clean(client, user_a, bank.id)

    db_session.expire_all()
    paired = db_session.get(Transaction, credit.id)
    assert paired.transaction_type == "transfer"
    (event,) = events(db_session, credit.id)
    assert (event.event_type, event.actor) == ("transfer_paired", "system")


def test_import_does_not_auto_pair_when_there_are_two_candidates(
    client: TestClient, user_a: ApiUser, db_session: Session
):
    bank = add_account(db_session, user_a.id)
    savings = add_account(db_session, user_a.id, "Savings")
    first = add_tx(db_session, user_a.id, savings.id, date(2026, 10, 21), "10000.00", "credit")
    add_tx(db_session, user_a.id, savings.id, date(2026, 10, 22), "10000.00", "credit")

    _import_clean(client, user_a, bank.id)

    db_session.expire_all()
    assert db_session.get(Transaction, first.id).transaction_type == "income"
    pairs = client.get("/api/v1/transfers/suggestions", headers=user_a.headers).json()["pairs"]
    assert {p["candidates_for_debit"] for p in pairs} == {2}


def test_import_does_not_auto_pair_without_a_hint(
    client: TestClient, user_a: ApiUser, db_session: Session
):
    bank = add_account(db_session, user_a.id)
    wallet = add_account(db_session, user_a.id, "Wallet", "wallet")
    credit = add_tx(db_session, user_a.id, wallet.id, date(2026, 10, 7), "18000.00", "credit")
    _import_clean(client, user_a, bank.id)  # "NEFT/RENT/LANDLORD SYNTH" 18,000.00 on 7 Oct
    db_session.expire_all()
    assert db_session.get(Transaction, credit.id).transaction_type == "income"


def _import_simple(client: TestClient, user: ApiUser, account_id: object, rows: str) -> None:
    preview = client.post(
        "/api/v1/imports",
        files={"file": ("s.csv", f"date,description,amount\n{rows}".encode(), "text/csv")},
        data={"account_id": str(account_id), "profile_id": "simple_v1"},
        headers=user.headers,
    ).json()
    client.post(f"/api/v1/imports/{preview['id']}/commit", headers=user.headers)


@pytest.mark.parametrize(("last4", "paired"), [("4321", True), ("9999", False)])
def test_last4_of_the_other_account_counts_as_a_hint(
    client: TestClient, user_a: ApiUser, db_session: Session, last4: str, paired: bool
):
    bank = add_account(db_session, user_a.id)
    savings = add_account(db_session, user_a.id, "Savings")
    savings.last4 = last4
    credit = add_tx(db_session, user_a.id, savings.id, date(2026, 11, 2), "7500.00", "credit",
                    description="IMPS CR")  # fmt: skip

    # No SELF/OWN wording: only the masked account number can be the hint.
    _import_simple(client, user_a, bank.id, "2026-11-01,IMPS TO A/C XX4321,-7500.00\n")

    db_session.expire_all()
    expected = "transfer" if paired else "income"
    assert db_session.get(Transaction, credit.id).transaction_type == expected


# --- cash withdrawals -------------------------------------------------------------------------


def test_cash_withdrawal_with_one_cash_account(
    client: TestClient, user_a: ApiUser, db_session: Session
):
    bank = add_account(db_session, user_a.id)
    cash = add_account(db_session, user_a.id, "Cash", "cash")
    atm = add_tx(db_session, user_a.id, bank.id, date(2026, 11, 5), "2000.00",
                 description="ATM CASH WDL MG ROAD")  # fmt: skip

    suggestions = client.get("/api/v1/transfers/suggestions", headers=user_a.headers).json()
    (suggestion,) = suggestions["cash_withdrawals"]
    assert suggestion["action"] == "transfer_to_cash_account"
    assert suggestion["cash_account_ids"] == [str(cash.id)]

    response = client.post(
        "/api/v1/transfers/cash-withdrawals",
        json={"transaction_id": str(atm.id), "cash_account_id": str(cash.id)},
        headers=user_a.headers,
    )
    assert response.status_code == 201
    debit_side, credit_side = response.json()["transactions"]
    assert (debit_side["id"], credit_side["account_id"]) == (str(atm.id), str(cash.id))
    assert credit_side["amount"] == "2000.00"
    cash_balance = client.get(f"/api/v1/accounts/{cash.id}/balance", headers=user_a.headers)
    assert cash_balance.json()["balance"] == "2000.00"  # 0 + 2000.00 arrived in the wallet
    group = response.json()["transfer_group_id"]
    refused = client.delete(f"/api/v1/transfers/{group}", headers=user_a.headers)
    assert refused.json()["code"] == "transfer.cash_withdrawal_cannot_unpair"


def test_cash_withdrawal_without_cash_account_suggests_a_category(
    client: TestClient, user_a: ApiUser, db_session: Session
):
    bank = add_account(db_session, user_a.id)
    add_tx(db_session, user_a.id, bank.id, date(2026, 11, 5), "500.00", description="NWD-SBI ATM")
    (suggestion,) = client.get("/api/v1/transfers/suggestions", headers=user_a.headers).json()[
        "cash_withdrawals"
    ]
    assert suggestion["action"] == "categorize_as_cash_withdrawal"
    assert suggestion["category_id"] == category_id(client, user_a, "Cash withdrawal")


# --- cross-user and source facts --------------------------------------------------------------


def test_other_users_transactions_cannot_be_paired_or_linked(
    client: TestClient, user_a: ApiUser, user_b: ApiUser, db_session: Session
):
    bank_a = add_account(db_session, user_a.id)
    bank_b = add_account(db_session, user_b.id)
    debit_a = add_tx(db_session, user_a.id, bank_a.id, date(2026, 11, 3), "100.00")
    credit_b = add_tx(db_session, user_b.id, bank_b.id, date(2026, 11, 3), "100.00", "credit")
    assert pair(client, user_b, debit_a.id, credit_b.id).status_code == 404
    assert link(client, user_b, credit_b.id, debit_a.id).status_code == 404
    assert events(db_session, debit_a.id) == []


def test_nothing_in_this_milestone_changes_a_source_fact(
    client: TestClient, user_a: ApiUser, db_session: Session
):
    bank = add_account(db_session, user_a.id)
    savings = add_account(db_session, user_a.id, "Savings")
    cash = add_account(db_session, user_a.id, "Cash", "cash")
    add_tx(db_session, user_a.id, savings.id, date(2026, 10, 21), "10000.00", "credit")
    _import_clean(client, user_a, bank.id)
    before = facts(db_session, user_a.id)

    ids = list(before)
    atm = db_session.scalars(
        select(Transaction).where(Transaction.description == "ATM CASH WDL MG ROAD")
    ).one()
    client.post(
        "/api/v1/transfers/cash-withdrawals",
        json={"transaction_id": str(atm.id), "cash_account_id": str(cash.id)},
        headers=user_a.headers,
    )
    order = db_session.scalars(
        select(Transaction).where(Transaction.description == "UPI/AMAZON/402711116666/ORDER")
    ).one()
    refund = db_session.scalars(
        select(Transaction).where(Transaction.description == "UPI/AMAZON/402711117777/REFUND")
    ).one()
    link(client, user_a, refund.id, order.id)
    for tx_id in ids[:5]:
        patch(client, user_a, tx_id, notes="checked", is_excluded=True)

    db_session.expire_all()
    after = facts(db_session, user_a.id)
    assert {k: v for k, v in after.items() if k in before} == before
    assert len(after) == len(before) + 1  # only the cash side was added
    total_events = db_session.scalar(
        select(func.count())
        .select_from(TransactionEvent)
        .where(TransactionEvent.user_id == user_a.id)
    )
    # 2 auto-pair events + 2 cash pairing + 1 refund link + 5 edits
    assert total_events == 10
