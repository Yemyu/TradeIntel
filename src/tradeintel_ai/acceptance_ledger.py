"""At-most-once ledger for the frozen research-plan acceptance batch."""
from collections import Counter
from copy import deepcopy


class AcceptanceLedger:
    """Record every planned question without hiding failures or omissions."""

    def __init__(self, question_ids, *, max_planning=None, max_answers=None):
        ids = list(question_ids)
        if not ids or len(set(ids)) != len(ids):
            raise ValueError('question IDs must be non-empty and unique')
        self.question_ids = tuple(ids)
        self.max_planning = max_planning if max_planning is not None else len(ids)
        self.max_answers = max_answers if max_answers is not None else len(ids)
        self.records = []
        self.stop_reason = None

    @property
    def planning_calls(self):
        return sum(int(record['planning_calls']) for record in self.records)

    @property
    def answer_calls(self):
        return sum(int(record['answer_attempted']) for record in self.records)

    @property
    def total_calls(self):
        return self.planning_calls + self.answer_calls

    def stop(self, reason):
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError('stop reason is required')
        self.stop_reason = reason

    def record(self, question_id, *, terminal_status, expected_status,
               planning_calls=1, answer_attempted=False, detail=None):
        if self.stop_reason:
            raise RuntimeError('ledger is stopped')
        if question_id not in self.question_ids:
            raise ValueError('question is not in the frozen set')
        if any(record['id'] == question_id for record in self.records):
            raise ValueError('question already recorded')
        if planning_calls not in (0, 1) or type(answer_attempted) is not bool:
            raise ValueError('invalid call counts')
        if self.planning_calls + planning_calls > self.max_planning:
            raise ValueError('planning budget exceeded')
        if self.answer_calls + int(answer_attempted) > self.max_answers:
            raise ValueError('answer budget exceeded')
        record = {
            'id': question_id, 'terminal_status': terminal_status,
            'expected_status': expected_status, 'planning_calls': planning_calls,
            'answer_attempted': answer_attempted, 'detail': deepcopy(detail or {}),
        }
        self.records.append(record)
        return deepcopy(record)

    def summary(self):
        terminal_counts = Counter(record['terminal_status'] for record in self.records)
        expected_counts = Counter(record['expected_status'] for record in self.records)
        finished = len(self.records) == len(self.question_ids)
        return {
            'planned_questions': len(self.question_ids),
            'recorded_questions': len(self.records),
            'remaining_questions': len(self.question_ids) - len(self.records),
            'planning_calls': self.planning_calls,
            'answer_calls': self.answer_calls,
            'total_model_calls': self.total_calls,
            'terminal_status_counts': dict(sorted(terminal_counts.items())),
            'expected_status_counts': dict(sorted(expected_counts.items())),
            'status': 'stopped' if self.stop_reason else 'collected' if finished else 'running',
            'stop_reason': self.stop_reason,
        }
