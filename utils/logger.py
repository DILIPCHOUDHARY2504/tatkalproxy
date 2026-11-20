"""
Tatkal Proxy - Logging Utility
Configures clean, structured logging with sensitive data masking.
"""

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from config import settings


class SensitiveDataFilter(logging.Filter):
    """Filter that scrubs tokens, passwords, and secrets from log records."""

    PATTERNS = [
        (re.compile(r"bot\d+:[A-Za-z0-9_-]{20,}", re.IGNORECASE), "bot[REDACTED_BOT_TOKEN]"),
        (re.compile(r"token=[A-Za-z0-9_\-\.]{15,}", re.IGNORECASE), "token=[REDACTED]"),
        (re.compile(r"password=['\"]?[^\s'\"]+['\"]?", re.IGNORECASE), "password=[REDACTED]"),
        (re.compile(r"pass=['\"]?[^\s'\"]+['\"]?", re.IGNORECASE), "pass=[REDACTED]"),
        (re.compile(r":([a-zA-Z0-9_\-\.@]+):([a-zA-Z0-9_\-\.@]+)@"), ":[REDACTED_USER]:[REDACTED_PASS]@"),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            msg = record.msg
            for pattern, repl in self.PATTERNS:
                msg = pattern.sub(repl, msg)
            record.msg = msg
        return True


def setup_logger(name: str = "TatkalProxy") -> logging.Logger:
    """Configures application logger with rotating file and console handlers."""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, settings.LOG_LEVEL, logging.INFO))

    # Prevent duplicate handlers if called multiple times
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s:%(lineno)d]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    sensitive_filter = SensitiveDataFilter()

    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(sensitive_filter)
    logger.addHandler(console_handler)

    # Rotating File Handler
    log_file = settings.LOGS_DIR / "tatkalproxy.log"
    try:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(sensitive_filter)
        logger.addHandler(file_handler)
    except Exception as e:
        console_handler.handle(
            logging.LogRecord(
                name,
                logging.WARNING,
                __file__,
                0,
                f"Could not initialize file logger: {e}",
                (),
                None,
            )
        )

    return logger


logger = setup_logger()
