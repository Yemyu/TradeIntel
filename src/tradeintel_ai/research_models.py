"""Explicit research generation limits; separate from historical adapters."""
from .model_adapter import OpenAICompatibleModel


class ResearchPlannerModel(OpenAICompatibleModel):
    max_output_tokens = 1536
    stage = 'planning'

    def _payload(self, *, messages, tools):
        payload = super()._payload(messages=messages, tools=tools)
        payload.update(max_tokens=self.max_output_tokens,
                       thinking={'type': 'disabled'}, stream=False)
        return payload

    def effective_request_settings(self):
        # This is the same payload builder used by complete(), with no user
        # messages or credentials. Capture generation settings only.
        payload = self._payload(messages=[], tools=[])
        return {key: payload[key] for key in
                ('model', 'temperature', 'max_tokens', 'thinking', 'stream')}


class ResearchPolicyModel(ResearchPlannerModel):
    max_output_tokens = 768
    stage = 'policy_generation'
