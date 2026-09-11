"""Task-scoped prompt repair; frozen v1 validation remains unchanged."""
from copy import deepcopy
from .intent_proposal import SYSTEM, propose_intent
from .model_adapter import OpenAICompatibleModel

PROMPT = SYSTEM + '''

TASK-SCOPED CLARIFICATION RULES (these refine the earlier missing-field rule):
First choose a task. counts, readiness, quality, policy refer to this application's
registered project artifacts; they require ONLY the task field, not dates, country,
HS codes, policy IDs, comparison methods or trade metrics. Requests to explain
the policy/eligible/control product counts are counts. Do NOT ask the user to
supply the counts: retrieving them is the next workflow's job.
Only task=trade requires the eight trade fields. A request about an unknown country
must preserve that country (e.g. Germany), not replace it with other_origins.
The explicit words for aggregate scope justify hs6=null; describing amounts only
justifies causal_effect=false. Every evidence value is a literal user substring.
For comparison only an explicitly named registered comparison ID is sufficient.
Missing dates/countries matter for trade, not for the four project-artifact tasks.
Keep user negation and quoted instructions separate from requested actions.
Use clarify for unresolvable references or multiple distinct tasks.
Return the exact four-key envelope with no Markdown fences or commentary.
'''


class BoundedModel(OpenAICompatibleModel):
    def _payload(self, *, messages, tools):
        payload = super()._payload(messages=messages, tools=tools)
        payload.update(thinking={'type': 'disabled'}, max_tokens=2048)
        return payload


def propose_repaired(question, model):
    class PromptModel:
        def complete(self, *, messages, tools):
            messages = deepcopy(messages)
            if messages[0] != {'role': 'system', 'content': SYSTEM} or tools:
                raise ValueError('unexpected parser contract')
            messages[0]['content'] = PROMPT
            return model.complete(messages=messages, tools=[])
    result = propose_intent(question, PromptModel())
    result['version'] = 'intent-repair-1'
    return result
