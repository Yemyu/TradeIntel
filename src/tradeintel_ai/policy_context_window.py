"""Bounded same-page expansion, separate from frozen lexical retrieval."""
from copy import deepcopy


def expand_context(retrieval,corpus):
    pages={p['id']:p['text'] for p in corpus['pages']}
    chunks={c['id']:c for c in corpus['chunks']}
    bounds={}
    for c in corpus['chunks']:
        old=bounds.get(c['page_id'],(c['start'],c['end']))
        bounds[c['page_id']]=(min(old[0],c['start']),max(old[1],c['end']))
    if len(retrieval['hits'])>3: raise ValueError('Only top three expansion supported')
    result=deepcopy(retrieval)
    expanded=[]
    for hit in retrieval['hits']:
        original=chunks.get(hit['id'])
        if original is None: raise ValueError('Unknown source chunk')
        for key,value in original.items():
            if hit.get(key)!=value: raise ValueError('Source chunk changed')
        page=pages[original['page_id']]
        if page[hit['start']:hit['end']]!=hit['text']: raise ValueError('Source offset mismatch')
        lo,hi=bounds[hit['page_id']]
        start=max(lo,hit['start']-600)
        end=min(hi,hit['end']+600)
        if end-start>2400: raise ValueError('Window exceeds budget')
        expanded.append({**hit,'id':f"{hit['page_id']}:w{start}-{end}",
            'parent_chunk_id':hit['id'],'start':start,'end':end,'text':page[start:end]})
    total=sum(len(h['text']) for h in expanded)
    unique=set((h['page_id'],i) for h in expanded for i in range(h['start'],h['end']))
    if total>7200: raise ValueError('Total context exceeds budget')
    result.update(hits=expanded,context_expansion={'version':1,'radius_chars':600,
        'total_chars':total,'unique_chars':len(unique),'duplicated_chars':total-len(unique),
        'original_chars':sum(len(h['text']) for h in retrieval['hits'])})
    return result
