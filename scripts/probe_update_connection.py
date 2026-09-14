"""One local-config JSON probe; no business data, secrets or retries in logs."""
import json
import sys
import time
from pathlib import Path
from dataclasses import replace
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tradeintel_ai.local_provider_config import load_config
from tradeintel_ai.research_models import JsonResearchModel
from tradeintel_ai.provider_diagnostics import safe_provider_diagnostic
from tradeintel_ai.transport_diagnostic import transport_detail


def probe(config, output, opener=urlopen):
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    state = {'status': 'prepared', 'attempts': 0, 'phase': 'setup',
             'business_quality_measured': False, 'total_tokens': None}

    def save():
        (output / 'status.json').write_text(json.dumps(state, indent=2), encoding='utf-8')

    def tracked_open(request, timeout):
        state.update(phase='awaiting_headers', attempts=1)
        save()
        response = opener(request, timeout=timeout)
        state.update(phase='reading_response', http_status=response.status)
        save()
        return response

    class ProbeModel(JsonResearchModel):
        max_output_tokens = 32

    model = ProbeModel(replace(config, timeout_seconds=30, temperature=0), opener=tracked_open)
    state['settings'] = model.effective_request_settings()
    save()
    try:
        response = model.complete(messages=[{'role': 'user', 'content': 'Return JSON only: {"ok":true}'}], tools=[])
        state.update(status='response_received', phase='decoded_response',
                     total_tokens=response.metadata.get('usage', {}).get('total_tokens'),
                     expected_json=json.loads(response.text) == {'ok': True})
    except Exception as exc:
        state.update(status='failed', diagnostic=safe_provider_diagnostic(exc),
                     transport=transport_detail(exc))
    state['elapsed_seconds'] = round(time.monotonic()-started, 3)
    save()
    return state


if __name__ == '__main__':
    print(json.dumps(probe(load_config(), ROOT/'tmp/update-connection-probe-v1'), indent=2))
