"""Explicit single-slot G2 runner; never loops, retries, or auto-approves."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from tradeintel_ai.g2_ledger import G2Ledger, FrozenWebModel, ExperimentBlocked, protocol_provider


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preparation',type=Path,required=True)
    parser.add_argument('action',choices=['status','call','review','serve'])
    parser.add_argument('--slot',type=int)
    parser.add_argument('--live',action='store_true',help='Explicitly enable provider access for call/serve')
    parser.add_argument('--decision',choices=['continue','stop'])
    parser.add_argument('--reason')
    parser.add_argument('--reviewer')
    parser.add_argument('--port',type=int,default=8767)
    args=parser.parse_args()
    # One canonical ledger per prepared package, not a caller-selected reset.
    ledger=G2Ledger(args.preparation,args.preparation/'execution-ledger')
    ledger.verify()
    if args.action=='status':
        state=ledger.state()
        inherited=ledger.manifest.get('revision',{}).get('inherited_attempts',0)
        print(json.dumps({'attempts':[{'slot':a['slot'],'status':a['status'],'usage':a.get('usage'),
            'review':a.get('review')} for a in state['attempts']], 'limit':12,
            'inherited_attempts':inherited,'used_total':inherited+len(state['attempts']),
            'remaining':12-inherited-len(state['attempts'])},ensure_ascii=False,indent=2))
        return
    if args.slot is None or not 0<=args.slot<12:
        parser.error('--slot must be 0..11')
    if args.action=='review':
        if not all((args.decision,args.reason,args.reviewer)):
            parser.error('review requires --decision, --reason and --reviewer')
        ledger.review(args.slot,decision=args.decision,reason=args.reason,reviewer=args.reviewer)
        print('Review recorded; no provider call.')
        return
    if not args.live:
        parser.error('call/serve requires --live; no credentials loaded')
    schedule=ledger.manifest['schedule'][args.slot]
    if args.action=='serve' and (schedule['arm']!='C' or schedule['id']!='primary_all'):
        raise ExperimentBlocked('the single planned browser slot is primary_all C')
    from tradeintel_ai.local_provider_config import load_config
    config=load_config()
    if not config.api_key:
        raise ExperimentBlocked('local provider credential unavailable')
    if args.action=='call':
        if schedule['id']=='primary_all' and schedule['arm']=='C':
            raise ExperimentBlocked('reserved browser slot cannot be consumed by CLI')
        ledger.run(args.slot,protocol_provider(config,schedule['arm']))
        print('Attempt saved. Review recorded evidence before any next request.')
    else:
        from tradeintel_ai.web_app import create_server
        def factory(unused_config, task):
            return FrozenWebModel(ledger,args.slot,protocol_provider(config,'C'))
        server=create_server(root=ROOT,host='127.0.0.1',port=args.port,
            output_root=args.preparation/'web-runs',structured_model_factory=factory)
        print(f'Local experiment: http://127.0.0.1:{server.server_port}; one frozen C slot only.',flush=True)
        try: server.serve_forever()
        finally: server.server_close()


if __name__=='__main__':
    try: main()
    except ExperimentBlocked as exc:
        print(str(exc),file=sys.stderr)
        raise SystemExit(2)
