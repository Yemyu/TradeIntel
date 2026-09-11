"""Proposed read-only capability contract; not registered in frozen v2.1.

Input is an explicit structured request, not natural-language intent. This module
does not query trade amounts, execute operations or assert task completion.
"""
import hashlib
from pathlib import Path

from .agent import MODEL_TOOL_NAMES
from .evidence_v21 import EvidenceRegistryV21
from .tools import DATA_START, DATA_END, _month_key, ToolError

ROOT=Path(__file__).resolve().parents[2]


def source(relative):
    return {'kind':'implementation_contract','path':relative,
            'sha256':hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()}


def describe_capabilities(repository=None):
    registry=EvidenceRegistryV21(repository)
    schemas={s['name']:s for s in registry.schemas() if s['name'] in MODEL_TOOL_NAMES}
    trade=schemas['get_trade_series']['parameters']['properties']
    readiness=registry.call('get_causal_readiness',{})
    known=(readiness.get('status')=='ok' and
           type(readiness.get('data',{}).get('causal_allowed')) is bool and
           readiness['data'].get('status') not in (None,'','unknown'))
    return {'contract_version':'proposal-1','backend':'verified_csv_artifacts',
            'policies':['us_301_list1_2018'],'importer':'United States',
            'available_months':{'start':f'{DATA_START[0]:04d}-{DATA_START[1]:02d}',
                                'end':f'{DATA_END[0]:04d}-{DATA_END[1]:02d}'},
            'origins':trade['origin']['enum'],
            'granularities':['policy_aggregate','hs6_2017'],
            'metrics':['import_value_consumption_usd'],
            'allowed_operations':['read'],'model_tools':sorted(schemas),
            'causal_status':readiness['data']['status'] if known else 'unknown',
            'causal_allowed':readiness['data']['causal_allowed'] if known else False,
            'causal_status_verified':known,
            'sources':[source('src/tradeintel_ai/tools.py'),source('src/tradeintel_ai/agent.py'),
                       source('src/tradeintel_ai/evidence_v21.py'),source('src/tradeintel_ai/capability_contract.py')]
                      + (readiness.get('evidence',{}).get('sources',[]) if known else []),
            'limitation':'This describes the frozen application tools, not every dataset or the assistant computer permissions.'}


def assess_trade_request(request, repository=None):
    """Validate an explicit import request without silently substituting scope."""
    required={'policy_id','operation','metric','origin','granularity','months','hs6','causal_effect'}
    if not isinstance(request,dict) or set(request)!=required:
        return {'status':'needs_clarification','reason':'请求必须明确给出全部登记字段，且不得附加未登记字段',
                'required_fields':sorted(required),'executed':False,'intent_verified':False}
    text_fields=required-{'months','hs6','causal_effect'}
    if (any(not isinstance(request[k],str) or not request[k] for k in text_fields)
            or type(request['causal_effect']) is not bool
            or request['hs6'] is not None and not isinstance(request['hs6'],str)):
        return {'status':'needs_clarification','reason':'字段类型或空值不符合约定','executed':False,'intent_verified':False}
    months=request['months']
    if not isinstance(months,list) or not 1<=len(months)<=48:
        return {'status':'needs_clarification','reason':'月份列表应包含1至48个明确月份','executed':False,'intent_verified':False}
    try:
        for month in months:_month_key(month)
        if len(set(months))!=len(months):raise ToolError('重复月份')
    except (ToolError,TypeError):
        return {'status':'needs_clarification','reason':'月份无效或重复','executed':False,'intent_verified':False}
    capabilities=describe_capabilities(repository)
    reasons=[]
    for key,allowed,message in (
        ('policy_id',capabilities['policies'],'当前只支持登记的Section 301 List 1政策范围'),
        ('operation',capabilities['allowed_operations'],'当前应用工具只读，不能执行删除或写入操作'),
        ('metric',capabilities['metrics'],'当前贸易工具提供美元进口额，不提供GDP或失业率'),
        ('origin',capabilities['origins'],'当前工具仅支持中国、其他原产地整体及全部原产地，不能替代单独国家'),
        ('granularity',capabilities['granularities'],'当前贸易工具支持政策整体或HS6_2017商品，不提供企业名单或企业金额')):
        if request[key] not in allowed:reasons.append({'field':key,'reason':message})
    if request['granularity']=='hs6_2017':
        hs6=request['hs6']
        if not hs6 or not hs6.isascii() or not hs6.isdigit() or len(hs6)!=6:
            reasons.append({'field':'hs6','reason':'HS6查询需要明确的六位商品编码'})
        elif request['policy_id'] in capabilities['policies']:
            registry=EvidenceRegistryV21(repository)
            if hs6 not in registry.repository.policy_hs6(request['policy_id']):
                reasons.append({'field':'hs6','reason':'商品不在登记的政策暴露范围内'})
    elif request['hs6'] is not None:
        reasons.append({'field':'hs6','reason':'整体范围与指定HS6不能混用'})
    available=[m for m in months if DATA_START<=_month_key(m)<=DATA_END]
    unavailable=[m for m in months if m not in available]
    if request['causal_effect'] and not capabilities['causal_allowed']:
        reasons.append({'field':'causal_effect','reason':'当前证据不允许关税因果效果；可以另行请求描述性金额'})
    if reasons:status='unsupported_request'
    elif not available:status='outside_coverage'
    elif unavailable:status='partially_in_coverage'
    else:status='within_declared_capability'
    return {'status':status,'reasons':reasons,'requested_months':list(months),
            'months_in_declared_coverage':available,'months_outside_declared_coverage':unavailable,
            'operation_allowed':request['operation']=='read','executed':False,'intent_verified':False,
            'data_observed':False,'task_success_verified':False,'capabilities':capabilities,
            'limitation':'Months in coverage do not guarantee observed values; no amounts have been queried. Unsupported scope is never automatically substituted.'}
