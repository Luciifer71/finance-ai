"""Background worker: ``python -m app.worker`` (``--once`` drains the queue and exits).

Runs beside the API from the same image. Polls the PostgreSQL ``jobs`` table;
no Redis or other broker is needed.
"""

import argparse
import logging
import os
import signal
import socket
import time
import uuid
from types import FrameType

from app.core.clock import SystemClock
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.database import create_db_engine, create_session_factory
from app.jobs.handlers import HANDLERS
from app.jobs.runner import process_available, session_scope_from

logger = logging.getLogger("app.worker")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="process ready jobs, then exit")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_db_engine(settings.database_url)
    scope = session_scope_from(create_session_factory(engine))
    worker_id = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    clock = SystemClock()

    stopping = False

    def stop(signum: int, frame: FrameType | None) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    logger.info("worker_started", extra={"once": args.once})
    try:
        while not stopping:
            ran = process_available(scope, HANDLERS, worker_id, clock)
            if args.once:
                logger.info("worker_drained", extra={"jobs": ran})
                break
            if ran == 0:
                time.sleep(args.poll_seconds)
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
