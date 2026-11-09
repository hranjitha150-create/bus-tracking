"""Keep credentials out of configured production log messages and tracebacks."""
import logging
import os
import re
from urllib.parse import unquote, urlsplit


class RedactSecrets(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        if record.exc_info:
            message += '\n' + logging.Formatter().formatException(record.exc_info)
            record.exc_info = None
            record.exc_text = None
        for key in ('DJANGO_SECRET_KEY', 'DATABASE_URL'):
            secret = os.getenv(key, '')
            if secret:
                message = message.replace(secret, '[REDACTED]')
        try:
            password = unquote(urlsplit(os.getenv('DATABASE_URL', '')).password or '')
            if password:
                message = message.replace(password, '[REDACTED]')
        except ValueError:
            pass
        message = re.sub(r'(?i)Bearer\s+[A-Za-z0-9_.~+/-]+', 'Bearer [REDACTED]', message)
        message = re.sub(r'(?i)(postgres(?:ql)?://)[^\s]+', r'\1[REDACTED]', message)
        record.msg, record.args = message, ()
        return True
