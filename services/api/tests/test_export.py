"""M7: export, restore, CSV formula injection, isolation of exports."""

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import API_ROOT
from app.core.security import dev_subject_for
from app.jobs.handlers import HANDLERS
from app.jobs.runner import process_available
from app.models import AccessAudit
from app.services.export import (
    build_export,
    escape_cell,
    read_transactions_csv,
    unescape_cell,
)
from app.tools import dbadmin
from app.tools.demo import Demo, run_demo
from tests.conftest import ApiUser, TokenFactory
from tests.export_restore import restore, unzip
from tests.factories import add_account, add_tx


def export(client: TestClient, user: ApiUser) -> dict[str, bytes]:
    response = client.get("/api/v1/export", headers=user.headers)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["content-disposition"] == (
        'attachment; filename="finance-ai-export-2026-11-18.zip"'
    )
    return unzip(response.content)


@pytest.mark.parametrize(
    ("raw", "escaped"),
    [
        ('=HYPERLINK("http://x")', '\'=HYPERLINK("http://x")'),
        ("+91 call", "'+91 call"),
        ("-5 discount", "'-5 discount"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("\tTAB", "'\tTAB"),
        ("\rCR", "'\rCR"),
        ("'already quoted", "''already quoted"),
        ("UPI/SWIGGY", "UPI/SWIGGY"),
    ],
)
def test_csv_cells_are_escaped_against_formula_injection(raw: str, escaped: str):
    assert escape_cell(raw) == escaped
    assert unescape_cell(escaped) == raw


def test_export_contents_manifest_and_audit(
    client: TestClient, user_a: ApiUser, db_session: Session
):
    account = add_account(db_session, user_a.id)
    add_tx(
        db_session,
        user_a.id,
        account.id,
        date(2026, 11, 3),
        "350.00",
        description="=cmd|' /C calc'!A0",
    )
    add_tx(
        db_session,
        user_a.id,
        account.id,
        date(2026, 11, 4),
        "1000.00",
        "credit",
        description="SALARY",
    )

    files = export(client, user_a)

    assert set(files) == {
        "accounts.json",
        "budgets.json",
        "categories.json",
        "goals.json",
        "imports.json",
        "manifest.json",
        "transaction_events.json",
        "transactions.csv",
    }
    manifest = json.loads(files["manifest.json"])
    assert manifest["format"] == "finance-ai-export/1"
    assert manifest["files"]["transactions.csv"]["rows"] == 2
    assert manifest["files"]["categories.json"]["rows"] == 21
    import hashlib

    for name, entry in manifest["files"].items():
        assert entry["sha256"] == hashlib.sha256(files[name]).hexdigest(), name
    csv_text = files["transactions.csv"].decode()
    assert "'=cmd" in csv_text  # neutralized for spreadsheets
    assert ",=cmd" not in csv_text
    rows = read_transactions_csv(files["transactions.csv"])
    assert rows[0]["description"] == "=cmd|' /C calc'!A0"  # and exactly recoverable
    assert rows[0]["amount"] == "350.00"
    audit = db_session.scalars(
        select(AccessAudit.action).where(AccessAudit.user_id == user_a.id)
    ).all()
    assert "data_exported" in audit


def test_export_is_deterministic(client: TestClient, user_a: ApiUser, db_session: Session):
    account = add_account(db_session, user_a.id)
    add_tx(db_session, user_a.id, account.id, date(2026, 11, 3), "350.00")
    first = client.get("/api/v1/export", headers=user_a.headers).content
    second = client.get("/api/v1/export", headers=user_a.headers).content
    assert first == second


def test_export_never_contains_another_users_data(
    client: TestClient, user_a: ApiUser, user_b: ApiUser, db_session: Session
):
    account = add_account(db_session, user_a.id, "A private account")
    tx = add_tx(
        db_session,
        user_a.id,
        account.id,
        date(2026, 11, 3),
        "350.00",
        description="A's secret purchase",
    )
    b_files = export(client, user_b)
    blob = b"".join(b_files.values())
    for secret in (str(account.id), str(tx.id), "A private account", "A's secret purchase"):
        assert secret.encode() not in blob
    assert json.loads(b_files["manifest.json"])["files"]["transactions.csv"]["rows"] == 0


@contextmanager
def scratch_database(test_database_url: str) -> Iterator[str]:
    url = make_url(test_database_url).set(database="finance_restore_scratch")
    rendered = url.render_as_string(hide_password=False)
    dbadmin.drop_database(rendered)
    dbadmin.create_database(rendered)
    try:
        env = {**os.environ, "DATABASE_URL": rendered}
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=API_ROOT,
            env=env,
            check=True,
            capture_output=True,
        )
        yield rendered
    finally:
        dbadmin.drop_database(rendered)


@pytest.mark.slow
def test_export_restore_export_gives_identical_manifests(
    client: TestClient,
    db_session: Session,
    make_token: TokenFactory,
    clock,
    test_database_url: str,
):
    """The full demo data (imports, edits, refund, transfer, budgets) survives a round trip."""

    @contextmanager
    def scope() -> Iterator[Session]:
        yield db_session

    def token_for(user: str) -> str:
        email = f"demo.{user}@example.test"
        return make_token(dev_subject_for(email), email)

    demo = Demo(
        client=client,
        token_for=token_for,
        run_worker=lambda: process_available(scope, HANDLERS, "w", clock),
    )
    assert all(ok for _, ok, _ in run_demo(demo))
    token = token_for("a")
    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"}).json()
    user = ApiUser(id=me["id"], email=me["email"], token=token)
    original = export(client, user)

    with scratch_database(test_database_url) as url:
        engine = create_engine(url)
        try:
            with Session(engine) as session:
                restored_user = restore(session, original, "restored@example.test")
            with Session(engine) as session:
                again = build_export(session, restored_user)
        finally:
            engine.dispose()

    assert again["manifest.json"] == original["manifest.json"]
    assert json.loads(original["manifest.json"])["files"]["transactions.csv"]["rows"] == 17
