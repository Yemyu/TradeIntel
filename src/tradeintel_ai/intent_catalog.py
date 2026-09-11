"""Explicit domain task meanings; same candidate validator and confirmation gate."""
from copy import deepcopy
from .intent_repair import PROMPT, propose_repaired

CATALOG = PROMPT + '''

业务任务词典（用于理解用户语言，不要求用户使用英文任务名）：
- readiness：本项目是否具备因果分析条件、处理与对照匹配进展、匹配是否通过、
  前趋势检验/事件研究是否已运行、当前能否报告因果效果。只问进度或能否报告，
  都属于readiness，不是要求计算一个新的因果估计。多个相关状态属于同一任务。
- quality：本项目数据质量检查报告，包括总体状态、规则通过/失败/复核数量、
  复核项、覆盖情况。用户同时要求质量状态和规则计数仍是一个quality任务。
- counts：政策清单、合格处理商品和具有足够对照的商品的数量及口径关系。
- policy：登记政策名称、生效日期、税率、政策清单基本信息。
- comparison：已经登记的描述性比较，须指定登记ID。
- trade：查询具体原产地、月份、商品范围的美元进口额。
一个报告的多个属性不等于多个独立任务。只有同时要求不同任务的独立结果，
例如质量报告加贸易金额，才按当前单任务接口要求clarify。
应读取否定后的实际请求；引号中被明确排除执行的内容不是新增任务。
'''


def propose_catalog(question, model):
    class CatalogModel:
        def complete(self, *, messages, tools):
            messages = deepcopy(messages)
            if messages[0] != {'role': 'system', 'content': PROMPT}:
                raise ValueError('unexpected prompt contract')
            messages[0]['content'] = CATALOG
            return model.complete(messages=messages, tools=tools)
    result = propose_repaired(question, CatalogModel())
    result['version'] = 'intent-catalog-1'
    return result
