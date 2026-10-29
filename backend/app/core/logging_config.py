"""Structured JSON logging configuration for PingCRM.

Provides:
- JSON-formatted log output for machine-parseable logs (AI-friendly)
- Rotating file handler (10MB, 5 backups) to logs/pingcrm.log
- Environment-based log level control via LOG_LEVEL env var
- Per-module overrides via LOG_LEVEL_SQL, LOG_LEVEL_CELERY env vars
"""
import logging
import logging.config
import os
from pathlib import Path


# Keys whose values can carry user message content or prompts. The LLM SDKs
# log request payloads at DEBUG; even at WARNING, application loggers may pass
# a request dict as a formatting argument. Handlers redact these centrally so a
# single leaked log call cannot put contact message bodies on disk.
_SENSITIVE_KEYS = frozenset(
    {
        "body",
        "content",
        "input",
        "messages",
        "prompt",
        "system",
        "system_prompt",
        "text",
    }
)

_REDACTED = "[REDACTED]"


def _redact_value(value):
    """Recursively replace sensitive dict values with ``[REDACTED]``."""
    if isinstance(value, dict):
        return {
            key: (
                _REDACTED
                if isinstance(key, str) and key.lower() in _SENSITIVE_KEYS
                else _redact_value(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item) for item in value)
    return value


class RedactMessagesFilter(logging.Filter):
    """Strip message/prompt content from every record passing a handler.

    Attached to handlers rather than loggers: a logger-level filter would be
    bypassed by propagation, whereas every emitted record must pass through a
    handler to reach stdout or the log file.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            if isinstance(record.args, dict):
                record.args = _redact_value(record.args)
            else:
                record.args = tuple(_redact_value(arg) for arg in record.args)

        # ``logger.info("...", extra={"messages": ...})`` lands directly in the
        # record's __dict__, not in args.
        for key in list(record.__dict__):
            if key.lower() in _SENSITIVE_KEYS:
                record.__dict__[key] = _REDACTED

        return True


def _has_json_logger() -> bool:
    try:
        import pythonjsonlogger.jsonlogger  # noqa: F401
        return True
    except ImportError:
        return False


def setup_logging() -> None:
    """Configure structured JSON logging for the application.

    Falls back to simple text formatting if python-json-logger is not installed
    (e.g. in test environments).
    """
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level_sql = os.getenv("LOG_LEVEL_SQL", "WARNING").upper()
    log_level_celery = os.getenv("LOG_LEVEL_CELERY", log_level).upper()
    use_json = _has_json_logger()

    # Ensure logs directory exists
    log_dir = Path(__file__).resolve().parent.parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = str(log_dir / "pingcrm.log")

    formatters: dict = {
        "simple": {
            "format": "%(asctime)s %(levelname)-8s %(name)s — %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    }
    if use_json:
        formatters["json"] = {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
            "rename_fields": {
                "levelname": "level",
                "asctime": "timestamp",
            },
            "timestamp": True,
        }

    fmt_name = "json" if use_json else "simple"

    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": formatters,
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": fmt_name,
                "stream": "ext://sys.stdout",
            },
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": fmt_name,
                "filename": log_file,
                "maxBytes": 10_485_760,  # 10 MB
                "backupCount": 5,
                "encoding": "utf-8",
            },
        },
        "loggers": {
            # Quiet SQLAlchemy engine logs (very noisy at INFO)
            "sqlalchemy.engine": {
                "level": log_level_sql,
                "handlers": ["console", "file"],
                "propagate": False,
            },
            # Celery loggers
            "celery": {
                "level": log_level_celery,
                "handlers": ["console", "file"],
                "propagate": False,
            },
            "celery.task": {
                "level": log_level_celery,
                "handlers": ["console", "file"],
                "propagate": False,
            },
            # Quiet noisy third-party libs
            "httpx": {"level": "WARNING"},
            "httpcore": {"level": "WARNING"},
            "hpack": {"level": "WARNING"},
            "telethon": {"level": "WARNING"},
            # LLM SDKs log full request bodies (including prompts and contact
            # message content) at DEBUG/INFO. Keep them at WARNING regardless
            # of LOG_LEVEL; RedactMessagesFilter is the second line of defense.
            "anthropic": {"level": "WARNING"},
            "openai": {"level": "WARNING"},
        },
        "root": {
            "level": log_level,
            "handlers": ["console", "file"],
        },
    }

    logging.config.dictConfig(config)

    # Add correlation filter to all handlers so request_id/task_id appear in logs
    from app.core.request_context import CorrelationFilter
    correlation_filter = CorrelationFilter()
    redact_filter = RedactMessagesFilter()
    for handler in logging.root.handlers:
        handler.addFilter(correlation_filter)
        # setup_logging() can run more than once (e.g. re-imported app modules
        # in tests); don't stack duplicate filters.
        if not any(isinstance(f, RedactMessagesFilter) for f in handler.filters):
            handler.addFilter(redact_filter)
