"""End-to-end demo: every user journey through the HTTP API, with checked results.

    python scripts/dev.py demo

``dev.py`` creates a scratch database, migrates it, runs this module against it
(``DEMO_DATABASE_URL``) and drops it afterwards. Each step compares the API's
answer with a value worked out by hand from the synthetic statements in
``tests/fixtures/statements`` and prints a PASS/FAIL table. Exit code 1 if any
step fails. Nothing is written to your dev database.
"""

import os
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.core.clock import SystemClock
from app.core.config import API_ROOT, Settings
from app.core.security import (
    StaticKeyProvider,
    TokenVerifier,
    dev_subject_for,
    key_id_for,
    load_or_create_dev_key,
    mint_token,
)
from app.jobs.handlers import HANDLERS
from app.jobs.runner import process_available, session_scope_from

FIXTURES = API_ROOT / "tests" / "fixtures" / "statements"


@dataclass
class Demo:
    client: TestClient
    token_for: Callable[[str], str]
    run_worker: Callable[[], int]
    results: list[tuple[str, bool, str]] = field(default_factory=list)
    ids: dict[str, str] = field(default_factory=dict)

    def check(self, step: str, ok: bool, detail: str = "") -> bool:
        self.results.append((step, ok, detail))
        return ok

    def call(self, method: str, url: str, user: str = "a", **kw: Any) -> tuple[int, Any]:
        headers = {"Authorization": f"Bearer {self.token_for(user)}"} if user else {}
        response = self.client.request(method, url, headers=headers, **kw)
        body = response.json() if response.content else None
        return response.status_code, body

    def upload(self, account: str, name: str, profile: str = "generic_indian_bank_v1") -> Any:
        return self.call(
            "POST",
            "/api/v1/imports",
            files={"file": (name, (FIXTURES / name).read_bytes(), "text/csv")},
            data={"account_id": account, "profile_id": profile},
        )


def _expect(demo: Demo, step: str, got: Any, expected: Any) -> bool:
    return demo.check(step, got == expected, "" if got == expected else f"got {got!r}")


def run_demo(demo: Demo) -> list[tuple[str, bool, str]]:
    d = demo
    # Journey 1: sign in to a private account
    status, _ = d.call("GET", "/api/v1/me")
    _expect(d, "1  sign in (GET /me)", status, 200)
    status, _ = d.call("GET", "/api/v1/accounts", user="")
    _expect(d, "1  no token -> 401", status, 401)

    # Journey 2: accounts and an opening balance
    status, bank = d.call(
        "POST",
        "/api/v1/accounts",
        json={"name": "HDFC Savings", "account_type": "bank", "last4": "1531"},
    )
    _expect(d, "2  create bank account", (status, bank["balance"]["reason"]), (201, "no_anchor"))
    status, cash = d.call(
        "POST", "/api/v1/accounts", json={"name": "Wallet cash", "account_type": "cash"}
    )
    bank_id, cash_id = bank["id"], cash["id"]
    status, opening = d.call(
        "POST",
        f"/api/v1/accounts/{cash_id}/opening-balance",
        json={"as_of": "2026-10-01", "balance": "500.00"},
    )
    _expect(
        d,
        "2  opening balance is an estimate",
        (opening["balance"], opening["reason"]),
        ("500.00", "no_statement"),
    )

    # Journey 3: import a statement (preview, commit, re-import adds nothing)
    status, preview = d.upload(bank_id, "clean_12_rows.csv")
    _expect(
        d,
        "3  preview: 12 valid rows, closing 34125.00",
        (status, preview["counts"]["valid"], preview["closing_balance"]),
        (201, 12, "34125.00"),
    )
    status, done = d.call("POST", f"/api/v1/imports/{preview['id']}/commit")
    _expect(d, "3  commit adds 12 rows", (done["status"], done["rows_imported"]), ("completed", 12))
    status, again = d.upload(bank_id, "clean_12_rows.csv")
    _expect(
        d, "3  same file again -> 409", (status, again["code"]), (409, "import.already_imported")
    )

    # Background categorization
    _expect(d, "3  worker ran the categorize job", d.run_worker(), 1)
    status, job = d.call("GET", f"/api/v1/jobs/{done['categorize_job_id']}")
    _expect(d, "3  job succeeded", job["status"], "succeeded")

    # Journey 4: verified balance and categorized rows
    status, balance = d.call("GET", f"/api/v1/accounts/{bank_id}/balance")
    _expect(
        d,
        "4  balance 34125.00 verified",
        (balance["balance"], balance["status"]),
        ("34125.00", "verified"),
    )
    status, page = d.call("GET", "/api/v1/transactions?limit=50")
    rows = {t["description"]: t for t in page["items"]}
    categories = {c["name"]: c["id"] for c in d.call("GET", "/api/v1/categories")[1]["items"]}
    swiggy = rows["UPI/SWIGGY/402711112222/FOOD"]
    _expect(
        d,
        "4  Swiggy auto-categorized (rule)",
        (swiggy["category_id"], swiggy["category_source"]),
        (categories["Food & Dining"], "rule"),
    )

    # Journey 5: search
    status, found = d.call("GET", "/api/v1/transactions?q=swiggy")
    _expect(d, "5  search 'swiggy' finds 1 row", len(found["items"]), 1)

    # Journey 6: edit (audited), refund link, cash withdrawal as a transfer
    salary = rows["SALARY OCT ACME SYNTHETIC LTD"]
    status, edited = d.call(
        "PATCH",
        f"/api/v1/transactions/{salary['id']}",
        json={"category_id": categories["Salary"], "notes": "October salary"},
    )
    _expect(d, "6  edit writes one audit event", (status, len(edited["events"])), (200, 1))
    status, suggestions = d.call("GET", "/api/v1/refunds/suggestions")
    pairs = [
        (s["refund"]["description"], s["original"]["description"]) for s in suggestions["items"]
    ]
    _expect(
        d,
        "6  refund suggestion found",
        pairs,
        [("UPI/AMAZON/402711117777/REFUND", "UPI/AMAZON/402711116666/ORDER")],
    )
    if suggestions["items"]:
        first = suggestions["items"][0]
        status, linked = d.call(
            "POST",
            "/api/v1/refunds",
            json={
                "refund_transaction_id": first["refund"]["id"],
                "original_transaction_id": first["original"]["id"],
            },
        )
        _expect(d, "6  refund linked", linked["transaction_type"], "refund")
    status, transfers = d.call("GET", "/api/v1/transfers/suggestions")
    cash_suggestions = transfers["cash_withdrawals"]
    _expect(
        d,
        "6  ATM withdrawal suggested",
        [s["action"] for s in cash_suggestions],
        ["transfer_to_cash_account"],
    )
    if cash_suggestions:
        status, _ = d.call(
            "POST",
            "/api/v1/transfers/cash-withdrawals",
            json={
                "transaction_id": cash_suggestions[0]["transaction"]["id"],
                "cash_account_id": cash_id,
            },
        )
    status, cash_balance = d.call("GET", f"/api/v1/accounts/{cash_id}/balance")
    _expect(d, "6  cash wallet 500 + 5000 = 5500.00", cash_balance["balance"], "5500.00")

    # Journey 5 again: October report (hand-calculated in the M6 learning note's style)
    status, october = d.call("GET", "/api/v1/reports/summary?period=month&date=2026-10-15")
    _expect(
        d,
        "5  October totals",
        october["totals"],
        {
            "gross_spending": "33497.45",
            "refunds": "2499.00",
            "net_spending": "30998.45",
            "income": "60123.45",
            "net_cash_flow": "29125.00",
        },
    )

    # Journey 3 again: an overlapping statement adds only new rows and reconciles
    status, overlap = d.upload(bank_id, "overlap_nov.csv")
    _expect(
        d,
        "3  overlap: 4 already imported, 4 new",
        (overlap["counts"]["already_imported"], overlap["counts"]["valid"]),
        (4, 4),
    )
    status, _ = d.call("POST", f"/api/v1/imports/{overlap['id']}/commit")
    d.run_worker()
    status, balance = d.call("GET", f"/api/v1/accounts/{bank_id}/balance")
    _expect(
        d,
        "4  balance 91418.50 verified",
        (balance["balance"], balance["status"]),
        ("91418.50", "verified"),
    )
    status, recon = d.call("GET", f"/api/v1/accounts/{bank_id}/reconciliation")
    _expect(d, "4  statements reconcile", recon["status"], "ok")

    # Journey 7: budgets
    d.call(
        "POST",
        "/api/v1/budgets",
        json={"category_id": categories["Food & Dining"], "month": "2026-11", "amount": "400.00"},
    )
    d.call("POST", "/api/v1/budgets", json={"month": "2026-11", "amount": "5000.00"})
    status, budgets = d.call("GET", "/api/v1/budgets/status?month=2026-11")
    by_name = {b["category_name"]: b for b in budgets["items"]}
    _expect(
        d,
        "7  Food budget over (520.00 of 400.00)",
        (by_name["Food & Dining"]["spent"], by_name["Food & Dining"]["status"]),
        ("520.00", "over"),
    )
    _expect(
        d,
        "7  total budget ok (2706.50 of 5000.00)",
        (by_name[None]["spent"], by_name[None]["status"]),
        ("2706.50", "ok"),
    )

    # Privacy: user B sees none of A's data
    status, b_accounts = d.call("GET", "/api/v1/accounts", user="b")
    _expect(d, "1  user B sees no accounts", b_accounts["items"], [])
    status, _ = d.call("GET", f"/api/v1/accounts/{bank_id}", user="b")
    _expect(d, "1  user B reading A's account -> 404", status, 404)
    status, b_tx = d.call("GET", "/api/v1/transactions", user="b")
    _expect(d, "1  user B sees no transactions", b_tx["items"], [])
    return d.results


def print_table(results: list[tuple[str, bool, str]]) -> None:
    width = max(len(step) for step, _, _ in results)
    print("\n" + "=" * (width + 12))
    for step, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {step.ljust(width)}  {detail}")
    passed = sum(ok for _, ok, _ in results)
    print("=" * (width + 12))
    print(f"  {passed}/{len(results)} checks passed")


def main() -> int:
    from app.main import create_app

    database_url = os.environ.get("DEMO_DATABASE_URL")
    if not database_url:
        print("Run this through `python scripts/dev.py demo`.", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as keys:
        key = load_or_create_dev_key(Path(keys))
        settings = Settings(
            app_env="test", database_url=database_url, rate_limit_enabled=False, log_level="WARNING"
        )
        verifier = TokenVerifier(
            StaticKeyProvider({key_id_for(key.public_key()): (key.public_key(), "ES256")}),
            issuer="finance-ai-demo",
            audience="authenticated",
            algorithms=["ES256"],
        )
        app = create_app(settings, token_verifier=verifier)
        scope = session_scope_from(app.state.session_factory)
        clock = SystemClock()

        def token_for(user: str) -> str:
            email = f"demo.{user}@example.test"
            return mint_token(
                key,
                subject=dev_subject_for(email),
                email=email,
                issuer="finance-ai-demo",
                audience="authenticated",
                now=clock.now(),
            )

        demo = Demo(
            client=TestClient(app),
            token_for=token_for,
            run_worker=lambda: process_available(scope, HANDLERS, "demo-worker", clock),
        )
        try:
            results = run_demo(demo)
        except Exception as exc:  # a crash is a failed demo, reported in the table
            results = [*demo.results, ("demo crashed", False, type(exc).__name__)]
        finally:
            app.state.engine.dispose()
    print_table(results)
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
