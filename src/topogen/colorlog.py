"""
File Chain (see DEVELOPER.md):
Doc Version: v1.0.1
Date Modified: 2026-02-16

- Called by: main.py
- Purpose: ANSI color-coded log formatter for console output

TopoGen Color Log Formatter - ANSI Color-Coded Log Message Formatting

PURPOSE:
    Provides color-coded log output for better readability in terminal.
    Uses ANSI escape codes to colorize log messages based on severity level.

WHO READS ME:
    - main.py: Uses CustomFormatter for console log handler

WHO I READ:
    - None (leaf module, no internal dependencies)

DEPENDENCIES:
    - logging: Standard library logging.Formatter

KEY EXPORTS:
    - CustomFormatter: logging.Formatter subclass with color support

COLOR SCHEME:
    - DEBUG: Grey
    - INFO: Cyan
    - WARNING: Yellow
    - ERROR: Red
    - CRITICAL: Bold Red

LOG FORMAT:
    %(asctime)s - %(message)s - (%(filename)s:%(lineno)d)
    Example: "2026-02-02 13:04:26,789 - Configuration loaded - (config.py:32)"

ATTRIBUTION:
    Based on: https://stackoverflow.com/questions/384076/how-can-i-color-python-logging-output
"""

import logging


class CustomFormatter(logging.Formatter):
    """return a formatter that prints log messages with color"""

    grey = "\x1b[38;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    cyan = "\x1b[36;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    template = (
        # "%(asctime)s - %(levelname)s - %(name)s - %(message)s (%(filename)s:%(lineno)d)"
        "%(asctime)s - %(message)s - (%(filename)s:%(lineno)d)"
    )

    FORMATS = {
        logging.DEBUG: grey + template + reset,
        logging.INFO: cyan + template + reset,
        logging.WARNING: yellow + template + reset,
        logging.ERROR: red + template + reset,
        logging.CRITICAL: bold_red + template + reset,
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)
