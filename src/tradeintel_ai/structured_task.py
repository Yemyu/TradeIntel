"""Explicit user-selected scope; not an LLM plan or natural-language score."""
import re


def compile_task(task):
    base = {'policy_id','month','product','task'}
    if not isinstance(task,dict) or set(task) not in (base, base | {'focus'}, base | {'focus','schema_version','policy_view'}):
        raise ValueError('structured task requires policy_id/month/product/task')
    if 'schema_version' in task and (task['schema_version'] != 'research-request-v2' or task['policy_view'] != 'archived_event'):
        raise ValueError('unsupported request version or policy view')
    focus = task.get('focus', 'contrast')
    if not isinstance(focus, str) or focus not in ('china_amount','china_share','contrast'):
        raise ValueError('unsupported focus')
    cases={'us_301_solar2024':('2024年光伏电池和组件',('85414200','85414300')),
           'us_301_review2025_tungsten_solar':('2025年钨、硅片及多晶硅',('28046100','38180000','81019400','81019910','81019980'))}
    if (not isinstance(task['policy_id'],str) or task['policy_id'] not in cases
            or task['task'] not in ('source_and_investigation', 'monthly_exposure')):
        raise ValueError('unsupported structured task')
    month=task['month']
    if not isinstance(month,str) or not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])',month):
        raise ValueError('invalid month')
    product=task['product']
    label,codes=cases[task['policy_id']]
    if not isinstance(product,str) or product not in ('all',*codes):
        raise ValueError('explicit supported product required')
    scope='全部登记商品' if product=='all' else '税号'+product
    if task['task'] == 'monthly_exposure':
        instruction = {'china_amount':'重点解释中国原产金额及其在本次范围中的规模。',
                       'china_share':'重点解释中国来源占该商品美国全部来源进口的比例。',
                       'contrast':'比较中国原产金额与中国来源占该商品美国进口的比例，解释两种关注角度的区别。'}[focus]
        question=(f'请为{label}政策的{scope}制作{month}美国消费进口研究简报，'
                  + instruction)
    else:
        question=f'请为{label}政策的{scope}制作{month}美国消费进口简报，列出全部来源金额、中国原产金额和份额，并提出待核查问题及原因。'
    return question, {'kind':'brief','month':month,'hts8':None if product=='all' else product}
