"""Fixed, escaped, read-only review of one saved run; no provider access."""
from html import escape
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'tmp/trade-aware-interpretation-v1-first/run'
PINNED={
    'source-packet.zh-CN.md':'828f39ef105ab22c88d30b6f4ef8048f4f9055122a8537d565d9026b353a17ba',
    'interpretation-response.json':'5603d3fe80d3e98711550266a4d9ed0e2003d45e50bb7a177088bf980d09a69a',
    'trade-evidence.json':'0d5a5c8604c2324f69de206fe7918bfbb198af66040328c01a1be7d611cf1ee2'}


def build(run=RUN, destination=ROOT/'web/research-review.html'):
    raw={name:(run/name).read_bytes() for name in PINNED}
    for name,digest in PINNED.items():
        if hashlib.sha256(raw[name]).hexdigest()!=digest: raise ValueError('review belongs to a different saved run')
    trade=json.loads(raw['trade-evidence.json'])
    answer=json.loads(json.loads(raw['interpretation-response.json'])['text'])
    rows=trade['data']['series'][0]['product_breakdown']
    cards=''.join('<article><h3>HTS '+escape(r['hts8'])+'</h3><dl>'
        +f'<dt>美国全部来源消费进口</dt><dd>${r["all_origins_value_usd"]:,}</dd>'
        +f'<dt>其中中国原产</dt><dd>${r["china_value_usd"]:,}</dd>'
        +f'<dt>中国份额</dt><dd>{r["china_value_usd"]/r["all_origins_value_usd"]*100:.2f}%</dd>'
        +'</dl></article>' for r in rows)
    verdicts=[('不采纳为优先调查','本次数据没有给出转运或规避的证据。不能把第三国来源自动当成规避；这条提问也不是已发现违规。'),
              ('有限用途，仍需审阅','正确区分贸易统计与企业税负、合同安排。可作为研究边界提醒，但不是已经分析出价格影响，也不是深度个性化结论。')]
    notes=''
    for i,(note,(label,reason)) in enumerate(zip(answer['notes'],verdicts)):
        notes+=f'<article><h3>建议 {i+1}</h3><p class="tag">AI 原话 · 未批准</p><blockquote>{escape(note["text"])}</blockquote><p>事实关联：{escape(", ".join(note["fact_ids"]))}</p><div class="review"><strong>助手审阅：{label}</strong><p>{reason}</p></div></article>'
    page=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TradeShock AI · 真实研究结果与审阅</title>
<style>body{{margin:0;background:#f3f6fa;color:#172c40;font:17px/1.75 system-ui,sans-serif}}main{{max-width:1080px;margin:auto;padding:28px 20px}}h1,h2,h3{{line-height:1.35}}section{{margin:28px 0}}article,.box{{background:white;padding:22px;border:1px solid #d9e2eb;border-radius:12px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px}}.banner,.review{{background:#fff4dd;border-left:4px solid #ad6900;padding:16px}}.tag,dt,small{{color:#475d70}}dd{{margin:0 0 12px;font-weight:700;font-size:23px}}blockquote{{margin:12px 0;border-left:3px solid #8097ae;padding-left:14px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.6 monospace}}summary{{cursor:pointer;padding:12px}}a{{color:#125b9b}}small{{overflow-wrap:anywhere}}</style></head><body><main>
<a href="/">← 返回查询首页</a><h1>这次研究查到了什么，哪些建议能用？</h1>
<p>2024 年光伏政策 · 2026 年 7 月消费进口 · 两类登记商品</p>
<div class="banner"><strong>真实运行记录，只读展示；整份未批准。</strong><br>数据由程序计算，建议来自一次 GLM-4.7 调用，审阅意见由开发助手另行撰写。打开本页不会调用 API；不是实时数据，也不是第二案例已经开放。</div>
<section><h2>一、程序查到的贸易规模</h2><div class="grid">{cards}</div><p>份额分母是美国该税号全部来源进口。这不是中国出口依赖率，也不是关税税基、损失或政策效果。</p></section>
<section><h2>二、AI 原话与逐项审阅</h2><p>事实编号只说明引用关联，不证明推论成立。以下没有把审阅建议改写回模型答案。</p><div class="grid">{notes}</div></section>
<section class="box"><h2>三、你可以如何使用</h2><p>先确认商品和月份，查看贸易规模；再区分已有统计与尚缺的企业合同、实际税负信息。不要据此认定违规、预测涨价或作采购决定。</p><p>本页只有存档查看功能。首页的查询功能仍限已启用案例；第二案例仍在候选阶段，没有“点击即批准”功能。</p><a href="https://www.govinfo.gov/content/pkg/FR-2024-09-18/html/2024-21217.htm" target="_blank" rel="noopener noreferrer">查看本案例存档政策原文</a></section>
<section class="box"><h2>四、复核记录</h2><p>一次模型请求，1725 tokens；无重试。既有记录未改写，不是独立准确率评测。</p><details><summary>查看原始模型 JSON（已转义）</summary><pre>{escape(json.loads(raw['interpretation-response.json'])['text'])}</pre></details><details><summary>查看程序贸易证据 JSON（已转义）</summary><pre>{escape(json.dumps(trade,ensure_ascii=False,indent=2))}</pre></details><small>数据版本：{escape(trade['data_version'])}<br>模型回答文件 SHA-256：{PINNED['interpretation-response.json']}<br>本页审阅意见不是独立专业审核，尚未进行浏览器视觉验收。</small></section></main></body></html>'''
    page=page.replace('</main>', '<section class="box"><h2>完整来源资料包</h2><details><summary>展开政策事实卡、全部原文及数据来源</summary><pre>'+escape(raw['source-packet.zh-CN.md'].decode())+'</pre></details></section></main>')
    destination.write_text(page)
    return destination

if __name__=='__main__': print(build())
