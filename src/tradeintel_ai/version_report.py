"""Read-only, version-pinned data report. No generated economic interpretation."""
from html import escape
from .exposure_version_store import ExposureVersionStore, VersionStoreError
from .update_brief import _amount, _money


def render_version_report(snapshot):
    # Validate the content address even when used independently of the store.
    from .exposure_version_store import snapshot_difference
    snapshot_difference(snapshot, snapshot)
    rows=[]
    for month, entry in sorted(snapshot['months'].items()):
        world=_amount(entry,'all_origins_value_usd');china=_amount(entry,'china_value_usd')
        if world is not None and china is not None and china>world:
            raise VersionStoreError('中国金额大于全部来源金额')
        rows.append((month,entry,world,china))
    maximum=max((w for _,_,w,_ in rows if w is not None),default=0)
    body=[]
    for month,entry,world,china in rows:
        share=f'{china/world*100:.2f}%' if world and china is not None else '未知'
        bar=f'<span class="bar" style="width:{world/maximum*100:.3f}%"></span>' if maximum and world is not None else '无可绘制数据'
        body.append(f'<tr><th>{escape(month)}</th><td>{_money(world)}</td><td>{_money(china)}</td><td>{share}</td><td>{bar}</td></tr>')
    sources=[]
    for month,entry,_,_ in rows:
        url=entry.get('source_url','')
        link=f'<a href="{escape(url,quote=True)}">来源压缩包</a>' if isinstance(url,str) and url.startswith('https://') else '来源网址未记录'
        sources.append(f'<li>{escape(month)}：{link}；月表SHA-256：<code>{escape(str(entry.get("output_sha256","未记录")))}</code></li>')
    version=escape(snapshot['version'])
    return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>贸易数据报告 · {escape(snapshot['end'])}</title>
<style>body{{max-width:1100px;margin:40px auto;padding:0 20px;font:16px/1.7 system-ui;color:#17283b}}table{{border-collapse:collapse;width:100%}}td,th{{padding:8px;border-bottom:1px solid #ddd;text-align:right}}td:last-child{{width:25%}}.bar{{display:block;height:14px;background:#357bb0}}code{{overflow-wrap:anywhere}}@media print{{a{{color:inherit}}}}</style>
<h1>贸易数据报告</h1><p>统计范围：{escape(snapshot['start'])} 至 {escape(snapshot['end'])}；政策登记：{escape(snapshot['policy_id'])}。</p>
<p>固定数据版本：<code>{version}</code>。<a href="/api/version-report?version={version}">此版本固定链接</a>（后续更新不改变本链接）。可使用浏览器打印保存PDF。</p>
<p>这是程序生成的数据页，不是AI分析或整篇旧报告的自动改写。仅覆盖登记税号，不代表美国全部商品；不覆盖历史报告，也不沿用其AI解释。</p>
<p>版本模式：{escape(str(snapshot.get('mode','未记录')))}。窗口回放不代表新下载或严格历史实时回测。统计截止月份不是政策信息的实时截止日。</p>
<h2>月度表及进口规模条形图</h2><p>金额单位：美元。中国份额＝本范围中国原产进口额÷本范围全部来源进口额，不包含美国本土生产。各月条形长度使用同一金额比例尺；未核查跨期编码可比性，不计算环比或解释政策效果。</p>
<table><thead><tr><th>月份</th><th>全部来源</th><th>中国原产</th><th>中国份额</th><th>全部来源规模</th></tr></thead><tbody>{''.join(body)}</tbody></table>
<h2>逐月来源</h2><ul>{''.join(sources)}</ul><p>缺失金额不按零处理；零分母份额记为未知。金额不是税款、企业损失或政策因果影响。</p></html>'''


def version_report(root, version=None, *, policy_id=None):
    from pathlib import Path
    from .policy_cases import resolve_case
    case = resolve_case(policy_id) if policy_id else None
    store=ExposureVersionStore(root, Path(root) / case.versions) if case else ExposureVersionStore(root)
    selected=version if version is not None else store.active_version()
    if not selected:raise VersionStoreError('尚无活动版本')
    store.release_root(selected)
    snapshot = store.load_snapshot(selected)
    if case and snapshot['policy_id'] != case.policy_id:
        raise VersionStoreError('数据版本不属于指定政策')
    html = render_version_report(snapshot)
    if case and case.policy_id != 'us_301_review2025_tungsten_solar':
        html = html.replace('?version='+selected+'"', '?version='+selected+'&amp;policy_id='+escape(case.policy_id, quote=True)+'"')
    return html
