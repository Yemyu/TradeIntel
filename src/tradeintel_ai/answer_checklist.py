"""Independent reviewer records. Structural validation is not semantic proof."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from .quote_gap_audit import digest_audit, validate_gap_review

CHECKLIST_PATH = Path(__file__).resolve().parents[2] / 'docs/evaluation/development-checklist-0093.json'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def at(value, path):
    if not isinstance(path, list) or not path:
        raise ValueError('nonempty artifact path required')
    for part in path:
        if isinstance(value, list) and type(part) is int and 0 <= part < len(value):
            value = value[part]
        elif isinstance(value, dict) and isinstance(part, str) and part in value:
            value = value[part]
        else:
            raise ValueError('artifact path does not exist')
    return value


def load_checklists(cases):
    data = json.loads(CHECKLIST_PATH.read_text())
    if data.get('version') != 'answer-checklist-0093' or set(data['cases']) != {c['id'] for c in cases}:
        raise ValueError('checklist case version mismatch')
    for case in cases:
        rows = data['cases'][case['id']]
        ids = [r['id'] for r in rows]
        if not rows or len(ids) != len(set(ids)):
            raise ValueError('duplicate or empty checklist')
        for row in rows:
            if any(not isinstance(row.get(k), str) or not row[k].strip()
                   for k in ('id', 'quote', 'required_answer', 'task', 'expected_disposition')):
                raise ValueError('incomplete checklist')
            if row['quote'] not in case['question'] or row['task'] not in ('policy', 'trade', 'unsupported'):
                raise ValueError('checklist source/task mismatch')
            if row['expected_disposition'] not in ('answer', 'scope_selection'):
                raise ValueError('checklist disposition mismatch')
    return data


def template(packet):
    result = {'packet_sha256': digest(packet), 'overall': {'status': 'unreviewed', 'reason': ''},
            'items': [{'id': r['id'], 'status': 'unreviewed', 'reason': '', 'witnesses': []}
                      for r in packet['checklist']]}
    audit = packet['artifact'].get('gap_audit')
    if packet['stage'] == 'plan' and audit is not None:
        result['gap_review'] = {
            'audit_sha256': digest_audit(audit),
            'overall': {'status': 'unreviewed', 'reason': ''},
            'gaps': [{k: g[k] for k in ('start', 'end', 'quote')} |
                     {'status': 'unreviewed', 'reason': ''}
                     for g in audit['segments'] if g['source'] == 'host_gap' and g['quote'].strip()]}
    return result


def validate_review(packet, submission, reviewer):
    """Fail closed on incomplete records; preserve negative reviews as decisions."""
    if packet.get('stage') not in ('plan', 'answer'):
        raise ValueError('unknown review stage')
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError('explicit reviewer required')
    if not isinstance(submission, dict) or submission.get('packet_sha256') != digest(packet):
        raise ValueError('review packet changed or unbound')
    # Derived evidence hashes belong to the validated record, not the original
    # submission retained for audit and reproducibility.
    submission = deepcopy(submission)
    overall = submission.get('overall', {})
    if (overall.get('status') not in ('pass', 'fail') or not isinstance(overall.get('reason'), str)
            or not overall['reason'].strip()):
        raise ValueError('explicit overall review and reason required')
    entries = submission.get('items')
    checklist = packet['checklist']
    if not isinstance(entries, list) or len(entries) != len(checklist):
        raise ValueError('missing checklist decisions')
    if any(not isinstance(r, dict) for r in entries):
        raise ValueError('invalid decision')
    ids = [r.get('id') for r in entries]
    if any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids) or set(ids) != {r['id'] for r in checklist}:
        raise ValueError('duplicate or unknown decision IDs')
    by_id = {r['id']: r for r in entries}
    approved = overall['status'] == 'pass'
    artifact = packet['artifact']
    for required in checklist:
        row = by_id[required['id']]
        if not isinstance(row.get('reason'), str) or not row['reason'].strip():
            raise ValueError('per-item reason required')
        if packet['stage'] == 'plan':
            allowed = ('covered', 'omitted', 'wrong_scope', 'needs_clarification')
            passing = ('covered',) if required['expected_disposition'] == 'answer' else ('needs_clarification',)
            if required['expected_disposition'] == 'scope_selection' and artifact.get('status') not in ('needs_scope_selection', 'needs_clarification'):
                raise ValueError('unsupported scope cannot execute')
        else:
            allowed, passing = ('supported', 'missing', 'contradicted', 'unverifiable'), ('supported',)
        if row.get('status') not in allowed:
            raise ValueError('unknown review status')
        approved = approved and row['status'] in passing
        if packet['stage'] != 'answer' or row['status'] != 'supported':
            continue
        if required['task'] == 'policy':
            witnesses = row.get('witnesses')
            if not isinstance(witnesses, list) or not witnesses:
                raise ValueError('supported policy needs claim and evidence witnesses')
            claims = artifact['policy']['generation']['claims']
            hits = {h['id']: h for h in artifact['policy_evidence']['hits']}
            for witness in witnesses:
                index = witness.get('claim_index')
                if type(index) is not int or not 0 <= index < len(claims):
                    raise ValueError('claim index does not exist')
                claim = claims[index]
                citation = witness.get('citation_id')
                hit = hits.get(citation)
                if hit is None or citation not in claim.get('citations', []):
                    raise ValueError('citation not linked to claim')
                if witness.get('claim_text') != claim['text']:
                    raise ValueError('claim text changed')
                excerpt = witness.get('evidence_excerpt')
                if not isinstance(excerpt, str) or not excerpt.strip() or excerpt not in hit['text']:
                    raise ValueError('evidence excerpt not found')
                witness['evidence_sha256'] = digest(hit)
        elif required['task'] == 'trade':
            checks = required.get('checks', [])
            if not checks or row.get('checks') != checks:
                raise ValueError('all frozen trade checks must be recorded')
            for check in checks:
                actual = at(artifact, check['path'])
                if type(actual) is not type(check['expected']) or actual != check['expected']:
                    raise ValueError('trade result differs from frozen reference')
        else:
            raise ValueError('unsupported task cannot have supported answer')
    gap_review = None
    if packet['stage'] == 'plan' and artifact.get('gap_audit') is not None:
        gap_review = validate_gap_review(artifact['gap_audit'], submission.get('gap_review'), reviewer)
        approved = approved and gap_review['approved']
    result = {'version': 'checklist-review-0093', 'reviewer': reviewer,
            'packet_sha256': digest(packet), 'question_sha256': digest(packet['case']['question']),
            'checklist_sha256': digest(checklist), 'artifact_sha256': digest(artifact),
            'files': deepcopy(packet['files']), 'stage': packet['stage'],
            'approved': approved, 'semantic_coverage_verified': False,
            'conclusion': ('reviewer_supported' if packet['stage'] == 'answer' else 'reviewer_plan_covered') if approved else 'not_approved',
            'judgment_basis': 'external_reviewer_not_automatic_semantic_proof',
            'overall': deepcopy(overall), 'items': deepcopy(entries)}
    if gap_review is not None:
        result['gap_review'] = gap_review
    return result


def file_hashes(directory):
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(directory).rglob('*')) if p.is_file()}


def unchanged(hashes):
    return all(Path(p).is_file() and hashlib.sha256(Path(p).read_bytes()).hexdigest() == h
               for p, h in hashes.items())
