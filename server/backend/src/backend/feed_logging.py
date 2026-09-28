"""Keep revocable RSS subscription credentials out of HTTP access logs."""

import logging
import re

_TOKEN_PATH = re.compile(r"(/feeds/vodloft/)[^/?\s]+")


class RedactFeedToken(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and len(record.args) >= 3:
            args = list(record.args)
            args[2] = _TOKEN_PATH.sub(r"\1[redacted]", str(args[2]))
            record.args = tuple(args)
        elif isinstance(record.msg, str):
            record.msg = _TOKEN_PATH.sub(r"\1[redacted]", record.msg)
        return True
