"""One explicit tiny connectivity/auth diagnostic; not a research retry."""
import argparse
import json
from pathlib import Path
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.tradeintel_ai.local_provider_config import load_config
from src.tradeintel_ai.model_adapter import OpenAICompatibleModel, OpenAICompatibleConfig, _endpoint, safe_error_details


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    args=p.parse_args()
    cfg=load_config()
    endpoint='https://open.bigmodel.cn/api/paas/v4/chat/completions'
    if _endpoint(cfg.base_url)!=endpoint: raise SystemExit('unexpected endpoint')
    class DiagnosticModel(OpenAICompatibleModel):
        def _payload(self, *, messages, tools):
            value=super()._payload(messages=messages, tools=tools)
            value.update(max_tokens=16, thinking={'type':'disabled'})
            return value
    client=DiagnosticModel(OpenAICompatibleConfig(cfg.base_url,'glm-4.7',cfg.api_key,20,0),system_prompt='')
    args.output.mkdir(parents=True,exist_ok=False)
    path=args.output/'diagnostic.json'
    record={'mode':'one_shot_auth_diagnostic','model':'glm-4.7','max_attempts':1,
            'max_tokens':16,'timeout_seconds':20,'status':'started',
            'started_at':datetime.now(timezone.utc).isoformat(),
            'prompt':'Reply OK only.','attempts':1,'automatic_retry':False}
    path.write_text(json.dumps(record,indent=2))
    try:
        response=client.complete(messages=[{'role':'user','content':'Reply OK only.'}],tools=[])
        record.update(status='response_received',usage=response.metadata.get('usage'),
                      finish_reason=response.metadata.get('finish_reason'),
                      expected_ok=response.text.strip()=='OK')
    except Exception as exc:
        record.update(status='diagnostic_failed',error_details=safe_error_details(exc))
    record['completed_at']=datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(record,indent=2))
    print(json.dumps(record))
    return 0 if record['status']=='response_received' else 2


if __name__=='__main__': raise SystemExit(main())
