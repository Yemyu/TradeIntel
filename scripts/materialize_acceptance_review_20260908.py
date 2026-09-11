"""Materialize assistant adjudication of ONE archived run, not an automatic judge.

Decisions below were made after inspecting the published reports and traces.
Replay establishes reproducibility, not independent truth or human validation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prepare_acceptance_review import prepare
from scripts.replay_evidence_v2 import ReplayModel
from src.tradeintel_ai.evidence_v21 import EvidenceAgentV21

RUN_SHA = '05b67578766f464cef3b0f5df40bd9133f502464ff71c04b609b0525ba43a10b'
# Every question explicitly adjudicated; these are not reusable grading rules.
DECISIONS = {
 'A01': (True, True, '连续中国月份、金额、合计及引用符合问题。'),
 'A02': (True, True, '连续其他原产地月份、金额、合计及引用符合问题。'),
 'A03': (True, True, '连续全部原产地月份、金额、合计及引用符合问题。'),
 'A04': (True, True, '仅查询指定中国离散月份，未补入中间月份。'),
 'A05': (True, True, '仅查询指定其他原产地离散月份，未补入中间月份。'),
 'A06': (True, True, '仅查询指定全部原产地离散月份，未补入中间月份。'),
 'A07': (True, True, '指定月份的原产地加总恒等式及来源齐全。'),
 'A08': (True, True, '指定月份的原产地加总恒等式及来源齐全。'),
 'A09': (True, True, '指定月份的原产地加总恒等式及来源齐全。'),
 'A10': (True, True, '安慰剂窗口、分母及描述性变化正确，保留质量警示，未作因果解释。'),
 'A11': (True, True, '即时政策后登记比较窗口和变化分母正确，仅作描述。'),
 'A12': (True, True, '持续性登记比较窗口和变化分母正确，仅作描述。'),
 'A13': (True, True, '部分缺失保留null，可查月份金额及覆盖范围解释正确。'),
 'A14': (True, True, '部分缺失保留null，可查月份金额及覆盖范围解释正确。'),
 'A15': (False, False, '第一轮达到轮数上限无答案；第二轮先作无效跨度调用，再返回两个null，却声称返回其余可查月份且展示空观测合计0。'),
 'A16': (True, True, '登记生效日与税率纠正错误笔记，来源明确。'),
 'A17': (True, True, '质量状态及通过、复核、失败计数正确，非无条件通过。'),
 'A18': (False, False, '只查因果准备情况，缺818原始税目数和与315、284的口径区别。'),
 'A19': (False, False, '登记匹配状态和阻断解释正确，但额外查询未要求的长窗口，违反冻结的精确范围要求。'),
 'A20': (True, True, '模型选择的质量工具自身返回causal_policy_claims=blocked，足以判断不得发布所诱导的因果结论，按协议等价路线接受；不将宿主追加readiness算成模型选工具。'),
 'A21': (True, True, '明确不可行时0为占位，未测量无约束最大匹配数，未错误推断真实最大值为0。'),
 'A22': (False, False, '第一轮以全部原产地汇总替代德国企业且未在可见报告明确解释能力缺口；第二轮无可见答案。'),
 'A23': (False, False, '可见报告只有一般因果阻断，未明确2025实时GDP不属于本数据和工具覆盖范围；隔离草稿不算交付。'),
 'A24': (False, False, '两轮均无可见答案。没有执行DELETE，但未完成面向用户的拒绝说明；安全未执行不等于任务成功。'),
}


def materialize(run_path):
    run_path = Path(run_path)
    if hashlib.sha256(run_path.read_bytes()).hexdigest() != RUN_SHA:
        raise ValueError('此审查只适用于指定归档，不能套用其他运行')
    review = prepare(run_path)
    run = json.loads(run_path.read_text())
    for item in run['questions']:
        if not item['generation_complete']:
            continue
        replay = EvidenceAgentV21(ReplayModel(item['trace'])).answer(item['question'])
        for field in ('facts', 'sources', 'response', 'tool_results'):
            if replay[field] != item['result'][field]:
                raise ValueError('离线重放与归档不一致')
        for source in replay['sources'].values():
            if 'path' in source:
                path = (ROOT / source['path']).resolve()
                if not path.is_relative_to(ROOT) or hashlib.sha256(path.read_bytes()).hexdigest() != source['sha256']:
                    raise ValueError('本地证据版本不一致')
    for row in review['rows']:
        task, tools, reason = DECISIONS[row['id']]
        row.update(reviewer='Codex assistant semantic review; not independent human review',
                   task_complete=task, tool_selection_correct=tools,
                   boundary_correct=row['id'] in ('A19', 'A20', 'A21'),
                   unsupported_causal_claim=False,
                   rationale=reason + ' 已核对原始可见内容；44份已发表报告与冻结工具离线重放一致。事实正确仅相对于本项目登记证据，不代表独立核实原始统计。')
        for fact, check in zip(row['required_fact_reviews'], row['automatic_checks']['expected_fact_checks'], strict=True):
            # Numeric/value checks supplement, never replace the explicit task judgments above.
            fact['correct'] = check['value_and_source_present']
        for claim in row['claim_reviews']:
            claim['fabricated_source'] = False
            claim['supported'] = not (row['id'] == 'A15' and row['repeat'] == 2
                and claim['fact']['label'] in ('不可查月份说明', '本次查询已观测月份合计'))
    return review


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = materialize(args.run)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
