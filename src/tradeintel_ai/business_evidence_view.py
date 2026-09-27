"""Separate transport/provenance metadata from the model's business evidence.

Only enumerated machine fields move to the audit sidecar. Every removed value
and source alias is reversible; policy prose, metrics and limitations stay.
"""
from copy import deepcopy
from .evidence_transport import pack, unpack

AUDIT_KEYS = frozenset({'sha256', 'text_sha256', 'document_sha256', 'path',
                        'row_hts8', 'derived_from'})


def build_view(information):
    sources = information.get('sources', [])
    source_urls = {s.get('url') for s in sources if s.get('url')}
    aliases = {s['id']:f'trade_source_{i+1}' for i,s in enumerate(sources)
               if isinstance(s.get('id'),str) and s['id'].startswith('trade:')}
    aliases.update({m['id']:f'm{i+1}' for i,m in enumerate(information.get('metrics', []))})
    removed = []
    shared = ('origin','effective_date','clock_24h','timezone','entry_events')
    facts = information.get('policy_facts', {})
    def visit(value, path):
        if isinstance(value, dict):
            result = {}
            for key,item in value.items():
                # Field references retain the clause ID; the common source
                # catalog carries its URL and the top level carries version.
                redundant_ref = ('field_refs' in path and (
                    (key in {'policy_id','data_version'} and item == information.get(key))
                    or (key == 'url' and item in source_urls)))
                shared_scope = (len(path)==4 and path[0]=='policy_facts' and path[1]=='product_rates'
                                and path[3]=='details' and key in shared and item == facts.get(key))
                repeated_period = (len(path)==2 and path[0]=='metrics' and key=='period'
                                   and item==information.get('request',{}).get('month'))
                if key in AUDIT_KEYS or redundant_ref or shared_scope or repeated_period:
                    removed.append({'parent':list(path),'key':key,'value':deepcopy(item)})
                else:
                    result[key] = visit(item, (*path,key))
            return result
        if isinstance(value, list):
            return [visit(v,(*path,i)) for i,v in enumerate(value)]
        return aliases.get(value,value) if isinstance(value,str) else value
    business = visit(information, ())
    business['_shared_values'] = {'product_details':'Missing origin/effective_date/clock_24h/timezone/entry_events inherit policy_facts fields; differing values stay explicit.',
                                 'metrics':'Missing period inherits request.month; differing periods stay explicit.'}
    packet = pack(business)
    audit = {'schema':'business-evidence-audit-v1', 'removed_machine_fields':removed,
             'source_aliases':aliases, 'excluded_keys':sorted(AUDIT_KEYS)}
    if restore(packet,audit) != information:
        raise ValueError('business evidence split is not reversible')
    return packet, audit


def restore(packet, audit):
    reverse = {short:original for original,short in audit['source_aliases'].items()}
    def rename(value):
        if isinstance(value,dict): return {k:rename(v) for k,v in value.items()}
        if isinstance(value,list): return [rename(v) for v in value]
        return reverse.get(value,value) if isinstance(value,str) else value
    result = rename(unpack(packet))
    result.pop('_shared_values')
    for field in audit['removed_machine_fields']:
        parent = result
        for step in field['parent']: parent = parent[step]
        parent[field['key']] = deepcopy(field['value'])
    return result
