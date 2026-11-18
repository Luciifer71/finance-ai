"""Print a development access token: ``python -m app.tools.devtoken you@example.com``.

Only works with ``APP_ENV=development`` and ``AUTH_MODE=dev``. The same email
always gets the same user id, so the mobile app can sign in as user A or B
before Supabase is set up. Tokens last 24 hours.
"""

import sys

from app.core.clock import SystemClock
from app.core.config import Settings
from app.core.security import dev_subject_for, load_or_create_dev_key, mint_token


def main(argv: list[str]) -> int:
    if len(argv) != 1 or "@" not in argv[0]:
        print("usage: python -m app.tools.devtoken <email>", file=sys.stderr)
        return 2
    settings = Settings()
    if settings.app_env != "development" or settings.auth_mode != "dev":
        print("dev tokens need APP_ENV=development and AUTH_MODE=dev", file=sys.stderr)
        return 1
    email = argv[0].strip().lower()
    token = mint_token(
        load_or_create_dev_key(settings.dev_keys_dir),
        subject=dev_subject_for(email),
        email=email,
        issuer=settings.dev_issuer,
        audience=settings.auth_audience,
        now=SystemClock().now(),
    )
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
