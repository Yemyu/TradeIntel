"""Offline format-only recovery, preserving the original live failure."""
import hashlib
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from tradeintel_ai.agent import ModelResponse
from tradeintel_ai.policy_retrieval import draft_answer
from tradeintel_ai.policy_response_format import PolicyFormattingModel


def replay():
    source=ROOT/'tmp/policy-bounded-13d/result.json'
    result=json.loads(source.read_text())
    evidence=json.loads(source.with_name('evidence.json').read_text())
    if result['raw_response']['tool_call_count']!=0: raise ValueError('Unexpected tools')
    class Archived:
        def complete(self,**kwargs): return ModelResponse(text=result['raw_response']['text'])
    output=draft_answer(PolicyFormattingModel(Archived()),evidence)
    report={'label':'offline_format_replay_not_new_live_success','new_api_calls':0,
            'original_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'original_status':result['generation']['status'],
            'finish_reason_available_in_archive':False,'replayed':output}
    target=ROOT/'docs/experiments/phase13d-format-replay.json'
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report


if __name__=='__main__': print(json.dumps(replay(),ensure_ascii=False,indent=2))
