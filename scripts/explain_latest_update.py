"""Preview an update input, or explicitly request one model explanation."""
import argparse
import json
from pathlib import Path
from dataclasses import replace
import sys
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from tradeintel_ai.exposure_version_store import ExposureVersionStore
from tradeintel_ai.update_explanation import context, run


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--output',type=Path,default=ROOT/'tmp/update-explanation-v1-first')
    args=parser.parse_args()
    store=ExposureVersionStore(ROOT);status=store.status()
    active=status.get('active') or {};version=status.get('active_version')
    if not version or not active.get('before_version'):raise ValueError('没有可比较的版本对')
    store.release_root(version)
    before=store.load_snapshot(active['before_version']);after=store.load_snapshot(version)
    if not args.execute:
        print(json.dumps(context(before,after),ensure_ascii=False,indent=2));return
    if args.output.exists():raise ValueError('输出目录已存在，不重复调用')
    from tradeintel_ai.local_provider_config import load_config
    from tradeintel_ai.research_models import JsonResearchModel
    config=replace(load_config(),timeout_seconds=60.0,temperature=0.0)
    class UpdateModel(JsonResearchModel):
        max_output_tokens=1200
    def tracked_open(request, timeout):
        # Fixed labels only: never serialize request headers or exception text.
        path=args.output/'transport-stage.json'
        path.write_text(json.dumps({'phase':'awaiting_headers'}))
        response=urlopen(request,timeout=timeout)
        path.write_text(json.dumps({'phase':'reading_response','http_status':response.status}))
        return response
    result=run(before,after,args.output,UpdateModel(config,opener=tracked_open),secret=config.api_key)
    print(json.dumps(result,ensure_ascii=False))
    if result['status']=='failed':raise SystemExit(1)


if __name__=='__main__':main()
