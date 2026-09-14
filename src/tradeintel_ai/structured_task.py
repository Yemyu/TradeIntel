"""Explicit user-selected scope; not an LLM plan or natural-language score."""
import re


def compile_task(task):
    if not isinstance(task,dict) or set(task)!={'policy_id','month','product','task'}:
        raise ValueError('structured task requires policy_id/month/product/task')
    if task['policy_id']!='us_301_solar2024' or task['task']!='source_and_investigation':
        raise ValueError('unsupported structured task')
    month=task['month']
    if not isinstance(month,str) or not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])',month):
        raise ValueError('invalid month')
    product=task['product']
    if not isinstance(product,str) or product not in ('all','85414200','85414300'):
        raise ValueError('explicit supported product required')
    scope='全部登记商品' if product=='all' else '税号'+product
    question=f'请为2024年光伏电池和组件政策的{scope}制作{month}美国消费进口简报，列出全部来源金额、中国原产金额和份额，并提出待核查问题及原因。'
    return question, {'kind':'brief','month':month,'hts8':None if product=='all' else product}
