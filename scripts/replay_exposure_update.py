"""Replay a data-window extension from verified local artifacts; no network."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tradeintel_ai.policy_exposure_tools import get_policy_exposure_series, POLICY_EXPOSURE_ID
from tradeintel_ai.repository import EvidenceRepository, DataPaths


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


def snapshot(root, end, policy_id=POLICY_EXPOSURE_ID):
    from tradeintel_ai.policy_cases import resolve_case
    case = resolve_case(policy_id)
    result = get_policy_exposure_series(start=case.start, end=end, policy_id=policy_id,
        repository=EvidenceRepository(DataPaths(root)))
    if not result['data']['coverage_complete']:
        raise ValueError('incomplete window')
    sources = result['evidence']['sources']
    monthly = {}
    for row in result['data']['series']:
        month = row['month']
        path = f'{case.monthly}/{policy_id}_{month.replace("-", "_")}.csv'
        file_ref = next(s for s in sources if s.get('path') == path)
        archive = next(s for s in sources if s.get('month') == month and s.get('kind') == 'official_census_archive')
        monthly[month] = {'output_sha256': file_ref['sha256'], 'archive_sha256': archive['sha256'],
                          'source_url': archive['url'], 'metrics': row}
    policy_files = [case.event, case.products, case.corpus]
    correction = str(Path(case.manifest).parent / 'policy_metadata_corrections.json')
    if (root / correction).exists():
        policy_files.append(correction)
    if policy_id == 'us_301_solar2024':
        policy_files.append(str(Path(case.corpus).parent / 'source.json'))
    body = {'policy_id': policy_id, 'start': case.start, 'end': end,
            'mode': 'current_vintage_window_replay', 'months': monthly,
            'policy_files': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in policy_files}}
    return {**body, 'version': digest(body)}


def compare(before, after):
    for state in (before, after):
        if state['version'] != digest({k: v for k, v in state.items() if k != 'version'}):
            raise ValueError('snapshot content differs from version')
    if before['policy_id'] != after['policy_id'] or before['start'] != after['start']:
        raise ValueError('different policy or start; not an incremental update')
    old, new = before['months'], after['months']
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    revised = sorted(k for k in set(old) & set(new) if old[k] != new[k])
    policy_changed = before['policy_files'] != after['policy_files']
    return {'status': 'changed' if added or removed or revised or policy_changed else 'unchanged',
            'before_version': before['version'], 'after_version': after['version'],
            'added_months': added, 'removed_months': removed, 'revised_months': revised,
            'policy_changed': policy_changed, 'requires_review': bool(removed or revised or policy_changed)}


def reviewed_comparison(root, before, after):
    review_path = root / 'data/processed/policy_exposure/code_transition_review.json'
    review = json.loads(review_path.read_text())
    if (review['status'] != 'reviewed_specific_transition'
            or review['reference_month'] != '2026-06' or review['current_month'] != '2026-07'):
        raise ValueError('transition review does not cover requested months')
    for source in review['sources']:
        if hashlib.sha256((root / source['path']).read_bytes()).hexdigest() != source['sha256']:
            raise ValueError('transition review source changed')
    def amount(state, month):
        return next(p['all_origins_value_usd'] for p in state['months'][month]['metrics']['product_breakdown']
                    if p['hts8'] == '38180000')
    old, new = amount(before, '2026-06'), amount(after, '2026-07')
    if (old != review['comparison']['reference_value_usd'] or new != review['comparison']['current_value_usd']):
        raise ValueError('review and query amounts disagree')
    return {'hts8': '38180000', 'reference_usd': old, 'current_usd': new,
            'change_usd': new - old, 'change_percent': round((new / old - 1) * 100, 4) if old else None,
            'review_sha256': hashlib.sha256(review_path.read_bytes()).hexdigest(),
            'source_url': review['source_url']}


def run(output, root=ROOT):
    before, after = snapshot(root, '2026-06'), snapshot(root, '2026-07')
    delta = compare(before, after)
    if delta['added_months'] != ['2026-07'] or delta['requires_review'] or delta['removed_months']:
        raise ValueError('unexpected update structure')
    reviewed = reviewed_comparison(root, before, after)
    july = after['months']['2026-07']
    row = july['metrics']
    report = '\n'.join([
        '# 贸易资源更新简报：新增2026年7月', '',
        '当前数据版本的窗口扩展回放：18个月 → 19个月。不是新的联网下载，也不是历史实时回测。', '',
        '新增月份：2026-07；原18个月没有修订；本地政策登记未变化（未联网检查政策更新）。', '',
        f"五税号范围：全来源消费进口额 {row['all_origins_value_usd']:,} 美元；中国原产 {row['china_value_usd']:,} 美元；中国份额 {row['target_share_percent']:.2f}%。", '',
        '## 已核实可比的商品变化', '',
        f"38180000：六月 {reviewed['reference_usd']:,} 美元 → 七月 {reviewed['current_usd']:,} 美元，变化 {reviewed['change_usd']:,} 美元（{reviewed['change_percent']:.2f}%）。", '',
        '完整HTS8内汇总所有后继编码，避免将拆码当作新贸易。变化仅描述名义进口金额，不能解释为数量、利润或政策效果。其他范围尚不据此自动报告环比。', '',
        '## 对分析人员的用途', '',
        '上次简报可以补入七月规模，并优先调查38180000金额变化与来源构成。供需和价格解释仍需额外证据。', '',
        f"[七月 Census 原始来源]({july['source_url']})；[编码转移证据]({reviewed['source_url']})。", '',
        f"旧版本：`{before['version']}`；新版本：`{after['version']}`。", '',
        'AI调用次数：0。本文由差异工具生成；后续AI可读取同一差异结果选择调查方向。', ''])
    output.mkdir(parents=True, exist_ok=False)
    for name, value in [('before.json', before), ('after.json', after), ('difference.json', {**delta, 'reviewed_comparison': reviewed})]:
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    (output / 'report.zh-CN.md').write_text(report)
    return delta


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    print(json.dumps(run(parser.parse_args().output), ensure_ascii=False, indent=2))
