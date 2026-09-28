"""Bounded development request for the primary structured workflow."""
import sys
import json
from pathlib import Path
from dataclasses import replace
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from tradeintel_ai.local_provider_config import load_config
from tradeintel_ai.research_models import JsonResearchModel
from tradeintel_ai.structured_task import compile_task
from tradeintel_ai.business_workflow import run_business_question


if __name__=='__main__':
    output=ROOT/'tmp/primary-interpretation-v1'
    if output.exists():raise SystemExit('已有运行，停止重复调用')
    config=replace(load_config(),model='glm-4.7',temperature=0,timeout_seconds=60)
    class Once(JsonResearchModel):
        max_output_tokens=1200
        calls=0
        def complete(self,**kwargs):
            if self.calls:raise ValueError('one call budget exhausted')
            self.calls+=1
            return super().complete(**kwargs)
    task={'policy_id':'us_301_review2025_tungsten_solar','month':'2026-07',
          'product':'all','task':'source_and_investigation'}
    question,_=compile_task(task)
    result=run_business_question(Once(config),question,output,secret=config.api_key,
        policy_id=task['policy_id'],structured_task=task,interpretation_mode=True)
    print(json.dumps({k:result.get(k) for k in ('status','model_calls','data_version','interpretation_status')},ensure_ascii=False))
