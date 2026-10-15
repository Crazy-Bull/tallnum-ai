"""Apply the measured tidy-single exit predicate to new five-cell producers."""
import argparse
import json
import os
from pathlib import Path
import subprocess

from .common import atomic_json, fingerprint
from .library import register, current_rule, MODEL
from .no80_route import OUT, ROOT, EVIDENCE, audit


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--targets',default='6,12,10,8,16,30,60,64')
    args=parser.parse_args()
    targets=[int(v) for v in args.targets.split(',')]
    directory=OUT/'tidy-five'
    directory.mkdir(exist_ok=True)
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    route=read(OUT/('route-tidy-five.json' if (OUT/'route-tidy-five.json').exists() else 'route-v9.json'))
    catalog=read(OUT/('catalog-tidy-five.json' if (OUT/'catalog-tidy-five.json').exists() else 'catalog-v9.json'))
    original=read(EVIDENCE/'route.json')
    prefix_length=next(i for i,s in enumerate(original['steps']) if s['after']==[[5120,1,False]])+1
    os.environ['PATH']=str(ROOT/'.tools/msys64/ucrt64/bin')+os.pathsep+os.environ['PATH']
    native=OUT/'tidy-five-pending.exe'
    for target in targets:
        item=next(p for p in catalog['policies'] if p.get('cells',5)==5 and p['exit']=='single' and p['target']==target)
        work=directory/str(target);work.mkdir(exist_ok=True)
        table=work/'table.bin';values=work/'values.bin';pending=work/'pending.bin'
        with (work/'compute.log').open('a') as log:
            if not table.exists():
                subprocess.run([str(OUT/'tidy-five-generator.exe'),'--cells','5','--target',str(target),
                    '--max-value',str(item['maxValue']),'--max-goal-cells','1','--bases',','.join(map(str,item['bases'])),
                    '--success-side','above','--success-no-extra-combos','1','--single-tidy-exit','1',
                    '--output',str(table)],stdout=log,stderr=subprocess.STDOUT,check=True)
                atomic_json(Path(str(table)+'.rules.json'),{'ruleSha256':current_rule(),
                    'sourceSha256':fingerprint(MODEL),'modelSha256':fingerprint(str(table)+'.model.json'),
                    'tableSha256':fingerprint(table)})
            if not values.exists():
                subprocess.run([str(ROOT/'tallnum_vi.exe'),str(table),'5000','1e-10',str(values)],
                               stdout=log,stderr=subprocess.STDOUT,check=True)
            if not pending.exists():
                subprocess.run([str(native),'build',str(table),str(values),str(pending)],
                               stdout=log,stderr=subprocess.STDOUT,check=True)
        replacement=register(directory,table,values,'single')
        meta={'format':'TNPEND03','pendingSha256':fingerprint(pending),
              'tableSha256':replacement['hashes']['table'],'policySha256':replacement['policySha256'],
              'target':target,'exit':'single','cells':5,'successNoExtraCombos':True,
              'matchEdgeGuard':False,'singleEdgeGuard':False,'singleTidyExit':True,
              'maxValue':item['maxValue'],'maxGoalCells':1,'sourceValuesSha256':fingerprint(values),
              'valueProvenance':read(Path(str(table)+'.result.json'))}
        meta_file=work/'pending.json';atomic_json(meta_file,meta)
        replacement.update(pendingValue=str(pending),pendingValueMeta=str(meta_file),
            pendingValueSha256=meta['pendingSha256'],pendingNative=str(native),realBoardAlternatives=True)
        catalog['policies']=[p for p in catalog['policies'] if p['id']!=item['id']]+[replacement]
        for step in route['steps']:
            if step.get('policy')==item['id']:step['policy']=replacement['id']
        if route['steps'][:prefix_length]!=original['steps'][:prefix_length]:
            raise ValueError('Tidy-five rebind changed the measured opening/prefix')
        audit(route,catalog)
        atomic_json(OUT/'route-tidy-five.json',route);atomic_json(OUT/'catalog-tidy-five.json',catalog)
        print(json.dumps({'target':target,'policy':replacement['id'],'values':meta['valueProvenance']}),flush=True)


if __name__=='__main__':main()
