"""Small append-only journal for one confirmed research execution."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path


class ExecutionJournal:
    """Write one redacted, flush-and-synced JSON event per execution milestone."""

    def __init__(self, path, *, secret=''):
        self.path = Path(path)
        self.secret = secret or ''
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _redact(self, value):
        if isinstance(value, str):
            return value.replace(self.secret, '[REDACTED]') if self.secret else value
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        if isinstance(value, dict):
            return {self._redact(key): self._redact(item) for key, item in value.items()}
        return value

    def append(self, event, *, status=None, detail=None):
        if not isinstance(event, str) or not event.strip():
            raise ValueError('journal event is required')
        record = {'at_utc': datetime.now(timezone.utc).isoformat(), 'event': event}
        if status is not None:
            record['status'] = status
        if detail:
            record['detail'] = detail
        payload = json.dumps(self._redact(record), ensure_ascii=False, sort_keys=True) + '\n'
        with self.path.open('a', encoding='utf-8') as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        return record
