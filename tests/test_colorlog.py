from __future__ import annotations

import logging

from topogen.colorlog import CustomFormatter


def test_custom_formatter_colors_warning():
    formatter = CustomFormatter()
    record = logging.LogRecord(
        name="x",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    out = formatter.format(record)
    assert "hello" in out
    assert "\x1b[33;20m" in out


def test_custom_formatter_handles_unknown_level():
    formatter = CustomFormatter()
    record = logging.LogRecord(
        name="x",
        level=5,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    assert formatter.format(record)
