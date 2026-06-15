"""Application-wide logging configuration.

Configured at import time (before uvicorn sets up its loggers).
Uvicorn's LOGGING_CONFIG has disable_existing_loggers=False and only
touches uvicorn/uvicorn.error/uvicorn.access — our "app" hierarchy
is left untouched.
"""

import logging
import logging.config
import os

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


def configure() -> None:
    """Apply logging configuration. Idempotent — safe for --reload."""

    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": (
                    "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
                ),
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "default",
            },
        },
        "loggers": {
            "app": {
                "handlers": ["console"],
                "level": LOG_LEVEL,
                "propagate": False,
            },
        },
    })
