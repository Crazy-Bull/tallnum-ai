"""Explicit opening: four six-cell32 exits, three40 exits, Group, EDGE.

Each equal-anchor match reuses the ordinary single policy's actions but
checks the real automatic merge. No synthetic draws or residual clearing.
"""
from copy import deepcopy
from .route_runtime import RouteExecutor
from .runtime import RouteFailure


def build(catalog, protect24=False):
    source={p['target']:p for p in catalog['policies'] if p['exit']=='single' and p.get('cells')==6}
    policies=[]
    for target in (32,40):
        item=source[target]
        if item['maxValue']<48 or not item.get('bootstrapPetsc',{}).get('verified'):
            raise ValueError('Need bound>=48 and two PETSc evaluations for six-cell source')
        if item['bootstrapPetsc'].get('rounds',0)<2:
            raise ValueError('Need two PETSc evaluations')
        for kind in ('single','match'):
            policies.append({**item,'id':f'opening-six{target}-{kind}', 'exit':kind,
                             'workerKey':f'opening-six{target}-single',
                             'nativeExitOverride':'single',
                             'statisticsScope':'source single iid statistics; full-route outcomes require real simulation'})
    steps=[]
    def leaf(target,kind,before,after):
        if sum(b[1] for b in before)+6>10:raise ValueError('Six-cell workspace does not fit')
        steps.append({'kind':'leaf','target':target,'exit':kind,'policyCells':6,
                      'template':f'6:{target}:{kind}','policy':f'opening-six{target}-{kind}',
                      'before':before,'after':after})
    b=lambda *values:[[v,1,False] for v in values]
    leaf(32,'single',b(),b(32))
    leaf(32,'match',b(32),b(64))
    leaf(32,'single',b(64),b(64,32))
    leaf(32,'match',b(64,32),b(128))
    leaf(40,'single',b(128),b(128,40))
    leaf(40,'match',b(128,40),b(128,80))
    leaf(40,'single',b(128,80),b(128,80,40))
    steps.append({'kind':'group','indices':[1,2],'before':b(128,80,40),
                  'after':[[128,1,False],[120,2,True]]})
    steps.append({'kind':'edge','before':[[128,1,False],[120,2,True]],'after':b(24)})
    leaf(40,'single',b(24) if protect24 else b(),b(24,40) if protect24 else b(40))
    return ({'id':'opening128-buffer3x40-edge24-single40','version':2,'kind':'stages',
             'target':-1,'cells':10,'initialPrefix':[],'steps':steps,
             'completionContract':b(24,40) if protect24 else b(40),
             'releaseAtStage':None if protect24 else 9,
             'goalRecognition':'completed-contract-only'},
            {'policies':policies})


class ContractExecutor(RouteExecutor):
    """Do not mistake an intermediate40 or a residual24 for route completion."""
    def _next(self,obs):
        # Release protection only: the real 24 and every residual stay on the board.
        if self.stage==self.route.get('releaseAtStage') and self.inner is None:
            self.fixed_ids.clear()
        try:
            return super()._next(obs)
        except RouteFailure as error:
            if str(error)=='route-finished-without-target' and self.stage==len(self.route['steps']):
                self._contract(obs,self.route['completionContract'])
                return None
            raise
