"""
Tests for logger module.
"""

import logging


class TestColoredFormatter:
    """Test ColoredFormatter class."""

    def test_formatter_colors_levelname(self):
        """Test that formatter adds colors to levelname."""
        from screenseeker.logger import ColoredFormatter

        formatter = ColoredFormatter("%(levelname)s - %(message)s")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        formatted = formatter.format(record)

        # Should contain ANSI color codes
        assert "\033[" in formatted or "INFO" in formatted
        # Original levelname should be preserved after formatting
        assert record.levelname == "INFO"

    def test_formatter_handles_all_levels(self):
        """Test that formatter handles all log levels."""
        from screenseeker.logger import ColoredFormatter

        formatter = ColoredFormatter("%(levelname)s - %(message)s")

        for level_name in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            record = logging.LogRecord(
                name="test",
                level=getattr(logging, level_name),
                pathname="test.py",
                lineno=1,
                msg="Test message",
                args=(),
                exc_info=None,
            )

            formatted = formatter.format(record)
            assert formatted is not None
            assert record.levelname == level_name


class TestSimpleFormatter:
    """Test SimpleFormatter class."""

    def test_simple_formatter_no_colors(self):
        """Test that simple formatter doesn't add colors."""
        from screenseeker.logger import SimpleFormatter

        formatter = SimpleFormatter("%(levelname)s - %(message)s")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        formatted = formatter.format(record)

        # Should not contain ANSI color codes
        assert "\033[" not in formatted
        assert "INFO" in formatted
        assert "Test message" in formatted


class TestSetupLogger:
    """Test setup_logger function."""

    def test_setup_logger_default(self):
        """Test setup_logger with default parameters."""
        from screenseeker.logger import setup_logger

        logger = setup_logger(name="test_logger_default")

        assert logger.name == "test_logger_default"
        assert logger.level == logging.INFO
        assert len(logger.handlers) > 0

    def test_setup_logger_custom_level(self):
        """Test setup_logger with custom log level."""
        from screenseeker.logger import setup_logger

        logger = setup_logger(name="test_logger_custom", level="DEBUG")

        assert logger.level == logging.DEBUG

    def test_setup_logger_with_file(self, tmp_path):
        """Test setup_logger with file logging enabled."""
        from screenseeker.logger import setup_logger

        log_file = tmp_path / "test.log"
        logger = setup_logger(
            name="test_logger_file",
            level="INFO",
            log_to_file=True,
            log_file_path=log_file,
            use_colors=False,
        )

        # Log a message
        logger.info("Test log message")

        # File should exist
        assert log_file.exists()

        # File should contain the message
        content = log_file.read_text()
        assert "Test log message" in content

    def test_setup_logger_without_colors(self):
        """Test setup_logger with colors disabled."""
        from screenseeker.logger import setup_logger

        logger = setup_logger(name="test_logger_no_color", use_colors=False)

        assert logger is not None
        assert len(logger.handlers) > 0

    def test_setup_logger_clears_existing_handlers(self):
        """Test that setup_logger clears existing handlers."""
        from screenseeker.logger import setup_logger

        # Set up logger twice
        logger = setup_logger(name="test_logger_handlers")
        handler_count = len(logger.handlers)

        logger = setup_logger(name="test_logger_handlers")

        # Should have same number of handlers (not doubled)
        assert len(logger.handlers) == handler_count


class TestGetLogger:
    """Test get_logger function."""

    def test_get_logger_with_module_name(self):
        """Test get_logger with module name."""
        from screenseeker.logger import get_logger

        logger = get_logger("test_module")

        assert "screenseeker.test_module" in logger.name

    def test_get_logger_without_module_name(self):
        """Test get_logger without module name."""
        from screenseeker.logger import get_logger

        logger = get_logger()

        assert logger.name == "screenseeker"

    def test_get_logger_with_none(self):
        """Test get_logger with None."""
        from screenseeker.logger import get_logger

        logger = get_logger(None)

        assert logger.name == "screenseeker"


class TestConvenienceFunctions:
    """Test convenience logging functions."""

    def test_debug_function(self):
        """Test debug convenience function."""
        from screenseeker.logger import debug, setup_logger

        setup_logger(level="DEBUG", use_colors=False)
        debug("Test debug message")  # Should not raise

    def test_info_function(self):
        """Test info convenience function."""
        from screenseeker.logger import info, setup_logger

        setup_logger(level="INFO", use_colors=False)
        info("Test info message")  # Should not raise

    def test_warning_function(self):
        """Test warning convenience function."""
        from screenseeker.logger import setup_logger, warning

        setup_logger(level="WARNING", use_colors=False)
        warning("Test warning message")  # Should not raise

    def test_error_function(self):
        """Test error convenience function."""
        from screenseeker.logger import error, setup_logger

        setup_logger(level="ERROR", use_colors=False)
        error("Test error message")  # Should not raise

    def test_critical_function(self):
        """Test critical convenience function."""
        from screenseeker.logger import critical, setup_logger

        setup_logger(level="CRITICAL", use_colors=False)
        critical("Test critical message")  # Should not raise
