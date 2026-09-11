"""Execute one explicit local request; no API key and no model calls."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.tradeintel_ai.structured_workflow import execute_request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('request', type=Path, help='Structured request JSON, not natural language')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    request = json.loads(args.request.read_text(encoding='utf-8'))
    # Reserve output first: never overwrite an existing run.
    with args.output.open('x', encoding='utf-8') as handle:
        result = execute_request(request)
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    print(json.dumps({'status': result['status'], 'model_calls': result['model_calls'],
                      'intent_verified': False, 'output': str(args.output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
