"""The end-to-end demo (`scripts/dev.py demo`) passes against the test app."""

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.clock import FixedClock
from app.core.security import dev_subject_for
from app.jobs.handlers import HANDLERS
from app.jobs.runner import process_available
from app.tools.demo import Demo, print_table, run_demo
from tests.conftest import TokenFactory


def test_every_demo_step_passes(
    client: TestClient,
    db_session: Session,
    make_token: TokenFactory,
    clock: FixedClock,
    capsys,
):
    @contextmanager
    def scope() -> Iterator[Session]:
        yield db_session

    def token_for(user: str) -> str:
        email = f"demo.{user}@example.test"
        return make_token(dev_subject_for(email), email)

    demo = Demo(
        client=client,
        token_for=token_for,
        run_worker=lambda: process_available(scope, HANDLERS, "demo-worker", clock),
    )
    results = run_demo(demo)
    print_table(results)

    failed = [(step, detail) for step, ok, detail in results if not ok]
    assert failed == []
    assert len(results) == 26
    assert "26/26 checks passed" in capsys.readouterr().out
