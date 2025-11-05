import logging
import sys
from pathlib import Path
from typing import Optional


class ColoredFormatter(logging.Formatter):
    """Custom formatter with colors for better readability in terminal."""

    # ANSI color codes
    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
        "RESET": "\033[0m",  # Reset
        "BOLD": "\033[1m",  # Bold
        "DIM": "\033[2m",  # Dim
    }

    def format(self, record):
        """Format log record with colors."""
        # Save original levelname
        original_levelname = record.levelname

        # Add color to level name
        if record.levelname in self.COLORS:
            record.levelname = (
                f"{self.COLORS[record.levelname]}"
                f"{self.COLORS['BOLD']}"
                f"{record.levelname:8}"
                f"{self.COLORS['RESET']}"
            )

        # Format the message
        formatted = super().format(record)

        # Restore original levelname
        record.levelname = original_levelname

        return formatted


class SimpleFormatter(logging.Formatter):
    """Simple formatter without colors for file logging."""

    def format(self, record):
        """Format log record without colors."""
        return super().format(record)


def setup_logger(
    name: str = "screenseeker",
    level: str = "INFO",
    log_to_file: bool = False,
    log_file_path: Optional[Path] = None,
    use_colors: bool = True,
) -> logging.Logger:
    """
    Set up and configure the application logger.

    Args:
        name: Logger name (default: "screenseeker")
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_to_file: Whether to also log to a file
        log_file_path: Path to log file (default: output/scraper.log)
        use_colors: Whether to use colored output in console

    Returns:
        Configured logger instance
    """
    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))

    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()

    # Console handler with colors
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)

    if use_colors and sys.stdout.isatty():
        # Use colored formatter for terminal
        console_format = (
            f"%(levelname)s "
            f"{ColoredFormatter.COLORS['DIM']}%(name)s{ColoredFormatter.COLORS['RESET']} "
            f"→ %(message)s"
        )
        console_formatter = ColoredFormatter(console_format)
    else:
        # Use simple formatter for non-terminal (e.g., piped output)
        console_format = "%(levelname)-8s %(name)s → %(message)s"
        console_formatter = SimpleFormatter(console_format)

    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # File handler (optional)
    if log_to_file:
        if log_file_path is None:
            log_file_path = Path("output/scraper.log")

        log_file_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file_path, mode="a", encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)

        # File format with timestamp
        file_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        file_formatter = SimpleFormatter(file_format, datefmt="%Y-%m-%d %H:%M:%S")

        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

    return logger


def get_logger(module_name: str = None) -> logging.Logger:
    """
    Get a logger instance for a specific module.

    Args:
        module_name: Name of the module (typically __name__)

    Returns:
        Logger instance

    Example:
        from logger import get_logger
        logger = get_logger(__name__)
        logger.info("Hello world")
    """
    if module_name:
        # Create child logger with module name
        return logging.getLogger(f"screenseeker.{module_name}")
    else:
        # Return root logger
        return logging.getLogger("screenseeker")


# Convenience functions for quick logging without getting logger instance
def debug(msg: str, **kwargs):
    """Log a debug message."""
    logging.getLogger("screenseeker").debug(msg, **kwargs)


def info(msg: str, **kwargs):
    """Log an info message."""
    logging.getLogger("screenseeker").info(msg, **kwargs)


def warning(msg: str, **kwargs):
    """Log a warning message."""
    logging.getLogger("screenseeker").warning(msg, **kwargs)


def error(msg: str, **kwargs):
    """Log an error message."""
    logging.getLogger("screenseeker").error(msg, **kwargs)


def critical(msg: str, **kwargs):
    """Log a critical message."""
    logging.getLogger("screenseeker").critical(msg, **kwargs)
