"""Knows which Alembic revision is the newest one shipped with this code."""

from functools import lru_cache

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.core.config import API_ROOT


@lru_cache(maxsize=1)
def head_revision() -> str | None:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    return ScriptDirectory.from_config(config).get_current_head()
