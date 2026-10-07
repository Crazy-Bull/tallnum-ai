"""Bind six-cell route producers to ordinary single policies only."""
from copy import deepcopy


def use_single_six(route, catalog):
    route, catalog = deepcopy(route), deepcopy(catalog)
    policies = {p['id']: p for p in catalog['policies']}
    changes = []
    for index, step in enumerate(route['steps']):
        if step['kind'] != 'leaf' or step.get('policyCells', 5) != 6:
            continue
        item = policies[step['policy']]
        if step['exit'] == 'single':
            if item['exit'] != 'single':
                raise ValueError('Six-cell single step is bound to a different exit')
            continue
        if step['exit'] != 'match':
            raise ValueError('Six-cell buffer/extend needs an explicit route connection')
        if not step['before'] or step['before'][-1] != [step['target'], 1, False]:
            raise ValueError('Single producer needs an ordinary equal-value connection anchor')
        single = policies.get(item.get('workerKey'))
        if single is None or single.get('exit') != 'single' or single.get('cells') != 6:
            raise ValueError('Missing certified six-cell single producer')
        if single['target'] != step['target'] or not single.get('successNoExtraCombos'):
            raise ValueError('Connection requires the same target and a clean single exit')
        changes.append({'stage': index, 'target': step['target'], 'previousPolicy': step['policy'],
                        'singlePolicy': single['id']})
        step.update(exit='single', policy=single['id'], template=f"6:{step['target']}:single",
                    singleConnectionAfter=deepcopy(step['after']),
                    connection='ordinary-single-then-real-automatic-equal-merge')
    # Match aliases never enter the resulting runtime catalog.
    catalog['policies'] = [p for p in catalog['policies']
                           if p.get('cells') != 6 or p.get('exit') == 'single']
    route['sixCellExecution'] = 'single-only-with-checked-real-connections'
    route['sixCellRebindings'] = changes
    for step in route['steps']:
        if step['kind'] == 'leaf' and step.get('policyCells', 5) == 6:
            if step['exit'] != 'single' or policies[step['policy']]['exit'] != 'single':
                raise ValueError('A six-cell match policy remains in the route')
    return route, catalog
