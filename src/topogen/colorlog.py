"""
colorful log message formatter
based on
https://stackoverflow.com/questions/384076/how-can-i-color-python-logging-output

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
