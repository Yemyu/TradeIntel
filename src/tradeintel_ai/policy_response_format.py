"""Syntax-only policy response wrapper; never edit claims or evidence IDs."""
from dataclasses import replace
import json
import re


def _pairs(items):
    result={}
    for key,value in items:
        if key in result: raise ValueError('duplicate_json_key')
        result[key]=value
    return result


def _constant(value):
    raise ValueError('nonstandard_json_constant')


def normalize_policy_response(response):
    if response.tool_calls:
        return response
    if response.metadata.get('finish_reason')=='length' or len(response.text)>24000:
        return replace(response,text='')
    fence=re.fullmatch(r'\s*```(?:json)?[ \t]*\r?\n([\s\S]*?)\r?\n```\s*',response.text,re.I)
    candidate=fence.group(1) if fence else response.text
    try:
        value=json.loads(candidate,object_pairs_hook=_pairs,parse_constant=_constant)
    except (ValueError,RecursionError):
        # Prevent the downstream permissive parser from accepting duplicate keys.
        return replace(response,text='')
    if not isinstance(value,dict): return replace(response,text='')
    return replace(response,text=candidate,
        metadata={**response.metadata,'policy_format_changes':['whole_json_fence_removed'] if fence else []})


class PolicyFormattingModel:
    def __init__(self,model): self.model=model
    def complete(self,**kwargs):
        return normalize_policy_response(self.model.complete(**kwargs))
