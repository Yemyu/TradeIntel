"""Conservative host routing before any model call or version lookup."""
import re
from .policy_cases import CASES

FIRST = 'us_301_review2025_tungsten_solar'
SECOND = 'us_301_solar2024'
CODES = {
    FIRST: {'28046100', '38180000', '81019400', '81019910', '81019980'},
    SECOND: {'85414200', '85414300'},
}


def select_business_case(question, selected=None):
    if selected is not None and (not isinstance(selected, str) or selected not in CASES):
        return None, 'unsupported', '所选政策案例未登记，不能改用其他政策的数据。'
    mentioned = set(re.findall(r'(?<![\d.])\d{4}\.?\d{2}\.?\d{2}(?![\d.])', question))
    mentioned = {code.replace('.', '') for code in mentioned}
    signals = {key for key, codes in CODES.items() if codes & mentioned or key in question}
    if '2024-21217' in question or re.search(r'光伏电池|太阳能电池|光伏组件', question):
        signals.add(SECOND)
    if re.search(r'多晶硅|硅片|钨', question):
        signals.add(FIRST)
    if len(signals) > 1 or (selected is not None and signals and selected not in signals):
        return None, 'clarify', '问题包含不同政策案例或与所选案例冲突，请一次明确一个案例：2024年光伏电池/组件，还是2025年钨/硅片/多晶硅？'
    if selected is None and not signals and re.search(r'光伏|太阳能|solar', question, re.I):
        return None, 'clarify', '你指2024年光伏电池/组件政策，还是2025年硅片/多晶硅政策？请明确案例或八位税号。'
    policy_id = selected or next(iter(signals), FIRST)
    if CASES[policy_id].status != 'enabled':
        return policy_id, 'unsupported', '2024年光伏电池/组件案例仍在验收，尚未开放问答；不会改用2025年硅片或钨的数据。'
    return policy_id, None, None
