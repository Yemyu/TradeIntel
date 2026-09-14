"""Render a read-only walkthrough from saved evidence; never call a model."""
import hashlib
from html import escape
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT/'tmp/solar-source-choice-v1-first-20260914/normalized-offline-replay'


def build(run=RUN, destination=ROOT/'web/solar-demo.html'):
    def read(name):
        return json.loads((run/name).read_text())
    state, trade, policy = read('status.json'), read('trade-evidence.json'), read('policy-evidence.json')
    coverage = read('condition-coverage.json')
    raw_report = (run/'report.zh-CN.md').read_text()
    if (state['status'] != 'draft_needs_review' or state['data_version'] != trade['data_version']
            or trade['data']['policy_id'] != 'us_301_solar2024'
            or policy['policy_id'] != 'us_301_solar2024'
            or not trade['data']['coverage_complete']):
        raise ValueError('demo evidence binding mismatch')
    if trade['data']['months'] != 1:
        raise ValueError('walkthrough requires one month')
    row = trade['data']['series'][0]
    if trade['data']['hts8'] != '85414300' or row['month'] != '2026-06':
        raise ValueError('review notes only cover the registered run')
    refs = {h['id']:h for h in policy['hits']}
    for binding in coverage['source_bindings']:
        if refs[binding['citation']]['text'] != binding['source_text']:
            raise ValueError('bound original differs from policy evidence')
    world, china = row['all_origins_value_usd'], row['china_value_usd']
    sources = ''.join(f'<details><summary>{escape(h["title"])}</summary><p><a href="{escape(h["citation_url"], quote=True)}">官方出处</a></p><pre>{escape(h["text"])}</pre></details>' for h in policy['hits'])
    html = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TradeShock AI｜单商品离线流程演示</title>
<style>body{{font:17px/1.8 system-ui,sans-serif;background:#f4f6f9;color:#172b40;margin:0}}main{{max-width:980px;margin:auto;padding:32px 20px}}section{{background:white;padding:24px;margin:20px 0;border-radius:12px}}h1,h2{{line-height:1.4}}.warning{{border-left:5px solid #bd6c00;background:#fff5dd}}.metrics{{display:flex;gap:24px;flex-wrap:wrap}}.metrics strong{{display:block;font-size:25px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.65 ui-monospace,monospace}}summary{{cursor:pointer;padding:12px 0}}small{{overflow-wrap:anywhere}}a{{color:#155c99}}</style>
<main><h1>一份贸易政策简报是怎样产生的？</h1>
<section class="warning"><b>单商品只读流程演示，不是第二案例已上线，也不是双商品验收通过。</b><br>本页使用已有真实模型回答的离线规范化重放（source-choice-v1，85414300、2026年6月；原始运行因格式失败）。后续双商品2026年7月任务先遇到断连，一次恢复已收到回答，但格式和部分解释仍未通过；之后的事实卡加AI建议路径已有真实输出，尚未完成案例验收。打开本页不调用API。内容仍需人工审阅。</section>
<section><h2>1．用户提出问题</h2><p>{escape(read('input.json')['question'])}</p><p>程序识别：2024光伏电池/组件政策 → 85414300 → 2026年6月。它不是根据关键词随便写一篇新闻摘要；本页也不代表全部登记商品都已完成验收。</p></section>
<section><h2>2．程序查真实贸易资料并计算</h2><div class="metrics"><div>美国全部来源消费进口额<strong>${world:,}</strong></div><div>其中中国原产<strong>${china:,}</strong></div><div>中国份额<strong>{china/world*100:.2f}%</strong></div></div><p>份额分母是美国该税号全部来源进口额。这不是中国出口对美依赖率，也不是关税损失、实际税基或供应替代能力。</p></section>
<section><h2>3．AI解释政策，程序附原文</h2><p>AI负责说明商品、税率、生效、原产地和一般限定，并选证据编号。程序提供完整原文，避免模型复制长表格时漏句。</p>{sources}</section>
<section class="warning"><h2>4．本次内容补核：还有什么不能直接相信？</h2><p><b>以下是开发助手审阅意见，不是模型原回答，也不是独立专业法律审核。</b></p><p>原回答“产品继续受反倾销、反补贴或其他税费约束”需要明确限定：其他税费<b>仅在依法适用时</b>继续适用，不能据此认定这件商品一定同时缴纳所有税费。</p><p>建议表述：“如该商品适用反倾销、反补贴或其他税费，这些税费仍继续适用；具体适用情况需另行核查。”此建议未写回原模型答案。</p><p>章98存在一般例外及特定子目特殊处理，本演示不作逐笔报关裁决。报告解释的是存档条款，不是今天的综合税率。</p></section>
<section><h2>5．交付给分析人员的用途</h2><p>先获得可回查的贸易规模和政策条件，再补核其他适用税费、具体商品和后续修订，用于撰写人工审阅后的简报。不是自动批准、走势预测或因果结论。</p><details><summary>查看完整原始重放报告（未替换中文内容）</summary><pre>{escape(raw_report)}</pre></details></section>
<section><h2>来源与运行边界</h2><small>数据版本：{escape(state['data_version'])}<br>报告SHA-256：{hashlib.sha256(raw_report.encode()).hexdigest()}<br>本页展示静态存档，不自动更新。不能把原始失败、离线重放和人工审阅混成一次模型成功。</small></section></main></html>'''
    destination.write_text(html)
    return destination


if __name__ == '__main__':
    print(build())
