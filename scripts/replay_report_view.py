"""Apply presentation-only changes to archived v2.1 results without any API calls."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.tradeintel_ai.report_view import build_view,canonical


def replay(path):
    path=Path(path)
    raw=path.read_bytes()
    run=json.loads(raw)
    for relative,expected in run['manifest']['files'].items():
        local=(ROOT/relative).resolve()
        if not local.is_relative_to(ROOT) or hashlib.sha256(local.read_bytes()).hexdigest()!=expected:
            raise ValueError('归档执行版本与当前文件不一致')
    items=[]
    for item in run['questions']:
        original=item['result']
        view=build_view(original)
        preserved=None
        if view['status']=='needs_review':
            preserved=canonical(view['audit_ledger'])==canonical({'facts':original['facts'],'sources':original['sources']})
            if not preserved:raise ValueError('展示层改动了原始事实账本')
        items.append({'id':item['id'],'repeat':item.get('repeat',1),'ledger_preserved':preserved,'view':view})
    return {'mode':'offline_presentation_comparison','api_requests':0,
            'source_run_sha256':hashlib.sha256(raw).hexdigest(),
            'view_code_sha256':hashlib.sha256((ROOT/'src/tradeintel_ai/report_view.py').read_bytes()).hexdigest(),
            'recorded_items':len(items),'rendered':sum(i['ledger_preserved'] is True for i in items),
            'model_adopted':False,'semantic_accuracy':None,'items':items}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    result=replay(args.run)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as handle:
        json.dump(result,handle,ensure_ascii=False,indent=2)
        handle.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k!='items'},ensure_ascii=False))


if __name__=='__main__':main()
