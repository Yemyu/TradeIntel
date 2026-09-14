"""Read-only dependency screening of saved research outputs."""
import json
import re
from .exposure_version_store import snapshot_difference, VersionStoreError

RUN_ID = re.compile(r'exposure-\d{8}T\d{6}-[0-9a-f]{8}')


def _read(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 10_000_000:
        raise ValueError('missing or unsafe metadata')
    obj = json.loads(path.read_bytes())
    if not isinstance(obj, dict):
        raise ValueError('invalid metadata')
    return obj


def assess_report(run, store, after):
    result = {'run_id':run.name,'status':'unknown','reason':'缺少可核对的版本或范围记录。'}
    try:
        state = _read(run/'status.json')
        version = state.get('data_version')
        if not isinstance(version, str):
            return {**result,'reason':'旧运行未记录数据版本，不能确定它使用的是哪一版数据。'}
        before = store.load_snapshot(version)
        if state.get('policy_id',before['policy_id']) != before['policy_id']:
            return result
        if before['policy_id'] != after['policy_id']:
            return {**result,'status':'other_policy','reason':'属于其他政策，本次更新不作判断。'}
        delta = snapshot_difference(before, after)
        evidence_path = run/'trade-evidence.json'
        if not evidence_path.exists():
            evidence_path = run/'evidence.json'
        evidence = _read(evidence_path)
        data = evidence.get('data', {})
        if (not isinstance(data,dict) or evidence.get('data_version') != version
                or data.get('policy_id') != before['policy_id']):
            return result
        months = data.get('requested_months')
        series = data.get('series')
        if (not isinstance(months,list) or not months or not all(isinstance(m,str) for m in months)
                or len(set(months)) != len(months) or data.get('coverage_complete') is not True
                or not isinstance(series,list)
                or not all(isinstance(row,dict) for row in series)
                or [row.get('month') for row in series] != months
                or any(m not in before['months'] for m in months)):
            return result
        changed = sorted(set(months)&set(delta['revised_months']+delta['removed_months']))
        if changed or delta['policy_changed']:
            reasons=[]
            if changed: reasons.append('所用月份资料已修订或移除：'+'、'.join(changed))
            if delta['policy_changed']: reasons.append('同政策文件已变化，政策解释需重核')
            return {**result,'status':'needs_review','reason':'；'.join(reasons)+'。'}
        return {**result,'status':'unchanged_scope',
                'reason':'所用固定月份及政策文件未变化；新增月份不使这份历史范围报告自动失效。'}
    except (ValueError, OSError, VersionStoreError, KeyError, TypeError):
        return result


def scan_reports(output_root, store, after):
    results=[]
    if not output_root.is_dir():
        return results
    for run in sorted(output_root.iterdir()):
        if not RUN_ID.fullmatch(run.name) or run.is_symlink() or not run.is_dir():
            continue
        artifact=next((name for name in ('report.zh-CN.md','source-packet.zh-CN.md')
                       if (run/name).is_file() and not (run/name).is_symlink()),None)
        if not artifact:
            continue
        item=assess_report(run,store,after)
        item['url']=(f'/api/report/{run.name}' if artifact=='report.zh-CN.md'
                     else f'/api/research-artifact/{run.name}/{artifact}')
        results.append(item)
    return results


def render_report_impacts(items):
    labels={'needs_review':'需要重新核查','unknown':'暂时无法判断',
            'other_policy':'其他政策','unchanged_scope':'固定范围未受影响'}
    lines=['', '## 具体报告的更新影响', '',
           '检查范围：网站运行目录中已有报告或来源资料包。以下依据版本与月份元数据筛查，未逐句审查AI文字；“最新”等动态表述仍需人工核查。']
    if not items:
        lines += ['当前目录没有可列出的报告。']
    for item in items:
        lines += ['',f"- [{item['run_id']}]({item['url']})：{labels[item['status']]}。{item['reason']}"]
    return '\n'.join(lines)+'\n'
