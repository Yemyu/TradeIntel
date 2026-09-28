"""Extract real, saved metrics for the isolated visual prototype (no API)."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'tmp/public-brief-eval-v1/policy-q3-candidate-20260923-shape-r1/host_artifacts/q3/response.json'
OUT = ROOT / 'web/design-preview/data.json'

def main():
    raw = SOURCE.read_bytes()
    report = json.loads(raw)['report']
    metrics = report['evidence']['metrics']
    names = {'28046100': '高纯硅', '38180000': '电子用掺杂元素及晶圆相关商品',
             '81019400': '未锻造钨', '81019910': '钨条杆、板片等', '81019980': '其他钨制品'}
    rows = []
    for product, name in names.items():
        for month in range(2, 8):
            period = f'2026-{month:02}'
            row = {'product': product, 'name': name, 'period': period}
            for field in ('world', 'china'):
                found = next(m for m in metrics if m['id'] == f'metric:{product}:{period}:{field}')
                assert found['status'] == 'known'
                row[field] = found['value']
            rows.append(row)
    data = {'source': str(SOURCE.relative_to(ROOT)), 'source_sha256': hashlib.sha256(raw).hexdigest(),
            'data_version': report['data_version'], 'rows': rows,
            'note': '原型使用固定真实案例，非新生成报告。来源份额由同范围金额复算，跨期增速不在前端推导。'}
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    print(f'Extracted {len(rows)} real product-month rows: {OUT}')

if __name__ == '__main__':
    main()
