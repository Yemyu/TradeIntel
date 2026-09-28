"""One bounded revision after the stopped development B; no provider access."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from scripts.freeze_g2_research import estimate_tokens

LIMIT = "China share cannot identify other origins' distribution, diversification, domestic supply or substitutability."
ENCODING = '$ref: references; $columns/$rows: tables; $groups: join rows in order. Lossless aliases, not evidence IDs.'


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(parent, output):
    parent=Path(parent).resolve(); output=Path(output).resolve()
    if output.exists(): raise ValueError('revision output already exists')
    old=json.loads((parent/'manifest.json').read_text())
    state_path=parent/'execution-ledger/state.json'
    state=json.loads(state_path.read_text())
    if old.get('revision') or len(state['attempts'])!=1 or state['attempts'][0].get('review',{}).get('decision')!='stop':
        raise ValueError('only one revision of the stopped first development call is allowed')
    if state['manifest_sha256']!=sha(parent/'manifest.json'):
        raise ValueError('parent ledger not bound')
    if old['schedule'][0]['id']!='development' or old['schedule'][0]['arm']!='B':
        raise ValueError('unexpected development schedule')
    for relative,expected in old['files_sha256'].items():
        path=(parent/relative).resolve()
        if not path.is_relative_to(parent) or sha(path)!=expected: raise ValueError('parent evidence changed')
    output.mkdir(parents=True)
    for relative in old['files_sha256']:
        target=output/relative; target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(parent/relative,target)
    # Only transport instructions are shortened; every evidence value remains.
    for name in ('development','primary_all','primary_single','solar_all','solar_single'):
        for arm in ('B','C'):
            path=output/name/f'{arm}.messages.json'
            messages=json.loads(path.read_text())
            information=json.loads(messages[1]['content'])
            information['metric_limits']=LIMIT
            information['instruction']=ENCODING
            messages[1]['content']=json.dumps(information,ensure_ascii=False,separators=(',',':'))
            path.write_text(json.dumps(messages,ensure_ascii=False,indent=2)+'\n')
    schedule=deepcopy(old['schedule'][1:])
    for item in schedule:
        relative=f"{item['id']}.messages.json" if item['arm']=='planning' else f"{item['id']}/{item['arm']}.messages.json"
        item['estimated_input_tokens']=estimate_tokens(json.loads((output/relative).read_text()))
    excessive=[s for s in schedule if s['estimated_input_tokens']>8000]
    revision={'number':1,'parent_preparation':str(parent), 'parent_manifest_sha256':sha(parent/'manifest.json'),
              'parent_state_sha256':sha(state_path),'inherited_attempts':1,
              'reason':'China import share does not identify diversification; shared metric boundary for B/C',
              'development_comparison':'old B versus revised C is not a controlled comparison'}
    new={**old,'revision':revision,'schedule':schedule,'over_budget':excessive,
         'status':'blocked_input_budget' if excessive else 'revision_prepared_no_calls',
         'live_execution_allowed':False,
         'files_sha256':{r:sha(output/r) for r in old['files_sha256']},
         'code_sha256':{str(p.relative_to(ROOT)):sha(p) for p in [
             ROOT/'scripts/freeze_g2_research.py', ROOT/'scripts/run_g2_research.py',Path(__file__),
             *sorted((ROOT/'src/tradeintel_ai').glob('*.py'))]}}
    (output/'manifest.json').write_text(json.dumps(new,ensure_ascii=False,indent=2)+'\n')
    return new


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=prepare(args.parent,args.output)
    print(json.dumps({k:result[k] for k in ('status','over_budget','live_execution_allowed')},ensure_ascii=False))
    raise SystemExit(2 if result['over_budget'] else 0)
