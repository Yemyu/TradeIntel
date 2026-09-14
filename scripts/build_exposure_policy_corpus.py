"""Fetch the registered CBP notice once and build paragraph-linked lexical evidence."""
import argparse
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import Request, urlopen
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tradeintel_ai.exposure_policy import Paragraphs
URL = 'https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3ca1cf1'


def build(root=ROOT):
    directory = root / 'data/raw/policy/review2025'
    directory.mkdir(parents=True, exist_ok=True)
    raw = directory / 'cbp-63577329.html'
    metadata = directory / 'cbp-63577329.source.json'
    if not raw.exists():
        with urlopen(Request(URL, headers={'User-Agent': 'TradeIntel research project'}), timeout=45) as response:
            content = response.read(2_000_001)
        if len(content) > 2_000_000:
            raise ValueError('unexpected notice size')
        raw.write_bytes(content)
        metadata.write_text(json.dumps({'url': URL, 'retrieved_at': datetime.now(timezone.utc).isoformat(),
            'sha256': hashlib.sha256(content).hexdigest()}, indent=2))
    content = raw.read_bytes()
    source = json.loads(metadata.read_text())
    if source['sha256'] != hashlib.sha256(content).hexdigest():
        raise ValueError('source hash mismatch')
    parser = Paragraphs()
    parser.feed(content.decode('utf-8'))
    chunks = []
    started = False
    for index, text in enumerate(parser.rows):
        if text.startswith('The purpose of this message'):
            started = True
        if text.startswith('For ease of reference'):
            break
        if not started:
            continue
        chunks.append({'id': f'cbp63577329:p{index}', 'page_id': 'cbp63577329:html',
            'source': 'cbp63577329', 'title': 'CBP Section 301 implementation guidance',
            'published': '2024-12-31', 'page': 1, 'paragraph_index': index,
            'text': text, 'sha256': source['sha256'], 'url': URL, 'citation_url': URL,
            'local_path': str(raw.relative_to(root)), 'retrieved_at': source['retrieved_at']})
    combined = ' '.join(c['text'] for c in chunks)
    for expected in ['2804.61.00', '3818.00.00', '8101.94.00', '8101.99.10', '8101.99.80', 'January 1, 2025', 'o/than those obtained simply by sintering']:
        if expected not in combined:
            raise ValueError('missing required notice text: ' + expected)
    selected = []
    for i, chunk in enumerate(chunks):
        text = chunk['text']
        if text.startswith('The tariff increases take effect'):
            selected.append({**chunk, 'paragraph_indices': [chunk['paragraph_index']]})
        if text.startswith(('For certain polysilicon', 'For certain tungsten')):
            group = [chunk]
            for following in chunks[i + 1:]:
                if not following['text'].startswith(('(1)', '(2)', '(3)')):
                    break
                group.append(following)
            selected.append({**chunk, 'text': '\n'.join(c['text'] for c in group),
                             'paragraph_indices': [c['paragraph_index'] for c in group]})
    if len(selected) != 3:
        raise ValueError('expected effective-date and two product/rate sections')
    chunks = selected
    corpus = {'version': 1, 'extractor': 'stdlib HTMLParser paragraphs v1',
        'coverage': [{'source': 'cbp63577329', 'published': '2024-12-31', 'kind': 'HTML paragraphs',
                      'excluded': 'other sections including separate 100% technical correction, FTZ, attachments, later amendments, current total tariffs'}],
        'chunks': chunks, 'limitations': ['仅登记CBP执行通知正文；不是现行综合税则。',
            '段落索引是本地HTML提取序号，不是PDF页码；检索命中仍需核对具体主张。',
            '抓取版本来自当前网页，出版日期筛选不等于历史发布版本回测。']}
    output = root / 'data/processed/policy_exposure/policy_corpus.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(corpus, ensure_ascii=False, indent=2) + '\n')
    return {'chunks': len(chunks), 'output': str(output)}


if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    print(json.dumps(build(), ensure_ascii=False))
