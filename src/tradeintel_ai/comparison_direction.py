"""Conservative, amount-free check of explicit endpoint direction.

This is a bounded grammar, not a general natural-language verifier. Unknown
or conflicting wording must be clarified; never rewrite a model's proposal.
"""
import re


class ComparisonDirectionError(ValueError):
    pass


MONTH = r'(?<![\d-])\d{4}-(?:0[1-9]|1[0-2])(?![\d-])'
PATTERNS = [
    re.compile(rf'以\s*(?P<reference>{MONTH})\s*为基准[，,\s]*比较\s*(?P<current>{MONTH})'),
    re.compile(rf'(?:比较\s*)?(?P<current>{MONTH})\s*(?:相对于|相对|相比于|比)\s*(?P<reference>{MONTH})'),
]
GUIDANCE = '请明确写出“以YYYY-MM为基准，比较YYYY-MM”，并检查基准月和比较月；尚未执行。'


def check_endpoint_direction(candidate, question):
    comparison = candidate.get('comparison') or {}
    if candidate.get('status') != 'plan' or comparison.get('kind') != 'endpoint':
        return
    quote = (candidate.get('evidence') or {}).get('trade.comparison', '')
    matches = [p.fullmatch(quote.strip()) for p in PATTERNS]
    pairs = {(m['reference'], m['current']) for m in matches if m}
    if quote not in question or len(pairs) != 1:
        raise ComparisonDirectionError('目前不能可靠核对这句比较方向。' + GUIDANCE)
    # Do not accept a correct-looking substring from a negation, example, or
    # competing direction elsewhere in the request. Conservative rejection is
    # preferable to treating a partial match as proof of intent.
    all_pairs = {(m['reference'], m['current']) for p in PATTERNS for m in p.finditer(question)}
    if all_pairs != pairs or re.search(r'不要|不是|并非|而非|别|不比|不以|不按|不能|不应|无需|不需要|忽略|例如|比如|示例', question):
        raise ComparisonDirectionError('比较表述有冲突、否定或示例，不能直接确定方向。' + GUIDANCE)
    proposed = (comparison.get('reference_month'), comparison.get('current_month'))
    if proposed not in pairs:
        raise ComparisonDirectionError('模型提出的基准月/比较月与原话不一致。' + GUIDANCE)
