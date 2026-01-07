import logging
import sys


def setup_logging(log_level: str = "INFO") -> logging.Logger:
    """Configure application-wide logging."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    return logging.getLogger("db_viewer")
