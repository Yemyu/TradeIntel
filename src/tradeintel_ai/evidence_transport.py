"""Reversible exact-value deduplication for bounded experiment inputs.

This does not summarize, truncate, translate, or select evidence. References
are transport aliases, not new policy citations or evidentiary claims.
"""
from collections import Counter
import json


def _key(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def pack(value):
    counts = Counter()
    def count(item):
        if isinstance(item, dict) and any(k in item for k in ('$ref', '$columns', '$groups')):
            raise ValueError('reserved transport key in original evidence')
        key = _key(item)
        if len(key) >= 40:
            counts[key] += 1
        if isinstance(item, dict):
            for child in item.values(): count(child)
        elif isinstance(item, list):
            for child in item: count(child)
    count(value)
    aliases, table = {}, {}
    def encode(item):
        key = _key(item)
        if key in aliases:
            return {'$ref':aliases[key]}
        if isinstance(item, dict):
            encoded = {k:encode(v) for k,v in item.items()}
        elif isinstance(item, list):
            # Repeated metric rows share long field names. A column/row table
            # retains every field and value without repeating its header.
            groups = []
            for child in item:
                keys = tuple(child) if isinstance(child, dict) else None
                if groups and keys is not None and groups[-1][0] == keys:
                    groups[-1][1].append(child)
                else:
                    groups.append((keys,[child]))
            if any(keys and len(rows)>1 for keys,rows in groups):
                encoded = {'$groups':[
                    {'$columns':list(keys), '$rows':[[encode(row[k]) for k in keys] for row in rows]}
                    if keys and len(rows)>1 else [encode(row) for row in rows]
                    for keys,rows in groups]}
            else:
                encoded = [encode(v) for v in item]
        else:
            encoded = item
        if counts[key] > 1:
            label = f'R{len(aliases)+1}'
            aliases[key] = label
            table[label] = encoded
            return {'$ref':label}
        return encoded
    body = encode(value)
    result = {'encoding':'exact-value-references-v1',
              'instruction':'Expand $ref via references. $columns/$rows encode tables; concatenate $groups in order. Recursive, lossless deduplication only; aliases are not evidence IDs.',
              'references':table, 'evidence':body}
    if unpack(result) != value:
        raise ValueError('evidence transport failed lossless roundtrip')
    return result


def unpack(packet):
    if packet.get('encoding') != 'exact-value-references-v1':
        raise ValueError('unknown transport encoding')
    def decode(item, seen):
        if isinstance(item, dict):
            if set(item) == {'$groups'}:
                return [row for group in item['$groups'] for row in decode(group,seen)]
            if set(item) == {'$columns','$rows'}:
                columns = item['$columns']
                if len(set(columns)) != len(columns) or any(len(row)!=len(columns) for row in item['$rows']):
                    raise ValueError('invalid column table')
                return [{k:decode(v,seen) for k,v in zip(columns,row)} for row in item['$rows']]
            if set(item) == {'$ref'}:
                label = item['$ref']
                if label in seen or label not in packet['references']:
                    raise ValueError('cyclic or unknown transport reference')
                return decode(packet['references'][label], seen | {label})
            return {k:decode(v,seen) for k,v in item.items()}
        if isinstance(item, list):
            return [decode(v,seen) for v in item]
        return item
    return decode(packet['evidence'], set())
