"""Interactive local workflow. --demo uses an archived response, never an API."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.tradeintel_ai.confirmed_workflow import ConfirmedWorkflow
from src.tradeintel_ai.intent_repair import BoundedModel
from src.tradeintel_ai.model_adapter import OpenAICompatibleConfig


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--demo',action='store_true')
    p.add_argument('--plan',action='store_true',help='Experimental 1–3 task planner; live mode only')
    p.add_argument('--plan-v2',action='store_true',help='Independent revised planner candidate; live mode only')
    p.add_argument('--plan-v3',action='store_true',help='Candidate with an extra coverage-review model call')
    args=p.parse_args()
    if sum((args.plan,args.plan_v2,args.plan_v3)) > 1:
        p.error('choose only one planner version')
    if args.demo and (args.plan or args.plan_v2 or args.plan_v3):
        p.error('--demo is a single-task archived response; do not combine with --plan')
    if args.demo:
        from scripts.review_intent_continuation import review
        path=ROOT/'tmp/intent-continuation/20260908T162309929803Z.json'
        review(path)
        item=next(q for q in json.loads(path.read_text())['questions'] if q['id']=='H04')
        question=item['question']
        class Recorded:
            def complete(self, **kwargs): return item['response']
        model=Recorded()
        print('离线演示：使用已归档的H04解析响应；不调用API，不是新模型生成。')
        print('示例问题：'+question)
    else:
        config=OpenAICompatibleConfig.from_env()
        if config.base_url.rstrip('/') != 'https://open.bigmodel.cn/api/paas/v4':
            raise ValueError('unsupported endpoint')
        model=BoundedModel(config,system_prompt='')
        question=input('请输入本次问题：').strip()
    if args.plan_v3:
        from src.tradeintel_ai.analysis_planner_v3 import AnalysisPlannerV3
        flow=AnalysisPlannerV3(model,model)
        print('实验模式：规划后增加一次覆盖复核；模型仍可能误判，需整体确认。')
    elif args.plan_v2:
        from src.tradeintel_ai.analysis_planner_v2 import AnalysisPlannerV2
        flow=AnalysisPlannerV2(model)
    elif args.plan:
        from src.tradeintel_ai.analysis_planner import AnalysisPlanner
        flow=AnalysisPlanner(model)
    else:
        flow=ConfirmedWorkflow(model)
    preview=flow.propose(question)
    print(preview['response'])
    token=preview.get('confirmation_token')
    if not token: return
    answer=input('\n请核对以上理解；输入“确认”执行只读查询，其他输入取消：').strip()
    if answer != '确认':
        flow.cancel();print('已取消，没有执行查询。');return
    result=flow.confirm(token)
    print('\n'+result['response'])
    print('\n执行状态：'+result['status']+'；用户确认不等同于模型质量验收通过。')


if __name__=='__main__':
    try: main()
    except (EOFError,KeyboardInterrupt): print('\n输入中止；未自动确认或重试。')
    except Exception:
        print('运行失败，请检查本地配置或证据记录；未显示敏感信息，未自动重试。')
        sys.exit(1)
