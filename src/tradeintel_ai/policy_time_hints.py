"""Source-bound clock notation hints, not policy facts or timezone conversion."""
from copy import deepcopy
import re


_CLOCK = re.compile(
    r'(?<![\w:])(?P<hour>0?[1-9]|1[0-2]):(?P<minute>[0-5][0-9])'
    r'\s*(?P<period>[ap])\.?\s*m\b\.?', re.IGNORECASE)


def annotate_clock_times(evidence):
    """Keep original text/IDs; derive hints only from exact matched source spans.

    No inferred date, timezone, applicability or claim approval. A midnight
    clock is still on the stated date; this function never adjusts dates.
    Supplied annotations are not trusted and are always rebuilt from text.
    """
    result = deepcopy(evidence)
    for row in result:
        row.pop('derived_clock_hints', None)
        text = row.get('text')
        if not isinstance(text, str):
            continue
        hints = []
        for match in _CLOCK.finditer(text):
            hour = int(match['hour']) % 12
            if match['period'].lower() == 'p':
                hour += 12
            hints.append({
                'source_id': row.get('id'),
                'start': match.start(), 'end': match.end(),
                'source_quote': match.group(),
                'clock_24h': f"{hour:02d}:{match['minute']}",
                'rule': '12hour-to-24hour-v1',
                'timezone_conversion': False,
            })
        if hints:
            row['derived_clock_hints'] = hints
    return result
