"""Durable, fail-closed experiment slots. Never retries an uncertain attempt."""
from contextlib import contextmanager
from dataclasses import asdict
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile


class ExperimentBlocked(ValueError):
    pass


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class G2Ledger:
    def __init__(self, preparation, directory):
        self.preparation = Path(preparation).resolve()
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.manifest = json.loads((self.preparation/'manifest.json').read_text())
        self.manifest_hash = digest((self.preparation/'manifest.json').read_bytes())
        inherited=self.manifest.get('revision',{}).get('inherited_attempts',0)
        if self.manifest['over_budget'] or len(self.manifest['schedule']) + inherited != 12:
            raise ExperimentBlocked('invalid frozen budget')
        if inherited:
            self.verify_parent(register=True)

    def verify_parent(self, *, register=False):
        revision=self.manifest.get('revision')
        if not revision: return
        if revision.get('number')!=1 or revision.get('inherited_attempts')!=1:
            raise ExperimentBlocked('unsupported revision')
        parent=Path(revision['parent_preparation']).resolve()
        parent_manifest=json.loads((parent/'manifest.json').read_text())
        state=json.loads((parent/'execution-ledger/state.json').read_text())
        if (parent_manifest.get('revision') or digest((parent/'manifest.json').read_bytes())!=revision['parent_manifest_sha256']
            or digest((parent/'execution-ledger/state.json').read_bytes())!=revision['parent_state_sha256']
            or len(state['attempts'])!=1 or state['attempts'][0].get('review',{}).get('decision')!='stop'
            or [(s['id'],s['arm']) for s in self.manifest['schedule']] !=
               [(s['id'],s['arm']) for s in parent_manifest['schedule'][1:]]):
            raise ExperimentBlocked('parent stop or budget lineage changed')
        marker=parent/'execution-ledger/revision-successor.json'
        binding={'preparation':str(self.preparation),'manifest_sha256':self.manifest_hash}
        with (parent/'execution-ledger/lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            if not marker.exists() and register:
                with marker.open('x') as stream:
                    json.dump(binding,stream);stream.flush();os.fsync(stream.fileno())
            if not marker.exists() or json.loads(marker.read_text())!=binding:
                raise ExperimentBlocked('a different revision is already registered')

    @contextmanager
    def locked(self):
        with (self.directory/'lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try: yield
            finally: fcntl.flock(lock, fcntl.LOCK_UN)

    def save(self, state):
        fd, name = tempfile.mkstemp(prefix='.state-', dir=self.directory)
        try:
            with os.fdopen(fd,'w') as stream:
                json.dump(state, stream, ensure_ascii=False, indent=2)
                stream.flush(); os.fsync(stream.fileno())
            os.replace(name, self.directory/'state.json')
        finally:
            if os.path.exists(name): os.unlink(name)

    def state(self):
        path = self.directory/'state.json'
        state = json.loads(path.read_text()) if path.exists() else {
            'manifest_sha256':self.manifest_hash,'attempts':[]}
        if state['manifest_sha256'] != self.manifest_hash:
            raise ExperimentBlocked('ledger belongs to another preparation')
        return state

    def verify(self):
        self.verify_parent()
        if digest((self.preparation/'manifest.json').read_bytes()) != self.manifest_hash:
            raise ExperimentBlocked('manifest changed')
        for relative, expected in self.manifest['files_sha256'].items():
            path = (self.preparation/relative).resolve()
            if not path.is_relative_to(self.preparation) or digest(path.read_bytes()) != expected:
                raise ExperimentBlocked('frozen input changed')
        root=Path(__file__).resolve().parents[2]
        for relative, expected in self.manifest.get('code_sha256',{}).items():
            path=(root/relative).resolve()
            if not path.is_relative_to(root) or digest(path.read_bytes())!=expected:
                raise ExperimentBlocked('code differs from preparation; do not reuse old freeze')

    def run(self, slot, model):
        """One provider call. Previous result needs an explicit content review."""
        from .agent import _normalise_response
        from scripts.freeze_g2_research import estimate_tokens
        with self.locked():
            self.verify()
            state = self.state()
            attempts = state['attempts']
            if type(slot) is not int or slot != len(attempts) or not 0 <= slot < len(self.manifest['schedule']):
                raise ExperimentBlocked('slot already used or out of order')
            if attempts and attempts[-1].get('review',{}).get('decision') != 'continue':
                raise ExperimentBlocked('previous call uncertain, failed, or not reviewed')
            scheduled = self.manifest['schedule'][slot]
            relative = (f"{scheduled['id']}.messages.json" if scheduled['arm']=='planning'
                        else f"{scheduled['id']}/{scheduled['arm']}.messages.json")
            messages = json.loads((self.preparation/relative).read_text())
            payload = model._payload(messages=messages,tools=[])
            expected = {'model':'glm-4.7','temperature':0,'max_tokens':2000,
                        'thinking':{'type':'disabled'},'stream':False}
            if any(payload.get(k)!=v for k,v in expected.items()) or model.config.timeout_seconds != 90:
                raise ExperimentBlocked('provider settings differ from protocol')
            if payload.get('messages') != messages or estimate_tokens(messages)>8000:
                raise ExperimentBlocked('message bytes or budget changed')
            expected_format = None if scheduled['arm']=='B' else {'type':'json_object'}
            if payload.get('response_format') != expected_format:
                raise ExperimentBlocked('wrong response mode for arm')
            attempt = {'slot':slot, **scheduled,'status':'started', 'usage':None,
                       'messages_sha256':digest((self.preparation/relative).read_bytes()),
                       'request_payload':payload,
                       'settings':expected, 'timeout_seconds':90}
            attempts.append(attempt)
            self.save(state)  # durable reservation BEFORE any external action
        try:
            response = _normalise_response(model.complete(messages=messages,tools=[]))
            raw = json.dumps(asdict(response), ensure_ascii=False)
            secret = model.config.api_key
            if secret: raw = raw.replace(secret,'[REDACTED]')
            with self.locked():
                state = self.state(); attempt=state['attempts'][slot]
                attempt['response'] = json.loads(raw)
                attempt['usage'] = response.metadata.get('usage') or None
                attempt['status'] = ('response_received' if not response.tool_calls and
                    response.metadata.get('finish_reason')=='stop' else 'failed_response')
                self.save(state)
            return response
        except Exception as exc:
            with self.locked():
                state=self.state()
                state['attempts'][slot].update(status='failed_or_uncertain',error_type=type(exc).__name__)
                self.save(state)
            raise ExperimentBlocked('request failed; slot retained, no retry') from None

    def review(self, slot, *, decision, reason, reviewer):
        if decision not in {'continue','stop'} or not reason.strip() or not reviewer.strip():
            raise ExperimentBlocked('explicit reason and reviewer required')
        with self.locked():
            self.verify(); state=self.state()
            if slot != len(state['attempts'])-1 or slot < 0:
                raise ExperimentBlocked('review only the latest attempt')
            attempt=state['attempts'][slot]
            if attempt['status']!='response_received' or 'review' in attempt:
                raise ExperimentBlocked('cannot approve failed/uncertain or rewrite a review')
            attempt['review']={'decision':decision,'reason':reason,'reviewer':reviewer,
                               'kind':'developer_experiment_review_not_user_approval'}
            self.save(state)


def protocol_provider(config, arm):
    from dataclasses import replace
    from .research_models import ResearchPlannerModel, JsonResearchModel
    base=ResearchPlannerModel if arm=='B' else JsonResearchModel
    class ProtocolModel(base):
        max_output_tokens=2000
    return ProtocolModel(replace(config,model='glm-4.7',temperature=0,timeout_seconds=90))


class FrozenWebModel:
    """Verify ordinary workflow evidence, then send the frozen C messages."""
    def __init__(self, ledger, slot, provider):
        self.ledger,self.slot,self.provider=ledger,slot,provider

    def complete(self, *, messages, tools):
        scheduled=self.ledger.manifest['schedule'][self.slot]
        if scheduled['arm']!='C' or tools:
            raise ExperimentBlocked('web experiment requires one C slot')
        original=json.loads((self.ledger.preparation/scheduled['id']/'unpacked-information.json').read_text())
        if len(messages)!=2 or json.loads(messages[1]['content'])!=original:
            raise ExperimentBlocked('web task/evidence differs from frozen input')
        return self.ledger.run(self.slot,self.provider)
