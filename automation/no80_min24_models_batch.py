"""Finish required min24 policies serially after the first warm model."""
import time
from .no80_route import OUT
from .no80_declared_models import build


def main():
    first=OUT/'min24-models/6-single-36-anchor5120-warm18-keep/policy.json'
    deadline=time.monotonic()+3600
    while not first.exists():
        if time.monotonic()>deadline:raise TimeoutError('First warm policy did not finish')
        time.sleep(10)
    jobs=[(28,'single',5120,48,'1,3,5,7,15',14,6,True),
          (44,'single',5120,64,'1,3,5,11,15',22,6,True),
          (30,'single',80,64,'1,3,5,15',None,5,False),
          (28,'match',28,64,'1,3,5,15',None,5,False),
          (34,'match',34,64,'1,3,5,15',None,5,False),
          (36,'match',36,64,'1,3,5,15',None,5,False),
          (44,'match',44,64,'1,3,5,15',None,5,False),
          (54,'match',54,64,'1,3,5,15',None,5,False),
          (56,'match',56,64,'1,3,5,15',None,5,False),
          (36,'extend',32,64,'1,3,5,15',None,5,False),
          (48,'extend',40,64,'1,3,5,15',None,5,False),
          (60,'extend',48,64,'1,3,5,15',None,5,False)]
    for job in jobs:
        print('building',job,flush=True)
        build(*job)
        from .compact_ready_no80_model import compact
        name=(f'{job[6]}-{job[1]}-{job[0]}-anchor{job[2]}'
              +(f'-warm{job[5]}' if job[5] else '')+('-keep' if job[7] else ''))
        compact(name)
    from .no80_min24_bind import bind
    if not bind():raise ValueError('Policies still missing')


if __name__=='__main__':main()
