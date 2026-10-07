"""Continue from the ordinary40 produced by the verified real opening."""
from .route_runtime import RouteExecutor


def bind40(executor, obs):
    indices=[i for i,t in enumerate(obs['tower']) if t['kind']=='tile' and t['value']==40]
    if not indices:
        raise ValueError('Opening did not produce ordinary40')
    # The anchor can be inside the tower: keep every real residual on both sides.
    executor.reset()
    executor.fixed_ids={obs['tower'][indices[0]]['id']}
    executor.initial_bound=True
    executor._contract(obs,executor.route['initialPrefix'])
