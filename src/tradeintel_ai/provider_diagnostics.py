"""Allow-listed transport diagnostics: never serialize provider text or URLs."""
from urllib.error import HTTPError, URLError
from http.client import HTTPException, RemoteDisconnected
from json import JSONDecodeError


def safe_provider_diagnostic(error):
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, HTTPError):
            status = current.code
            category = {401: 'authentication_rejected', 403: 'access_denied',
                        429: 'rate_or_quota_limit', 400: 'request_rejected',
                        404: 'endpoint_or_model_not_found'}.get(status, 'http_error')
            if type(status) is int and 500 <= status <= 599:
                category = 'provider_server_error'
            return {'category': category, 'http_status': status if type(status) is int else None}
        if isinstance(current, TimeoutError):
            return {'category': 'timeout'}
        if isinstance(current, RemoteDisconnected):
            return {'category': 'remote_disconnected'}
        if isinstance(current, ConnectionError):
            return {'category': 'connection_error'}
        if isinstance(current, HTTPException):
            return {'category': 'http_protocol_error'}
        if isinstance(current, (JSONDecodeError, UnicodeDecodeError)):
            return {'category': 'response_decode_error'}
        if isinstance(current, URLError):
            return {'category': 'timeout' if isinstance(current.reason, TimeoutError) else 'network_error'}
        current = current.__cause__ or current.__context__
    return {'category': 'unclassified_error'}
