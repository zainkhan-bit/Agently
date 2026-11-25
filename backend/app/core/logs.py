"""Logging setup. Libraries that see private text must not log, whatever LOG_LEVEL is."""

import logging

# httpx logs URLs at INFO, httpcore logs response headers at DEBUG.
SILENT = ("httpx", "httpcore", "hpack", "h11", "h2")
# SQLAlchemy logs whole result rows at DEBUG, and hide_parameters does not cover those.
QUIET = ("sqlalchemy", "psycopg")


def silence_http_libraries() -> None:
    for name in SILENT:
        logger = logging.getLogger(name)
        logger.setLevel(logging.CRITICAL + 1)  # children inherit it
        logger.propagate = False
        if not logger.handlers:
            logger.addHandler(logging.NullHandler())


def quiet_database_libraries() -> None:
    for name in [*QUIET, *logging.root.manager.loggerDict]:
        if name.split(".")[0] in QUIET:  # children too: one may have a level of its own
            logging.getLogger(name).setLevel(logging.WARNING)


def configure_logging(level: str) -> None:
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    silence_http_libraries()
    quiet_database_libraries()
