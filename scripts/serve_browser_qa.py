"""Local browser QA only: real workflow, fixed fake model, temporary outputs.

Run PYTHONPATH=src:. .venv/bin/python scripts/serve_browser_qa.py.
Never use the generated answer as model-quality evidence.
"""
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

from src.tradeintel_ai.agent import ModelResponse
from src.tradeintel_ai.model_adapter import OpenAICompatibleConfig
from src.tradeintel_ai.web_app import create_server
from tests.test_natural_v2 import QUESTION, PROPOSAL


def offline_response(self, **kwargs):
    payload = json.loads(kwargs['messages'][-1]['content'])
    if 'observations' in payload:
        answer = {'schema_version': 'research-brief-v2', 'findings': [
            {'observation_id': o['id'], 'explanation': '离线测试模拟文字：仅描述该观察，不认定政策效果。',
             'limitation_ids': [payload['limitations'][0]['id']]}
            for o in payload['observations'][:3]], 'followups': []}
    elif payload.get('question') == QUESTION:
        answer = PROPOSAL
    else:
        answer = {'status': 'clarify', 'request': None, 'evidence': {}, 'missing': ['fixture_question']}
    print('OFFLINE_FIXTURE_RESPONSE', flush=True)
    return ModelResponse(text=json.dumps(answer, ensure_ascii=False), metadata={'finish_reason': 'stop'})


def network_guard(event, args):
    if event == 'socket.connect' and (not isinstance(args[1], tuple) or args[1][0] not in {'127.0.0.1', '::1'}):
        raise RuntimeError('QA external connection forbidden')


if __name__ == '__main__':
    sys.addaudithook(network_guard)
    with tempfile.TemporaryDirectory(prefix='tradeintel-browser-qa-') as folder, \
         patch('src.tradeintel_ai.web_app.load_config', return_value=OpenAICompatibleConfig('https://invalid.test', 'fake', 'offline-qa')), \
         patch('src.tradeintel_ai.model_adapter.OpenAICompatibleModel.complete', offline_response):
        server = create_server(root=Path(__file__).resolve().parents[1], port=8766, output_root=Path(folder))
        print('OFFLINE QA ONLY http://127.0.0.1:8766\nQuestion: ' + QUESTION, flush=True)
        if '--seed-review' in sys.argv:
            # Seed only an unreviewed fixture; browser must save its own decision.
            handler = server.RequestHandlerClass
            preview = handler.coordinator.natural_preview(QUESTION,
                repository=handler.repository, output_root=Path(folder))
            result = handler.coordinator.natural_confirm(preview['confirmation_token'],
                repository=handler.repository, output_root=Path(folder))
            if result.get('status') != 'interpretation_needs_review':
                raise RuntimeError('offline review fixture did not initialize')
            print('REVIEW_URL http://127.0.0.1:8766' + result['review_url'], flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
