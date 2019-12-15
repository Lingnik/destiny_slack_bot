_logger = None

import logging

try:
    from django.conf import settings

    if settings.DEBUG:
        try:
            import http.client as http_client
        except ImportError:
            # Python 2
            import httplib as http_client
        http_client.HTTPConnection.debuglevel = 1
        logging.basicConfig()
        _logger = logging.getLogger()
        _logger.setLevel(logging.DEBUG)
        requests_log = logging.getLogger("requests.packages.urllib3")
        requests_log.setLevel(logging.DEBUG)
        requests_log.propagate = True
except:
    pass


class Logger:
    def debug(self, msg):
        if _logger:
            _logger.log(msg=msg, level=logging.DEBUG)

    def log(self, msg):
        if _logger:
            _logger.log(msg=msg, level=logging.INFO)

logger = Logger()
