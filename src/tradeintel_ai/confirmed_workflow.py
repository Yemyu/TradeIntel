"""Local, single-user confirmation boundary. Not a remote authentication system."""
from copy import deepcopy
import secrets
from .intent_presentation import propose_presented
from .structured_workflow import execute_request
from .evidence_v21 import EvidenceRegistryV21


class ConfirmedWorkflow:
    def __init__(self, model, registry=None):
        self.model = model
        self.registry = registry or EvidenceRegistryV21()
        self._pending = None

    def propose(self, question):
        self._pending = None
        preview = propose_presented(question, self.model, repository=self.registry.repository)
        if preview['status'] == 'needs_confirmation' and preview['parse_outcome'] == 'validated_proposal':
            token = secrets.token_urlsafe(24)
            self._pending = (token, deepcopy(preview['request']))
            preview['confirmation_token'] = token
        return deepcopy(preview)

    def cancel(self):
        self._pending = None
        return {'status':'cancelled', 'user_confirmed':False, 'execution_attempted':False}

    def confirm(self, token):
        if self._pending is None or not isinstance(token, str) or token != self._pending[0]:
            return {'status':'confirmation_rejected', 'user_confirmed':False, 'execution_attempted':False,
                    'response':'确认无效或已失效，请重新查看需求预览。'}
        _, request = self._pending
        self._pending = None  # consume before execution, including failed execution
        result = execute_request(deepcopy(request), self.registry)
        result.update(user_confirmed=True, execution_attempted=True, confirmed_request=request,
                      confirmation_scope='local_single_user_process')
        return result
