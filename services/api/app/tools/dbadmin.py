"""Create or drop a local database. Used by ``scripts/dev.py``.

    python -m app.tools.dbadmin create <database url>
    python -m app.tools.dbadmin drop <database url>    (only *_scratch databases)

Connects to the server's ``postgres`` maintenance database with the same
credentials, so it works the same against Docker on Windows and in CI.
"""

import re
import sys

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

_SAFE_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _maintenance_conninfo(database_url: str) -> tuple[str, str]:
    url = make_url(database_url)
    name = url.database or ""
    if not _SAFE_NAME.match(name):
        raise SystemExit(f"refusing unusual database name: {name!r}")
    conninfo = psycopg.conninfo.make_conninfo(
        host=url.host or "127.0.0.1",
        port=url.port or 5432,
        user=url.username or "",
        password=url.password or "",
        dbname="postgres",
        connect_timeout=5,
    )
    return conninfo, name


def create_database(database_url: str) -> bool:
    """Create the database named in the URL. Returns False if it already existed."""
    conninfo, name = _maintenance_conninfo(database_url)
    with psycopg.connect(conninfo, autocommit=True) as connection:
        exists = connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (name,)
        ).fetchone()
        if exists:
            return False
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        return True


def drop_database(database_url: str) -> None:
    """Drop a scratch database. Refuses anything not named ``*_scratch``."""
    conninfo, name = _maintenance_conninfo(database_url)
    if not name.endswith("_scratch"):
        raise SystemExit("drop is only allowed for databases named *_scratch")
    with psycopg.connect(conninfo, autocommit=True) as connection:
        connection.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
        )


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] not in {"create", "drop"}:
        print("usage: python -m app.tools.dbadmin create|drop <database url>", file=sys.stderr)
        return 2
    action, database_url = argv
    if action == "create":
        created = create_database(database_url)
        print("created" if created else "already exists")
    else:
        drop_database(database_url)
        print("dropped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
