"""Registered new-case policy retrieval using the existing lexical retriever."""
import hashlib
import json
import re
from html.parser import HTMLParser
from .policy_retrieval import PolicyRetriever

CODES = {'28046100', '38180000', '81019400', '81019910', '81019980'}


class Paragraphs(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.current = None
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag == 'p':
            self.current = []

    def handle_data(self, data):
        if self.current is not None:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == 'p' and self.current is not None:
            text = ' '.join(''.join(self.current).split())
            if text:
                self.rows.append(text)
            self.current = None


def scope_check(question):
    # Remove only explicit prohibitions on current-rate inference. A remaining
    # affirmative request for current rates must still be blocked.
    checked = re.sub(r'(?:不要|不必|无需|不)(?:推断|推测|确认|查询|解释)(?:今天|目前|现行|最新)(?:的)?(?:综合|全部|总)?税率', '', question)
    if re.search(r'现行|最新|今天|目前|current|latest|today', checked, re.I):
        return '登记的是2024年执行通知，不能确认现行全部税率。'
    codes = re.findall(r'(?<!\d)(?:\d{8,10}|\d{4}\.\d{2}\.\d{2}(?:\.\d{2})?)(?!\d)', question)
    if any(c.replace('.', '') not in CODES for c in codes):
        return '查询税号不在本通知登记的五个HTS8中。'
    return None


def retrieve_exposure_policy(root, question, *, as_of):
    path = root / 'data/processed/policy_exposure/policy_corpus.json'
    corpus = json.loads(path.read_text())
    parsed = {}
    for chunk in corpus['chunks']:
        raw = root / chunk['local_path']
        if hashlib.sha256(raw.read_bytes()).hexdigest() != chunk['sha256']:
            raise ValueError('policy source hash mismatch')
        if raw not in parsed:
            parser = Paragraphs()
            parser.feed(raw.read_text())
            parsed[raw] = parser.rows
        indices = chunk.get('paragraph_indices', [chunk['paragraph_index']])
        if (not indices or any(type(i) is not int or not 0 <= i < len(parsed[raw]) for i in indices)
                or '\n'.join(parsed[raw][i] for i in indices) != chunk['text']):
            raise ValueError('policy chunk differs from source paragraph')
    result = PolicyRetriever(corpus, scope_checker=scope_check).search(
        question, as_of=as_of, top_k=3,
        search_query='tungsten polysilicon wafers subheadings additional duty January 1 2025')
    return {**result, 'policy_id': 'us_301_review2025_tungsten_solar'}
