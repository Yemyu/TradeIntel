"""Narrow syntax compatibility; never repair request values or quoted evidence."""
from dataclasses import replace
import json
import re
from .agent import _normalise_response
from .intent_proposal import _pairs, _constant


def normalize_response(raw):
    response=_normalise_response(raw)
    if response.tool_calls or response.metadata.get('finish_reason')!='stop' or len(response.text)>24000:
        return response, []
    text=response.text
    fence=re.fullmatch(r'\s*```(?:json)?[ \t]*\r?\n([\s\S]*?)\r?\n```\s*',text,re.IGNORECASE)
    candidate_text=fence.group(1) if fence else text
    try:
        obj=json.loads(candidate_text,object_pairs_hook=_pairs,parse_constant=_constant)
    except (ValueError,RecursionError):return response,[]
    if not isinstance(obj,dict):return response,[]
    changes=['whole_json_fence_removed'] if fence else []
    req=obj.get('request');evidence=obj.get('evidence')
    if (isinstance(req,dict) and req.get('task')=='comparison' and isinstance(evidence,dict)
            and 'request.comparison_id' in evidence and 'comparison_id' not in evidence):
        evidence['comparison_id']=evidence.pop('request.comparison_id')
        changes.append('comparison_evidence_path_alias')
    if not changes:return response,[]
    return replace(response,text=json.dumps(obj,ensure_ascii=False)),changes
