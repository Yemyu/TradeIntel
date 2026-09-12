"""Bounded exception metadata: never persist error messages or request data."""
import socket
import ssl
from urllib.error import HTTPError, URLError


def transport_detail(exc):
    labels = ((HTTPError, 'http'), (URLError, 'url'),
              (ssl.SSLCertVerificationError, 'certificate'),
              (ssl.SSLEOFError, 'tls_eof'), (ssl.SSLError, 'tls'),
              (socket.gaierror, 'dns'), (TimeoutError, 'timeout'),
              (ConnectionResetError, 'connection_reset'),
              (ConnectionRefusedError, 'connection_refused'), (OSError, 'os'))
    chain, seen = [], set()
    current = exc
    while isinstance(current, BaseException) and id(current) not in seen and len(chain) < 6:
        seen.add(id(current))
        label = next((name for cls, name in labels if isinstance(current, cls)), 'wrapper')
        row = {'type': label}
        if isinstance(current, HTTPError) and type(current.code) is int:
            row['http_status'] = current.code
        if isinstance(current, OSError) and type(current.errno) is int:
            row['errno'] = current.errno
        chain.append(row)
        reason = current.reason if isinstance(current, URLError) else None
        current = reason if isinstance(reason, BaseException) else current.__cause__
    return {'exception_chain': chain, 'messages_recorded': False,
            'request_headers_recorded': False, 'failure_phase': 'not_instrumented'}
