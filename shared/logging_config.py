# shared/logging_config.py
"""
Structured logging setup using structlog.
Every service imports this and gets consistent 
JSON logs that work with OpenTelemetry.
"""

import logging
import structlog
from shared.config import settings


def setup_logging() -> None:
    """Call this once at application startup"""
    
    log_level = getattr(logging, settings.log_level.upper())
    
    # Configure structlog processors
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]
    
    if settings.environment == "development":
        # Human-readable in dev
        processors.append(structlog.dev.ConsoleRenderer())
    else:
        # JSON in production
        processors.append(structlog.processors.JSONRenderer())
    
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    logging.basicConfig(
        format="%(message)s",
        stream=None,
        level=log_level,
    )


def get_logger(name: str):
    """Get a structured logger for a module"""
    return structlog.get_logger(name)