"""Current application evidence access, separate from frozen experiments."""
from copy import deepcopy
import hashlib
import re

from .policy_retrieval import PolicyRetriever as FrozenPolicyRetriever
from .policy_context_window import expand_context as original_expand


class PolicyRetriever(FrozenPolicyRetriever):
    def search(self, question, **kwargs):
        # Only remove a request-time prefix, never a current-policy qualifier
        # elsewhere in the question. The original question remains the task.
        scoped = question
        if isinstance(question, str) and len(question) <= 2000:
            scoped = re.sub(r'^(?:现在|目前|今天)[，,\s]*请(?:帮我)?(?=(?:分析|解释|查询|说明|回顾).*2018)',
                            '请', question, count=1)
        result = super().search(scoped, **kwargs)
        result['question'] = question
        result['scope_interpretation'] = {
            'version': 1, 'original_question': question,
            'checked_question': scoped,
            'rule': '仅移除明确2018历史请求开头的提问时态；其余范围限制沿用',
        }
        return result


def expand_context(retrieval, corpus):
    result = original_expand(retrieval, corpus)
    pages = {p['id']: p['text'] for p in corpus['pages']}
    groups = []
    for rank, source in enumerate(result['hits'], 1):
        hit = deepcopy(source)
        hit['parents'] = [{'chunk_id': hit['parent_chunk_id'],
                           'rank': rank, 'score': hit.get('score'),
                           'window_start': hit['start'], 'window_end': hit['end']}]
        groups.append(hit)
    # Merge pairwise until stable, keeping the earliest retrieval rank first.
    changed = True
    while changed:
        changed = False
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                a, b = groups[i], groups[j]
                same_source = all(a.get(k) == b.get(k) for k in
                                  ('page_id', 'local_path', 'published', 'url'))
                start, end = min(a['start'], b['start']), max(a['end'], b['end'])
                if (same_source and max(a['start'], b['start']) < min(a['end'], b['end'])
                        and end - start <= 2400):
                    a.update(start=start, end=end, text=pages[a['page_id']][start:end],
                             id=f"{a['page_id']}:w{start}-{end}")
                    a['parents'].extend(b['parents'])
                    del groups[j]
                    changed = True
                    break
            if changed:
                break
    for hit in groups:
        hit['parents'].sort(key=lambda parent: parent['rank'])
        hit['text_sha256'] = hashlib.sha256(hit['text'].encode()).hexdigest()
    total = sum(len(h['text']) for h in groups)
    unique = len({(h['page_id'], i) for h in groups for i in range(h['start'], h['end'])})
    if total > 7200:
        raise ValueError('Merged context exceeds budget')
    result['hits'] = groups
    result['context_expansion'].update(
        version=2, premerge_chars=result['context_expansion']['total_chars'],
        total_chars=total, unique_chars=unique, duplicated_chars=total-unique,
        merge_rule='same source/page, overlap, union <= 2400 characters')
    return result
