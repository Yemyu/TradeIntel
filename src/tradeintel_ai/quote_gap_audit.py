"""Offline alignment proposal. Never a plan, repair, or execution permission.

Keep model quotes and host-observed gaps separate. Semantic disposition of a
gap is deliberately absent; a human must review the original request in full.
"""
from copy import deepcopy
import json
from hashlib import sha256

from .request_coverage import validate_unit_labels, normalize_neutral_trade_units


VERSION = 'host-gap-review-proposal-0102'
SEPARATORS = frozenset('，；。')
# Conservative first version: do not infer scope inside quoted/bracketed text.
SCOPE_MARKS = frozenset('"\'“”‘’「」『』()（）[]【】{}《》<>')


def audit_quote_gaps(units, question, *, neutral_source=None):
    """Return a lossless, non-executable review proposal or reject ambiguity.

    The workflow can opt into a separate review gate. Strict coverage still
    rejects responses that omit punctuation.
    """
    if not isinstance(question, str) or not question.strip():
        raise ValueError('question must be nonempty text')
    if not isinstance(units, list) or not units or len(units) > 100:
        raise ValueError('quoted units must contain 1–100 units')
    # Validate labels on a copy, not as a coverage claim about the user's
    # question. Original offsets are derived separately below.
    if neutral_source is not None:
        if not isinstance(neutral_source, dict) or set(neutral_source) not in (
                {'request_units', 'comparison'}, {'request_units', 'comparison', 'clarification'}):
            raise ValueError('neutral gap source fields')
        if type(neutral_source.get('clarification', False)) is not bool:
            raise ValueError('neutral clarification flag')
        normalized, _ = normalize_neutral_trade_units(neutral_source['request_units'],
                                                      neutral_source['comparison'],
                                                      clarification=neutral_source.get('clarification', False))
        if normalized != units:
            raise ValueError('neutral source differs from derived gap units')
    labelled = validate_unit_labels(units)
    segments = []
    cursor = 0

    def save_gap(start, end):
        if start == end:
            return
        text = question[start:end]
        if text.strip():
            if start == 0:
                raise ValueError('leading punctuation requires separate review')
            if any(not c.isspace() and c not in SEPARATORS for c in text):
                raise ValueError('non-separator request text omitted')
            if any(c in SCOPE_MARKS for c in question):
                raise ValueError('quoted or bracketed scope requires separate review')
            left, right = question[:start].rstrip(), question[end:].lstrip()
            if left and right and left[-1].isnumeric() and right[0].isnumeric():
                raise ValueError('numeric separator requires separate review')
        segments.append({'source': 'host_gap', 'start': start, 'end': end,
                         'quote': text, 'semantic_disposition': 'unreviewed'})

    for index, unit in enumerate(labelled):
        start = question.find(unit['quote'], cursor)
        if start < 0:
            raise ValueError('quote changed, reordered or not found')
        save_gap(cursor, start)
        cursor = start + len(unit['quote'])
        segments.append({'source': 'model_quote', 'start': start, 'end': cursor,
                         'unit_index': index, **deepcopy(unit)})
    save_gap(cursor, len(question))
    gaps = [s for s in segments if s['source'] == 'host_gap']
    result = {'version': VERSION, 'question': question,
            'question_sha256': sha256(question.encode('utf-8')).hexdigest(),
            'model_units': deepcopy(units), 'segments': segments,
            'status': 'review_required' if any(g['quote'].strip() for g in gaps)
            else 'literal_complete',
            'model_literal_coverage_complete': not any(g['quote'].strip() for g in gaps),
            'semantic_coverage_verified': False, 'executable': False}
    if neutral_source is not None:
        result['neutral_source'] = deepcopy(neutral_source)
        result['model_units_source'] = 'host_derived_from_neutral_source'
    return result


def digest_audit(audit):
    """Stable binding for an independent gap-review decision."""
    return sha256(json.dumps(audit, sort_keys=True, ensure_ascii=False,
                             separators=(',', ':')).encode('utf-8')).hexdigest()


def validate_alignment(audit, question, units):
    """Rebuild host provenance rather than trusting supplied offsets/flags."""
    expected = audit_quote_gaps(units, question, neutral_source=audit.get('neutral_source'))
    if digest_audit(audit) != digest_audit(expected):
        raise ValueError('host alignment changed')
    return [{key: s[key] for key in ('start', 'end', 'quote', 'kind', 'target', 'id', 'task_id')}
            for s in expected['segments'] if s['source'] == 'model_quote']


def validate_gap_review(audit, submission, reviewer=None):
    """Validate an explicit human decision about each host-observed gap.

    Passing means only that the reviewer accepted the listed separators for
    this exact audit. It never changes semantic_coverage_verified and cannot
    approve a different question or a changed gap list.
    """
    if not isinstance(audit, dict) or audit.get('version') != VERSION:
        raise ValueError('gap audit version mismatch')
    validate_alignment(audit, audit.get('question'), audit.get('model_units'))
    if reviewer is None:
        reviewer = submission.get('reviewer') if isinstance(submission, dict) else None
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError('explicit gap reviewer required')
    if not isinstance(submission, dict):
        raise ValueError('gap review must be an object')
    if submission.get('audit_sha256') != digest_audit(audit):
        raise ValueError('gap review is not bound to this audit')
    overall = submission.get('overall')
    if (not isinstance(overall, dict) or overall.get('status') not in ('pass', 'fail')
            or not isinstance(overall.get('reason'), str) or not overall['reason'].strip()):
        raise ValueError('gap review overall decision and reason required')
    expected = [g for g in audit.get('segments', []) if g.get('source') == 'host_gap'
                and str(g.get('quote', '')).strip()]
    entries = submission.get('gaps')
    if not isinstance(entries, list) or len(entries) != len(expected):
        raise ValueError('gap review decisions are incomplete')
    by_position = {}
    for row in entries:
        if not isinstance(row, dict):
            raise ValueError('invalid gap decision')
        if type(row.get('start')) is not int or type(row.get('end')) is not int:
            raise ValueError('gap offsets must be integers')
        key = (row.get('start'), row.get('end'))
        if key in by_position:
            raise ValueError('duplicate gap decision')
        by_position[key] = row
    approved = overall['status'] == 'pass'
    checked = []
    for gap in expected:
        key = (gap['start'], gap['end'])
        row = by_position.get(key)
        if row is None or row.get('quote') != gap['quote']:
            raise ValueError('gap position or quote mismatch')
        if row.get('status') not in ('accepted_separator', 'rejected'):
            raise ValueError('unknown gap decision')
        if not isinstance(row.get('reason'), str) or not row['reason'].strip():
            raise ValueError('gap decision reason required')
        approved = approved and row['status'] == 'accepted_separator'
        checked.append({'start': gap['start'], 'end': gap['end'],
                        'quote': gap['quote'], 'status': row['status'],
                        'reason': row['reason']})
    return {'version': 'gap-review-0102', 'reviewer': reviewer,
            'audit_sha256': digest_audit(audit),
            'question_sha256': audit['question_sha256'],
            'approved': approved, 'overall': deepcopy(overall), 'gaps': checked,
            'gap_review_verified': approved, 'semantic_coverage_verified': False,
            'judgment_basis': 'explicit_human_separator_review_not_semantic_proof'}
