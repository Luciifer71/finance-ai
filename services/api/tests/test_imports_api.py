"""M3: CSV import pipeline through the API (handoff 8.1-8.4).

Hand-calculated facts about the fixtures (see tests/fixtures/statements/README.md):
- clean_12_rows.csv: 12 rows; balances chain 10,000.00 -> 34,125.00 (28 Oct 2026).
- overlap_nov.csv: its first 4 rows are the clean file's last 4; 4 new rows take the
  balance from 34,125.00 to 91,418.50 on 8 Nov: +60,000.00 -520.00 -310.50 -1,876.00.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import AccessAudit, BalanceSnapshot, ImportRow, Job, Transaction
from app.services import imports as import_service
from tests.conftest import ApiUser
from tests.factories import add_account

FIXTURES = Path(__file__).parent / "fixtures" / "statements"
GENERIC = "generic_indian_bank_v1"
_NOW = datetime(2026, 11, 18, 6, 30, tzinfo=UTC)


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def upload(
    client: TestClient,
    user: ApiUser,
    account_id: object,
    data: bytes,
    profile: str = GENERIC,
    filename: str = "statement.csv",
    content_type: str = "text/csv",
):
    return client.post(
        "/api/v1/imports",
        files={"file": (filename, data, content_type)},
        data={"account_id": str(account_id), "profile_id": profile},
        headers=user.headers,
    )


def upload_ok(client: TestClient, user: ApiUser, account_id: object, data: bytes, **kw) -> dict:
    response = upload(client, user, account_id, data, **kw)
    assert response.status_code == 201, response.text
    return response.json()


def commit(client: TestClient, user: ApiUser, import_id: str) -> dict:
    response = client.post(f"/api/v1/imports/{import_id}/commit", headers=user.headers)
    assert response.status_code == 200, response.text
    return response.json()


def tx_count(session: Session, account_id: object) -> int:
    return session.scalar(
        select(func.count()).select_from(Transaction).where(Transaction.account_id == account_id)
    )


def balance(client: TestClient, user: ApiUser, account_id: object) -> dict:
    return client.get(f"/api/v1/accounts/{account_id}/balance", headers=user.headers).json()


@pytest.fixture
def account(db_session: Session, user_a: ApiUser):
    return add_account(db_session, user_a.id, "Synthetic Savings")


# --- the acceptance path ------------------------------------------------------------------


def test_clean_import_previews_then_commits_with_a_verified_balance(
    client: TestClient, user_a: ApiUser, account, db_session: Session
):
    preview = upload_ok(client, user_a, account.id, fixture("clean_12_rows.csv"))

    assert preview["status"] == "previewed"
    assert preview["profile_verified"] is False
    assert preview["profile_note"] == "synthetic, not yet verified against a real export"
    assert preview["counts"] == {
        "valid": 12,
        "invalid": 0,
        "duplicate_in_file": 0,
        "already_imported": 0,
    }
    assert (preview["date_from"], preview["date_to"]) == ("2026-10-01", "2026-10-28")
    assert (preview["closing_balance"], preview["closing_balance_on"]) == ("34125.00", "2026-10-28")
    assert preview["warnings"] == []
    assert len(preview["rows"]) == 12
    assert preview["rows"][1]["amount"] == "450.00"
    assert tx_count(db_session, account.id) == 0  # nothing is added before commit

    result = commit(client, user_a, preview["id"])

    assert result["status"] == "completed"
    assert (result["rows_total"], result["rows_imported"], result["rows_skipped"]) == (12, 12, 0)
    assert result["categorize_job_id"] is not None
    assert tx_count(db_session, account.id) == 12
    body = balance(client, user_a, account.id)
    assert (body["balance"], body["status"], body["verified_as_of"]) == (
        "34125.00",
        "verified",
        "2026-10-28",
    )

    rows = db_session.scalars(
        select(Transaction)
        .where(Transaction.account_id == account.id)
        .order_by(Transaction.import_row_number)
    ).all()
    assert [r.import_row_number for r in rows] == list(range(2, 14))
    assert {r.source for r in rows} == {"csv:generic_indian_bank_v1"}
    # 6.4 defaults: debits are expenses, credits are income
    assert sum(r.transaction_type == "expense" for r in rows) == 9
    assert sum(r.transaction_type == "income" for r in rows) == 3
    job = db_session.scalars(select(Job).where(Job.kind == "categorize_import")).one()
    assert job.payload == {"import_id": preview["id"]} and job.status == "queued"
    actions = db_session.scalars(
        select(AccessAudit.action).where(AccessAudit.user_id == user_a.id)
    ).all()
    assert {"import_uploaded", "import_committed"} <= set(actions)


def test_reuploading_the_same_file_is_rejected_with_the_existing_id(
    client: TestClient, user_a: ApiUser, account
):
    first = upload_ok(client, user_a, account.id, fixture("clean_12_rows.csv"))
    commit(client, user_a, first["id"])

    again = upload(client, user_a, account.id, fixture("clean_12_rows.csv"))

    assert again.status_code == 409
    assert again.json()["code"] == "import.already_imported"
    assert again.json()["import_id"] == first["id"]


def test_reimport_with_different_bytes_adds_zero_rows(
    client: TestClient, user_a: ApiUser, account, db_session: Session
):
    first = upload_ok(client, user_a, account.id, fixture("clean_12_rows.csv"))
    commit(client, user_a, first["id"])

    # Same rows, different file (Windows line endings): a new hash, the same fingerprints.
    windows = fixture("clean_12_rows.csv").replace(b"\n", b"\r\n")
    second = upload_ok(client, user_a, account.id, windows)
    assert second["counts"]["already_imported"] == 12
    result = commit(client, user_a, second["id"])

    assert (result["rows_imported"], result["rows_skipped"]) == (0, 12)
    assert tx_count(db_session, account.id) == 12


def test_overlapping_statement_adds_only_new_rows_and_reconciles(
    client: TestClient, user_a: ApiUser, account, db_session: Session
):
    commit(
        client, user_a, upload_ok(client, user_a, account.id, fixture("clean_12_rows.csv"))["id"]
    )
    preview = upload_ok(client, user_a, account.id, fixture("overlap_nov.csv"))
    assert preview["counts"]["already_imported"] == 4
    assert preview["counts"]["valid"] == 4

    result = commit(client, user_a, preview["id"])

    assert result["rows_imported"] == 4
    assert tx_count(db_session, account.id) == 16
    # 34125.00 + 60000.00 - 520.00 - 310.50 - 1876.00 = 91418.50
    body = balance(client, user_a, account.id)
    assert (body["balance"], body["status"]) == ("91418.50", "verified")
    recon = client.get(
        f"/api/v1/accounts/{account.id}/reconciliation", headers=user_a.headers
    ).json()
    assert recon["status"] == "ok"
    assert recon["pairs"][0]["movement"] == "57293.50"


def test_identical_same_day_rows_are_all_kept(
    client: TestClient, user_a: ApiUser, account, db_session: Session
):
    preview = upload_ok(
        client, user_a, account.id, fixture("same_day_identical.csv"), profile="simple_v1"
    )
    result = commit(client, user_a, preview["id"])
    assert result["rows_imported"] == 4
    chai = db_session.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(Transaction.account_id == account.id, Transaction.amount == Decimal("20.00"))
    )
    assert chai == 3


def test_malformed_rows_are_reported_and_do_not_block_valid_rows(
    client: TestClient, user_a: ApiUser, account, db_session: Session
):
    preview = upload_ok(client, user_a, account.id, fixture("malformed.csv"))
    assert preview["counts"]["valid"] == 2
    assert preview["counts"]["invalid"] == 4
    invalid = client.get(
        f"/api/v1/imports/{preview['id']}?row_status=invalid", headers=user_a.headers
    ).json()["rows"]
    assert [(r["row_number"], r["error_code"]) for r in invalid] == [
        (3, "import.row.bad_date"),
        (4, "import.row.two_amounts"),
        (5, "import.row.no_amount"),
        (6, "import.row.bad_amount"),
    ]
    result = commit(client, user_a, preview["id"])
    assert (result["rows_imported"], result["rows_failed"]) == (2, 4)
    assert tx_count(db_session, account.id) == 2


def test_preamble_and_footer_statement(
    client: TestClient, user_a: ApiUser, account, db_session: Session
):
    preview = upload_ok(client, user_a, account.id, fixture("preamble_footer.csv"))
    result = commit(client, user_a, preview["id"])
    assert result["rows_imported"] == 3
    snapshot = db_session.scalars(
        select(BalanceSnapshot).where(BalanceSnapshot.account_id == account.id)
    ).one()
    assert (snapshot.as_of, snapshot.balance) == (date(2026, 10, 5), Decimal("6460.00"))


def test_cp1252_file_imports(client: TestClient, user_a: ApiUser, account):
    preview = upload_ok(client, user_a, account.id, fixture("cp1252_text.csv"), profile="simple_v1")
    assert preview["rows"][0]["description"] == "Café Mocha – Rs. paid"


# --- rejections ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "kw", "status", "code"),
    [
        (b"", {}, 422, "import.empty_file"),
        (b"date,description,amount\n\x00\x00", {"profile": "simple_v1"}, 422, "import.binary_file"),
        (b"a,b\n1,2\n", {}, 422, "import.no_header"),
        (b"x", {"filename": "statement.xlsx"}, 415, "import.unsupported_type"),
        (b"x", {"content_type": "image/png"}, 415, "import.unsupported_type"),
        (b"x", {"profile": "no_such_profile"}, 422, "import.unknown_profile"),
    ],
)
def test_bad_uploads_are_rejected_with_stable_codes(
    client: TestClient, user_a: ApiUser, account, data: bytes, kw: dict, status: int, code: str
):
    response = upload(client, user_a, account.id, data, **kw)
    assert response.status_code == status, response.text
    assert response.json()["code"] == code


def test_file_over_the_size_limit_is_rejected(settings: Settings, app, user_a: ApiUser, account):
    app.state.settings = settings.model_copy(update={"max_upload_bytes": 1000})
    response = upload(TestClient(app), user_a, account.id, b"x" * 1500)
    assert response.status_code == 413
    assert response.json()["code"] == "import.file_too_large"


def test_file_over_the_row_limit_is_rejected(client: TestClient, user_a: ApiUser, account):
    rows = "".join(f"2026-11-05,row {i},-1.00\n" for i in range(20_001))
    response = upload(
        client,
        user_a,
        account.id,
        ("date,description,amount\n" + rows).encode(),
        profile="simple_v1",
    )
    assert response.status_code == 422
    assert response.json()["code"] == "import.too_many_rows"


def test_failed_import_with_the_same_file_can_be_retried(
    client: TestClient, user_a: ApiUser, account
):
    data = fixture("same_day_identical.csv")
    wrong_profile = upload(client, user_a, account.id, data, profile=GENERIC)
    assert wrong_profile.json()["code"] == "import.no_header"
    failed_id = wrong_profile.json()["import_id"]
    assert client.get(f"/api/v1/imports/{failed_id}", headers=user_a.headers).json()["status"] == (
        "failed"
    )

    retried = upload_ok(client, user_a, account.id, data, profile="simple_v1")
    assert retried["id"] != failed_id
    assert client.get(f"/api/v1/imports/{failed_id}", headers=user_a.headers).status_code == 404


def test_archived_or_foreign_account_cannot_receive_an_import(
    client: TestClient, user_a: ApiUser, user_b: ApiUser, account
):
    assert upload(client, user_b, account.id, fixture("clean_12_rows.csv")).status_code == 404
    client.patch(
        f"/api/v1/accounts/{account.id}", json={"is_archived": True}, headers=user_a.headers
    )
    assert upload(client, user_a, account.id, fixture("clean_12_rows.csv")).status_code == 409


# --- lifecycle ----------------------------------------------------------------------------


def test_commit_is_idempotent(client: TestClient, user_a: ApiUser, account, db_session: Session):
    preview = upload_ok(client, user_a, account.id, fixture("clean_12_rows.csv"))
    first = commit(client, user_a, preview["id"])
    second = commit(client, user_a, preview["id"])
    assert first == second
    assert tx_count(db_session, account.id) == 12
    assert db_session.scalar(select(func.count()).select_from(Job)) == 1


def test_cancel_then_commit_is_refused(client: TestClient, user_a: ApiUser, account, db_session):
    preview = upload_ok(client, user_a, account.id, fixture("clean_12_rows.csv"))
    url = f"/api/v1/imports/{preview['id']}"
    cancelled = client.post(f"{url}/cancel", headers=user_a.headers)
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["rows"] == []  # staging rows are deleted
    assert client.post(f"{url}/cancel", headers=user_a.headers).status_code == 200  # idempotent
    refused = client.post(f"{url}/commit", headers=user_a.headers)
    assert refused.status_code == 409
    assert refused.json()["code"] == "import.not_committable"
    assert tx_count(db_session, account.id) == 0


def test_completed_import_cannot_be_cancelled(client: TestClient, user_a: ApiUser, account):
    preview = upload_ok(client, user_a, account.id, fixture("clean_12_rows.csv"))
    commit(client, user_a, preview["id"])
    response = client.post(f"/api/v1/imports/{preview['id']}/cancel", headers=user_a.headers)
    assert response.status_code == 409


def test_uploading_a_previewed_file_again_replaces_the_preview(
    client: TestClient, user_a: ApiUser, account, db_session: Session
):
    first = upload_ok(client, user_a, account.id, fixture("clean_12_rows.csv"))
    second = upload_ok(client, user_a, account.id, fixture("clean_12_rows.csv"))
    assert first["id"] != second["id"]
    listed = client.get("/api/v1/imports", headers=user_a.headers).json()["items"]
    assert [i["id"] for i in listed] == [second["id"]]
    assert (
        db_session.scalar(
            select(func.count()).select_from(ImportRow).where(ImportRow.import_id == first["id"])
        )
        == 0
    )


def test_rows_imported_by_another_file_between_preview_and_commit_are_skipped(
    client: TestClient, user_a: ApiUser, account, db_session: Session
):
    clean = upload_ok(client, user_a, account.id, fixture("clean_12_rows.csv"))
    overlap = upload_ok(client, user_a, account.id, fixture("overlap_nov.csv"))
    commit(client, user_a, overlap["id"])  # adds 8 rows, 4 of them also in `clean`

    result = commit(client, user_a, clean["id"])

    assert (result["rows_imported"], result["rows_skipped"]) == (8, 4)
    assert result["counts"]["already_imported"] == 4
    assert tx_count(db_session, account.id) == 16


def test_conflicting_closing_balance_keeps_the_first_and_warns(
    client: TestClient, user_a: ApiUser, account, db_session: Session
):
    header = b"date,description,amount,balance\n"
    first = upload_ok(client, user_a, account.id, header + b"2026-11-01,a,-10.00,90.00\n",
                      profile="simple_v1")  # fmt: skip
    commit(client, user_a, first["id"])
    second = upload_ok(client, user_a, account.id, header + b"2026-11-01,b,-5.00,85.00\n",
                       profile="simple_v1")  # fmt: skip
    result = commit(client, user_a, second["id"])

    assert [w["code"] for w in result["warnings"]] == ["import.closing_balance_conflict"]
    snapshots = db_session.scalars(
        select(BalanceSnapshot.balance).where(BalanceSnapshot.account_id == account.id)
    ).all()
    assert snapshots == [Decimal("90.00")]


def test_profiles_endpoint(client: TestClient, user_a: ApiUser):
    items = client.get("/api/v1/import-profiles", headers=user_a.headers).json()["items"]
    generic = next(p for p in items if p["id"] == GENERIC)
    assert generic["verified"] is False
    assert generic["verification_note"] == "synthetic, not yet verified against a real export"


# --- property: importing twice equals importing once ----------------------------------------

row_strategy = st.tuples(
    st.integers(min_value=1, max_value=28),  # day of November
    st.integers(min_value=1, max_value=10_000_000),  # paise
    st.booleans(),  # credit?
    st.sampled_from(["UPI/CHAI", "UPI/SWIGGY", "SALARY", "ATM CASH WDL", "upi/chai  "]),
)


@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(rows=st.lists(row_strategy, min_size=1, max_size=30))
def test_property_import_twice_equals_import_once(
    rows: list[tuple[int, int, bool, str]], db_session: Session, user_a: ApiUser
):
    account = add_account(db_session, user_a.id)  # a fresh account per example
    lines = [
        f"2026-11-{day:02d},{text},{'' if credit else '-'}{Decimal(paise) / 100:.2f}"
        for day, paise, credit, text in rows
    ]
    first = ("date,description,amount\n" + "\n".join(lines) + "\n").encode()
    second = first.replace(b"\n", b"\r\n")  # different bytes, same rows

    counts = []
    for data in (first, second):
        record = import_service.create_import(
            db_session,
            user_a.id,
            account_id=account.id,
            profile_id="simple_v1",
            upload=import_service.UploadedFile(data, "s.csv", "text/csv"),
            max_rows=20_000,
        )
        import_service.commit_import(db_session, user_a.id, record.id, now=_NOW)
        counts.append(tx_count(db_session, account.id))

    assert counts[0] == len(rows)  # every row kept, identical ones included
    assert counts[1] == counts[0]
