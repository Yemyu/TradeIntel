"""Opt-in instruction layer and non-mutating presentation review flags.

Flags are advisory, not a factuality classifier or automatic answer repair.
"""
from copy import deepcopy
import re

FOCUS_RULES = '''回答组织规则（不得替代原有证据约束）：
在JSON的claims数组内先写直接回答用户问题的主张，再写使该答案成立的必要适用范围；不要为凑满条数重复事实。
不主动添加用户未问、也不是回答所必需的精确时刻、编码或历史背景。
不能为了简洁遗漏用户明确询问的子问题；需要比较时明确说明差别。
区分政策批次/行动与文件修订：不能因为来源文件名称含“修订”就将第一批或第二批行动叫作修订。
只有原文支持且问题需要时才写时刻。使用清楚的24小时制，保留原文时区/夏令时；不要写有歧义的“上午12点”。不能从本规则推断任何具体政策日期、税率或时刻。
保留原JSON结构与真实证据编号。证据不足仍按原规则处理，不用常识补答案。
最终输出格式：整个消息只能是一个JSON对象，所有回答文字只能放在claims各项的text字段中，引用只能放在对应citations字段中。
“直接回答”指在上述JSON结构内回答，不是在JSON前另写一段答案。不要输出前言、结语、Markdown代码围栏或JSON以外的任何文字。'''


class FocusedPolicyModel:
    """Add instructions only; never rewrite returned model claims."""
    def __init__(self, model): self.model=model
    def complete(self, *, messages, tools):
        updated=deepcopy(list(messages))
        systems=[i for i,m in enumerate(updated) if m.get('role')=='system']
        if len(systems)!=1: raise ValueError('Expected exactly one policy system message')
        index=systems[0]
        updated[index]['content']=str(updated[index]['content'])+'\n\n'+FOCUS_RULES
        return self.model.complete(messages=updated,tools=tools)


def presentation_flags(question, generation):
    flags=[]
    asks_time=bool(re.search(r'几点|时刻|具体时间|精确时间|时分|what time|exact time',question,re.I))
    for index,claim in enumerate(generation.get('claims',[]),1):
        text=claim['text']
        if re.search(r'上午\s*12(?:[:：点时]|\b)',text):
            flags.append({'claim':index,'code':'ambiguous_noon_midnight',
                          'note':'核对原文a.m./p.m.和时区，勿自动替换。'})
        if re.search(r'第[一二三四1234]批修订',text):
            flags.append({'claim':index,'code':'action_amendment_wording',
                          'note':'核对是否将政策批次误称文件修订。'})
        if not asks_time and re.search(r'\d{1,2}[:：]\d{2}',text):
            flags.append({'claim':index,'code':'possibly_unrequested_clock_time',
                          'note':'用户未明确询问精确时刻；检查它是否为必要条件，不自动删除。'})
    return {'flags':flags,'automatic_factuality_verdict':False,'original_claims_unchanged':True}
