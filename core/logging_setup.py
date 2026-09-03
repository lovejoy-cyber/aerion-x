"""Single place that configures logging for every entry point (scripts, future
backend). Call configure_logging() once at process start.
"""
from __future__ import annotations

import logging

from core.config import settings


def configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
