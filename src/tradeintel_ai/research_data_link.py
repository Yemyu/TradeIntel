"""Link a saved query to its own published data, never the newest version."""
from .exposure_version_store import ExposureVersionStore, VersionStoreError
from .report_update_impact import _read, assess_report


def research_data_link(root, run):
    unknown={'status':'unavailable','url':None,
             'message':'未能核对本次查询的数据版本；不会替换成最新数据。'}
    try:
        if run.is_symlink():return unknown
        state=_read(run/'status.json')
        version=state.get('data_version')
        if not isinstance(version,str):return unknown
        from .policy_cases import resolve_case
        policy_id = state.get('policy_id')
        case = resolve_case(policy_id, require_enabled=False) if policy_id else None
        store=ExposureVersionStore(root, root / case.versions) if case else ExposureVersionStore(root)
        snapshot=store.load_snapshot(version)
        store.release_root(version)
        if assess_report(run,store,snapshot)['status']!='unchanged_scope':return unknown
        path=run/'trade-evidence.json'
        evidence=_read(path if path.exists() else run/'evidence.json')
        data=evidence['data']
        # Check the actual amounts, not only matching version strings.
        for row in data['series']:
            metrics=snapshot['months'][row['month']]['metrics']
            hts=data.get('hts8')
            if hts is not None:
                matches=[p for p in metrics.get('product_breakdown',[]) if p.get('hts8')==hts]
                if len(matches)!=1:return unknown
                metrics=matches[0]
            for field in ('all_origins_value_usd','china_value_usd'):
                if type(row.get(field)) is not int or row[field]!=metrics.get(field):return unknown
        return {'status':'bound','url':'/api/version-report?version='+version + (
                    '&policy_id='+case.policy_id if case and case.policy_id != 'us_301_review2025_tungsten_solar' else ''),
                'data_version':version,'months':data['requested_months'],
                'hts8':data.get('hts8'),
                'message':'本次查询：'+ '、'.join(data['requested_months'])+
                    ('；税号'+str(data['hts8']) if data.get('hts8') else '；登记税号整体')+
                    '。链接展示同一版本的全窗口、全部登记税号背景数据，不扩大本次AI解释范围；版本绑定不等于解释已通过审核。'}
    except (ValueError,OSError,KeyError,TypeError,VersionStoreError):
        return unknown
