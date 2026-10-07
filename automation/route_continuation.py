"""Plan virtual half-boundary continuation without changing the real board."""
from pathlib import Path
from .common import atomic_json
from .route_search import RouteSearch, identity


def link_continuation(directory,catalog,config,node_limit=2000):
    continuation_config={**config,'initial_prefix':[[config['target']//2,1,False]]}
    search=RouteSearch(Path(directory)/'continuation',catalog,node_limit=node_limit,**continuation_config)
    try:continuation=search.plan()
    finally:search.close()
    path=Path(directory)/'route-plan.json'
    import json
    plan=json.loads(path.read_text(encoding='utf-8'))
    plan['continuationPlan']={k:v for k,v in continuation.items() if k!='routes'}
    if continuation['routes']:
        chosen=min(continuation['routes'],key=lambda r:r['metrics']['expectedTotalDrops'])
        for route in plan['routes']:
            route['continuation']=chosen
            route['id']=identity({'steps':route['steps'],'continuation':chosen,'target':route['target'],'cells':route['cells']})
    requirements={identity(r):r for r in [*plan['requirements'],*continuation['requirements']]}
    plan['requirements']=list(requirements.values())
    plan['missing']=[*plan['missing'],*continuation['missing']]
    atomic_json(path,plan)
    return plan
