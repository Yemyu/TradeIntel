"""One minimal diagnostic request, no retry, no research data or raw errors."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from tradeintel_ai.local_provider_config import load_config
from tradeintel_ai.research_models import ResearchPlannerModel
from tradeintel_ai.provider_diagnostics import safe_provider_diagnostic


def run(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    state = {'purpose':'connection_diagnostic_not_quality_evaluation','attempts':0,'retries':0}
    def save():
        (output/'diagnostic.json').write_text(json.dumps(state, ensure_ascii=False, indent=2))
    save()
    try:
        config = replace(load_config(), timeout_seconds=30.0)
        if not config.api_key:
            state['status'] = 'key_not_configured'
            return state
        class Probe(ResearchPlannerModel):
            max_output_tokens = 16
        state['attempts'] = 1
        save()
        reply = Probe(config).complete(messages=[{'role':'user','content':'Reply OK.'}], tools=[])
        usage = reply.metadata.get('usage', {}).get('total_tokens')
        state.update(status='response_received', total_tokens=usage if type(usage) is int else None)
    except Exception as exc:
        state.update(status='failed', diagnostic=safe_provider_diagnostic(exc))
    finally:
        save()
    return state


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    print(json.dumps(run(parser.parse_args().output), ensure_ascii=False))
