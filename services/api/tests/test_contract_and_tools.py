"""The committed OpenAPI contract and the developer tools."""

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine, make_url

from app.tools import dbadmin, openapi_export


def test_committed_openapi_contract_is_current():
    committed = openapi_export.CONTRACT_PATH.read_text(encoding="utf-8")
    assert committed == openapi_export.render_openapi(), (
        "packages/contracts/openapi.json is stale: run `python scripts/dev.py export-openapi`"
    )


def test_openapi_check_mode_reports_up_to_date(capsys: pytest.CaptureFixture[str]):
    assert openapi_export.main(["--check"]) == 0
    assert "up to date" in capsys.readouterr().out


def test_dbadmin_creates_and_drops_only_scratch_databases(test_database_url: str, engine: Engine):
    scratch = make_url(test_database_url).set(database="finance_tooltest_scratch")
    scratch_url = scratch.render_as_string(hide_password=False)

    assert dbadmin.main(["create", scratch_url]) == 0
    assert dbadmin.create_database(scratch_url) is False  # second call is a no-op
    with engine.connect() as connection:
        exists = connection.execute(
            text("SELECT 1 FROM pg_database WHERE datname = 'finance_tooltest_scratch'")
        ).scalar()
    assert exists == 1

    assert dbadmin.main(["drop", scratch_url]) == 0
    with pytest.raises(SystemExit, match="_scratch"):
        dbadmin.drop_database(test_database_url)


def test_dbadmin_rejects_odd_names_and_bad_usage(test_database_url: str):
    odd = make_url(test_database_url).set(database='x"; DROP')
    with pytest.raises(SystemExit, match="unusual"):
        dbadmin.create_database(odd.render_as_string(hide_password=False))
    assert dbadmin.main([]) == 2
