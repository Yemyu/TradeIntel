"""Local policy evidence CLI. Optional generation is explicit and single-call."""
import argparse
import hashlib
import json
import sys
import getpass
import os
from uuid import uuid4
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tradeintel_ai.policy_retrieval import PolicyRetriever, build_corpus, draft_answer
from tradeintel_ai.policy_workflow import BoundedPolicyModel,load_frozen_corpus,run_generation
from tradeintel_ai.model_adapter import OpenAICompatibleConfig
from tradeintel_ai.agent import ModelResponse

DEFAULT_QUESTION='第一批关税何时生效，额外税率是多少？'
ARCHIVE_SHA='46b783b9e9f821f3fea79cd2ab557389acfa1590d376355a0af426b202e012f2'


def evaluate(retriever):
    cases = json.loads((ROOT/'evals/policy_retrieval_development.json').read_text())['cases']
    results = {}
    for method in ('overlap', 'bm25'):
        rows = []
        for case in cases:
            found = retriever.search(case['question'], as_of=case['as_of'], method=method)
            pages = [h['page_id'] for h in found['hits']]
            rank = next((i for i, p in enumerate(pages, 1) if p in case['gold_pages']), None)
            rows.append({'id': case['id'], 'retrieved_pages': pages,
                         'first_relevant_rank': rank, 'hit_at_3': rank is not None})
        hits = sum(r['hit_at_3'] for r in rows)
        results[method] = {'cases': rows, 'hit_count': hits,
                          'page_hit_rate_at_3': hits/len(rows),
                          'mrr_at_3': sum(1/r['first_relevant_rank'] if r['first_relevant_rank'] else 0 for r in rows)/len(rows),
                          'development_gate_passed': hits >= 5}
    fingerprints = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (
        ROOT/'src/tradeintel_ai/policy_retrieval.py', ROOT/'evals/policy_retrieval_development.json')}
    return {'label': 'development_only_page_retrieval_not_answer_accuracy', 'results': results,
            'fingerprints': fingerprints,
            'corpus_sha256': hashlib.sha256(json.dumps(retriever.corpus, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
            'extractor': retriever.corpus['extractor'],
            'coverage': retriever.corpus['coverage'], 'chunk_count': len(retriever.chunks)}


def markdown_report(result, generation=None, audit=None):
    lines = ['# TradeShock 官方政策证据预览', '', f"问题：{result['question']}", '',
             '这是本地原文检索，不是已通过验收的模型回答。', '',
             f"状态：{result['status']}", '']
    if result.get('reason'):
        lines += [result['reason'], '']
    if audit:
        labels={'live':'本次真实请求','archived_replay':'旧响应离线重放（不是新的模型成功）','fixture':'模拟测试'}
        lines += ['运行来源：'+labels[audit['source_kind']], '',
                  f"本次API请求数：{audit['new_api_calls']}；语义验收：未通过独立验收。", '']
    if generation:
        lines += ['## 模型草稿（语义尚未验收）', '', f"状态：{generation['status']}", '']
        for claim in generation['claims']:
            sources={h['id']:h for h in result['hits']}
            links=[f"[{ref}]({sources[ref]['citation_url']})" for ref in claim['citations']]
            lines += [claim['text'], '', '引用：' + ', '.join(links), '']
    for h in result['hits']:
        lines += [f"## {h['id']}", '', f"[{h['title']}，PDF第{h['page']}页]({h['citation_url']})", '',
                  f"出版日期：{h['published']}；SHA-256：`{h['sha256']}`", '',
                  '> ' + h['text'].replace('\n', '\n> '), '']
    lines += ['## 边界', ''] + ['- ' + s for s in result['limitations']]
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--question', default=DEFAULT_QUESTION)
    parser.add_argument('--as-of', default='2018-07-06', help='publication cutoff, not legal validity')
    modes=parser.add_mutually_exclusive_group()
    modes.add_argument('--evaluate', action='store_true')
    modes.add_argument('--generate', action='store_true', help='one bounded GLM-4.7 call')
    modes.add_argument('--replay-last',action='store_true',help='offline replay of the frozen real response')
    parser.add_argument('--output-dir', type=Path, default=ROOT/'tmp/policy-retrieval')
    args = parser.parse_args()
    if args.replay_last and (args.question!=DEFAULT_QUESTION or args.as_of!='2018-07-06'):
        parser.error('离线重放必须保持原问题和日期，不能将旧回答冒充新问题回答')
    retriever = PolicyRetriever(load_frozen_corpus(ROOT))
    if args.generate or args.replay_last:
        evidence=retriever.search(args.question,as_of=args.as_of)
        model=None
        key=''
        source_kind='live' if args.generate else 'archived_replay'
        if args.replay_last:
            path=ROOT/'tmp/policy-bounded-13d/result.json'
            if hashlib.sha256(path.read_bytes()).hexdigest()!=ARCHIVE_SHA:
                raise ValueError('旧模型响应指纹改变，停止重放')
            archive=json.loads(path.read_text())
            if archive['raw_response']['tool_call_count']!=0: raise ValueError('旧响应含工具调用')
            class Archived:
                def complete(self,**kwargs): return ModelResponse(text=archive['raw_response']['text'])
            model=Archived()
        elif evidence['hits']:
            key=os.environ.get('TRADEINTEL_MODEL_API_KEY','').strip()
            if not key:
                if not sys.stdin.isatty(): raise ValueError('请在交互终端隐藏输入密钥，或配置项目环境变量')
                key=getpass.getpass('GLM密钥（隐藏输入、不保存）：').strip()
            if not key: raise ValueError('密钥为空，没有调用')
            model=BoundedPolicyModel(OpenAICompatibleConfig('https://open.bigmodel.cn/api/paas/v4','glm-4.7',key,60,0))
        output=args.output_dir/('run-'+uuid4().hex)
        print('开始处理；最多一次模型请求，无自动重试。',flush=True)
        result=run_generation(model,evidence,output,source_kind=source_kind,secret=key)
        report=markdown_report(evidence,result['generation'],result['audit'])
        if args.replay_last:
            report+='\n## 已有审查备注（不是模型原回答）\n\n日期及额外税率有原文支持；“上午12:01”表述有歧义，应明确为“凌晨00:01（美国东部夏令时）”。上面的模型原文未作修改。此运行仅重放旧响应，不是新的独立验收。\n'
        if key: report=report.replace(key,'[REDACTED]')
        (output/'report.zh-CN.md').write_text(report)
        print(result['generation']['status'])
        print(output/'report.zh-CN.md')
        return
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir/'corpus.json').write_text(json.dumps(retriever.corpus, ensure_ascii=False, indent=2)+'\n')
    if args.evaluate:
        result = evaluate(retriever)
        (args.output_dir/'development_results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    result = retriever.search(args.question, as_of=args.as_of)
    generation = None
    payload = {'retrieval': result, 'generation': generation}
    (args.output_dir/'evidence.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2)+'\n')
    (args.output_dir/'evidence.zh-CN.md').write_text(markdown_report(result, generation))
    print(f"{result['status']}：{len(result['hits'])}个原文片段；模型调用：{bool(generation)}")
    print(args.output_dir/'evidence.zh-CN.md')


if __name__ == '__main__':
    try:
        main()
    except (ValueError,FileNotFoundError) as exc:
        print(str(exc),file=sys.stderr)
        raise SystemExit(2)
