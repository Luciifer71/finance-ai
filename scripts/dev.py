"""Developer commands for the Finance AI backend. Standard library only.

Run from the repository root with the virtualenv's Python:

    Windows:      .venv\\Scripts\\python.exe scripts\\dev.py <command>
    Linux/macOS:  .venv/bin/python scripts/dev.py <command>

Commands
    up              start PostgreSQL in Docker, wait for it, create the test database
    createdb-test   create the finance_test database if missing
    migrate         apply migrations to the dev and test databases
    check           every check CI runs (migrations, round trip, tests, lint, types, contract)
    migration-roundtrip  upgrade/downgrade every migration on a scratch database
    serve           run the API on http://127.0.0.1:8000 with auto-reload
    worker          run the background job worker (add --once to drain and exit)
    seed            create synthetic users A and B with sample data (dev database)
    token EMAIL     print a development access token for EMAIL (AUTH_MODE=dev only)
    export-openapi  write packages/contracts/openapi.json
    backup [FILE]   pg_dump the dev database (custom format) into backups/
    restore FILE --yes   replace the dev database with a backup (destructive)
    demo            every user journey through the API on a scratch database, PASS/FAIL table

Settings come from environment variables; a repo-root .env file (never committed)
is read first if it exists. Always use 127.0.0.1, never localhost (see README).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
API = REPO / "services" / "api"
COMPOSE_FILE = REPO / "infra" / "docker-compose.yml"
BACKUP_DIR = REPO / "backups"
PYTHON = sys.executable

DEFAULT_DEV_URL = "postgresql+psycopg://finance:finance@127.0.0.1:5432/finance"
DEFAULT_TEST_URL = "postgresql+psycopg://finance:finance@127.0.0.1:5432/finance_test"
SCRATCH_DB = "finance_scratch"


# --- environment ---------------------------------------------------------------------


def _read_dotenv(path: Path) -> dict[str, str]:
    """Minimal KEY=VALUE parser; ignores comments and blank lines."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def base_env() -> dict[str, str]:
    env = dict(os.environ)
    for key, value in _read_dotenv(REPO / ".env").items():
        env.setdefault(key, value)
    env.setdefault("DATABASE_URL", DEFAULT_DEV_URL)
    env.setdefault("TEST_DATABASE_URL", DEFAULT_TEST_URL)
    env.setdefault("PYTHONUTF8", "1")
    return env


def _with_database(url: str, name: str) -> str:
    base, _, _ = url.rpartition("/")
    return f"{base}/{name}"


def run(args: list[str], *, env: dict[str, str] | None = None, cwd: Path = API) -> int:
    print(f"\n$ {' '.join(args)}", flush=True)
    return subprocess.call(args, cwd=cwd, env=env or base_env())


def alembic(url: str, *args: str) -> int:
    env = base_env()
    env["DATABASE_URL"] = url
    return run([PYTHON, "-m", "alembic", *args], env=env)


def docker_compose(*args: str) -> list[str]:
    if shutil.which("docker") is None:
        raise SystemExit("Docker is not installed or not on PATH.")
    return ["docker", "compose", "-f", str(COMPOSE_FILE), *args]


# --- commands ------------------------------------------------------------------------


def cmd_up(_: argparse.Namespace) -> int:
    if run(docker_compose("up", "-d"), cwd=REPO) != 0:
        return 1
    print("Waiting for PostgreSQL ...", flush=True)
    for _attempt in range(60):
        ready = subprocess.call(
            docker_compose(
                "exec", "-T", "postgres", "pg_isready", "-U", "finance", "-d", "finance"
            ),
            cwd=REPO,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if ready == 0:
            print("PostgreSQL is ready.")
            return cmd_createdb_test(_)
        time.sleep(1)
    print("PostgreSQL did not become ready in 60 seconds.", file=sys.stderr)
    return 1


def cmd_createdb_test(_: argparse.Namespace) -> int:
    env = base_env()
    return run([PYTHON, "-m", "app.tools.dbadmin", "create", env["TEST_DATABASE_URL"]], env=env)


def cmd_migrate(_: argparse.Namespace) -> int:
    env = base_env()
    for url in (env["DATABASE_URL"], env["TEST_DATABASE_URL"]):
        if alembic(url, "upgrade", "head") != 0:
            return 1
    return 0


def migration_round_trip(env: dict[str, str]) -> int:
    """upgrade head -> downgrade -1 -> upgrade head -> downgrade base -> upgrade head."""
    scratch = _with_database(env["TEST_DATABASE_URL"], SCRATCH_DB)
    steps: list[list[str]] = [
        [PYTHON, "-m", "app.tools.dbadmin", "drop", scratch],
        [PYTHON, "-m", "app.tools.dbadmin", "create", scratch],
    ]
    for args in steps:
        if run(args, env=env) != 0:
            return 1
    for direction, target in (
        ("upgrade", "head"),
        ("downgrade", "-1"),
        ("upgrade", "head"),
        ("downgrade", "base"),
        ("upgrade", "head"),
    ):
        if alembic(scratch, direction, target) != 0:
            return 1
    return run([PYTHON, "-m", "app.tools.dbadmin", "drop", scratch], env=env)


def cmd_check(_: argparse.Namespace) -> int:
    env = base_env()
    test_url = env["TEST_DATABASE_URL"]

    def command(args: list[str]) -> Callable[[], int]:
        return lambda: run(args, env=env)

    steps: list[tuple[str, Callable[[], int]]] = [
        (
            "create test database",
            command([PYTHON, "-m", "app.tools.dbadmin", "create", test_url]),
        ),
        ("migrate test database", lambda: alembic(test_url, "upgrade", "head")),
        ("alembic check", lambda: alembic(test_url, "check")),
        ("migration round trip", lambda: migration_round_trip(env)),
        (
            "pytest + coverage",
            command([PYTHON, "-m", "pytest", "tests", "-q", "--cov", "--cov-fail-under=85"]),
        ),
        (
            "ruff lint",
            command([PYTHON, "-m", "ruff", "check", "app", "tests", "migrations"]),
        ),
        (
            "ruff format",
            command(
                [
                    PYTHON,
                    "-m",
                    "ruff",
                    "format",
                    "--check",
                    "app",
                    "tests",
                    "migrations",
                ]
            ),
        ),
        ("mypy --strict", command([PYTHON, "-m", "mypy"])),
        (
            "openapi drift",
            command([PYTHON, "-m", "app.tools.openapi_export", "--check"]),
        ),
    ]
    results: list[tuple[str, bool]] = []
    for name, step in steps:
        code = step()
        results.append((name, code == 0))
        if code != 0:
            break
    print("\n" + "=" * 50)
    for name, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    skipped = [name for name, _ in steps[len(results) :]]
    for name in skipped:
        print(f"  SKIP  {name}")
    print("=" * 50)
    return 0 if all(ok for _, ok in results) and not skipped else 1


def cmd_serve(_: argparse.Namespace) -> int:
    return run(
        [
            PYTHON,
            "-m",
            "uvicorn",
            "app.main:app",
            "--reload",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ]
    )


def cmd_worker(args: argparse.Namespace) -> int:
    return run([PYTHON, "-m", "app.worker", *(["--once"] if args.once else [])])


def cmd_seed(_: argparse.Namespace) -> int:
    return run([PYTHON, "-m", "app.tools.seed"])


def cmd_token(args: argparse.Namespace) -> int:
    return run([PYTHON, "-m", "app.tools.devtoken", args.email])


def cmd_export_openapi(_: argparse.Namespace) -> int:
    return run([PYTHON, "-m", "app.tools.openapi_export"])


def cmd_backup(args: argparse.Namespace) -> int:
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = Path(args.file) if args.file else BACKUP_DIR / f"finance-{stamp}.dump"
    print(f"Writing {target}")
    with target.open("wb") as out:
        code = subprocess.call(
            docker_compose(
                "exec",
                "-T",
                "postgres",
                "pg_dump",
                "-Fc",
                "-U",
                "finance",
                "-d",
                "finance",
            ),
            cwd=REPO,
            stdout=out,
        )
    if code != 0 or target.stat().st_size == 0:
        print("Backup failed.", file=sys.stderr)
        return 1
    print(f"Backup written: {target} ({target.stat().st_size} bytes)")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    source = Path(args.file)
    if not source.is_file():
        print(f"No such backup file: {source}", file=sys.stderr)
        return 1
    if not args.yes:
        print("Restore REPLACES the dev database 'finance'. Re-run with --yes to confirm.")
        return 1
    with source.open("rb") as data:
        code = subprocess.call(
            docker_compose(
                "exec",
                "-T",
                "postgres",
                "pg_restore",
                "--clean",
                "--if-exists",
                "--no-owner",
                "-U",
                "finance",
                "-d",
                "finance",
            ),
            cwd=REPO,
            stdin=data,
        )
    print("Restore finished." if code == 0 else "Restore reported errors.")
    return code


def cmd_demo(_: argparse.Namespace) -> int:
    env = base_env()
    scratch = _with_database(env["TEST_DATABASE_URL"], "finance_demo_scratch")
    for args in (
        [PYTHON, "-m", "app.tools.dbadmin", "drop", scratch],
        [PYTHON, "-m", "app.tools.dbadmin", "create", scratch],
    ):
        if run(args, env=env) != 0:
            return 1
    if alembic(scratch, "upgrade", "head") != 0:
        return 1
    env["DEMO_DATABASE_URL"] = scratch
    code = run([PYTHON, "-m", "app.tools.demo"], env=env)
    run([PYTHON, "-m", "app.tools.dbadmin", "drop", scratch], env=env)
    return code


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("up").set_defaults(func=cmd_up)
    sub.add_parser("createdb-test").set_defaults(func=cmd_createdb_test)
    sub.add_parser("migrate").set_defaults(func=cmd_migrate)
    sub.add_parser("check").set_defaults(func=cmd_check)
    sub.add_parser("migration-roundtrip").set_defaults(
        func=lambda _: migration_round_trip(base_env())
    )
    sub.add_parser("serve").set_defaults(func=cmd_serve)
    worker = sub.add_parser("worker")
    worker.add_argument("--once", action="store_true")
    worker.set_defaults(func=cmd_worker)
    sub.add_parser("seed").set_defaults(func=cmd_seed)
    token = sub.add_parser("token")
    token.add_argument("email")
    token.set_defaults(func=cmd_token)
    sub.add_parser("export-openapi").set_defaults(func=cmd_export_openapi)
    backup = sub.add_parser("backup")
    backup.add_argument("file", nargs="?")
    backup.set_defaults(func=cmd_backup)
    restore = sub.add_parser("restore")
    restore.add_argument("file")
    restore.add_argument("--yes", action="store_true")
    restore.set_defaults(func=cmd_restore)
    sub.add_parser("demo").set_defaults(func=cmd_demo)
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
