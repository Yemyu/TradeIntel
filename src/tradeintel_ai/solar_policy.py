"""Candidate-only evidence extraction from the official Federal Register HTML."""
import hashlib
import json
import re
from html.parser import HTMLParser

BASE = 'data/candidates/solar2024'
CODES = {'85414200', '85414300'}


class PreText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.inside = False
        self.parts = []
    def handle_starttag(self, tag, attrs):
        if tag == 'pre': self.inside = True
    def handle_endtag(self, tag):
        if tag == 'pre': self.inside = False
    def handle_data(self, data):
        if self.inside: self.parts.append(data)


def build_corpus(root):
    meta = json.loads((root / BASE / 'source.json').read_text())
    relative = BASE + '/2024-21217.html'
    raw = (root / relative).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != meta['sha256']:
        raise ValueError('solar source fingerprint mismatch')
    parser = PreText(); parser.feed(raw.decode('utf-8'))
    text = ''.join(parser.parts)
    patterns = {
        'products': r'(?m)^8541\.42\.00[^\n]*\n[^\n]*\n8541\.43\.00[^\n]*\n[^\n]*',
        'rate': r'(?ms)^9903\.91\.02\.{3,}.*?(?=^9903\.91\.03\.)',
        'general_conditions': r'(?s)``31\. \(a\) As provided.*?(?=``\(b\) Heading)',
        'scope_and_effective': r'(?s)``\(c\) Heading 9903\.91\.02.*?(?=``\(d\) Heading)',
    }
    chunks = []
    for label, pattern in patterns.items():
        matches = list(re.finditer(pattern, text))
        if len(matches) != 1:
            raise ValueError('ambiguous or missing official section: ' + label)
        match = matches[0]
        chunks.append({'id':'fr202421217:'+label, 'source':'fr202421217',
                       'title':label, 'published':meta['publication_date'],
                       'text':match.group(), 'start':match.start(), 'end':match.end(),
                       'citation_url':meta['url'], 'local_path':relative, 'sha256':digest})
    return {'policy_id':'us_301_solar2024', 'status':'candidate_not_published',
            'extractor':'html-pre-exact-spans-v1', 'chunks':chunks,
            'limitations':['存档公告条款，不是现行综合税率或逐笔报关判断。',
                           '偏移量针对解码后的pre文本，不是PDF页码。',
                           '全部四组同时提供，包括一般适用限定；不自动涵盖后续修订。']}


def retrieve_solar_policy(root, question, *, as_of):
    from datetime import date
    date.fromisoformat(as_of)
    # Rebuild exact sections to reject changed spans, texts or missing caveats.
    expected = build_corpus(root)
    stored = json.loads((root / BASE / 'policy_corpus.json').read_text())
    if stored != expected:
        raise ValueError('solar index differs from verified original sections')
    reason = None
    mentioned = re.findall(r'(?<!\d)(?:\d{8,10}|\d{4}\.\d{2}\.\d{2}(?:\.\d{2})?)(?!\d)', question)
    if any(c.replace('.','') not in CODES for c in mentioned):
        reason = '税号不属于该光伏电池及组件候选案例。'
    if re.search(r'最新|现行|今天|current|latest|today', question, re.I):
        reason = '只能解释存档条款，不能确认现行综合税率。'
    if as_of < '2024-09-18':
        reason = '公告晚于请求截止日。'
    return {'status':'unsupported' if reason else 'candidate_evidence',
            'policy_id':expected['policy_id'], 'question':question, 'as_of':as_of,
            'hits':[] if reason else expected['chunks'], 'reason':reason,
            'method':'registered_complete_sections', 'limitations':expected['limitations']}
