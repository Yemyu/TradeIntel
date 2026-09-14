"""Describe registered data revisions without inferring policy effects."""
from .exposure_version_store import ExposureVersionStore, VersionStoreError, snapshot_difference


def _amount(entry, field):
    value = entry.get('metrics', {}).get(field)
    if type(value) is not int or value < 0:
        return None
    return value


def _money(value):
    return '未知' if value is None else f'{value:,}'


def render_update_brief(before, after):
    delta = snapshot_difference(before, after)
    lines = ['# 贸易数据更新简报', '', f"政策登记：{after['policy_id']}",
             f"旧版本：`{before['version']}`", f"新版本：`{after['version']}`", '',
             '本简报比较本地登记资料；政策文件未变化不代表线上没有新政策。']
    if any(s.get('mode') == 'current_vintage_window_replay' for s in (before, after)):
        lines += ['本次包含当前数据版本的窗口回放，不是新下载或历史实时回测。']
    lines += ['', '## 本次更新', '',
              '新增月份：'+('、'.join(delta['added_months']) or '无'),
              '已有月份资料修订：'+('、'.join(delta['revised_months']) or '无'),
              '移除月份：'+('、'.join(delta['removed_months']) or '无'),
              '本地政策文件：'+('有变化，需核对原文内容' if delta['policy_changed'] else '指纹未变化')]
    if delta['status'] == 'unchanged':
        lines += ['', '两个版本没有内容差异，本次没有新增研究结论。']
    for month in delta['added_months'] + delta['revised_months']:
        new = after['months'][month]
        old = before['months'].get(month)
        world = _amount(new, 'all_origins_value_usd')
        china = _amount(new, 'china_value_usd')
        if world is not None and china is not None and china > world:
            raise VersionStoreError('中国金额大于全部来源金额')
        share = f'{china/world*100:.2f}%' if world and china is not None else '未知（缺数据或分母为零）'
        lines += ['', f'## {month}', '',
                  f'美国全部来源消费进口额：{_money(world)} 美元；中国原产：{_money(china)} 美元；中国份额：{share}。']
        if old:
            previous = _amount(old, 'all_origins_value_usd')
            change = world-previous if world is not None and previous is not None else None
            lines += [f'同一月份旧版全部来源金额：{_money(previous)} 美元；版本修订差额：{_money(change)} 美元。',
                      '该差额是同月不同数据版本的差异，不是环比或经济增长。']
        else:
            lines += ['新增月份只补充贸易规模，本简报未核查跨月编码可比性，不据此计算环比。']
        url = new.get('source_url')
        if isinstance(url, str) and url.startswith('https://') and not any(c in url for c in '\n\r()<> '):
            lines += [f'[原始数据来源]({url})']
        lines += [f"月表SHA-256：`{new.get('output_sha256', '未记录')}`"]
    lines += ['', '## 哪些内容需要重新核查', '']
    if delta['added_months']:
        lines += ['- 引用“最新月份”的旧报告需要更新统计截止期；已有企业成本或价格判断不能自动延伸到新月份。']
    if delta['revised_months'] or delta['removed_months']:
        lines += ['- 引用修订或移除月份的金额、份额及其解释需要重新核查；旧报告保留其原版本，不能静默改写。']
    if delta['policy_changed']:
        lines += ['- 商品范围、税率及生效条件需要重新对照原文；文件变化本身不能证明政策已经调整。']
    if delta['status'] == 'unchanged':
        lines += ['- 本次本地差异未发现新增复核项。']
    lines += ['', '以上为程序生成的版本差异和复核提示，尚未自动检索并标记所有旧报告，也未生成新的AI解释。',
              '贸易金额不代表实际税款、损失或政策因果效果。', '']
    return '\n'.join(lines)


def current_update_brief(root, output_root=None):
    store = ExposureVersionStore(root)
    status = store.status()
    active = status.get('active') or {}
    version = status.get('active_version')
    if not version:
        raise VersionStoreError('尚无活动数据版本')
    store.release_root(version)
    previous = active.get('before_version')
    if not previous:
        return '# 贸易数据更新简报\n\n当前为首个登记版本，尚无前版可比较。\n'
    # Recompute differences from snapshots rather than trusting cached text.
    after=store.load_snapshot(version)
    report=render_update_brief(store.load_snapshot(previous), after)
    from .report_update_impact import scan_reports, render_report_impacts
    report+=render_report_impacts(scan_reports(output_root or root/'tmp/unified-research',store,after))
    return report
