"""Attach saved six-cell VI probability tables to the original 10240 opening."""
from __future__ import annotations

from copy import deepcopy
import argparse
import json
import os
from pathlib import Path
import subprocess

from .common import atomic_json, fingerprint
from .library import table_header
from .no80_route import ROOT, OUT


OPENING_IDS = ('opening-six32-single', 'opening-six40-single')
DEFAULT_DEST = OUT / 'probability-opening'


def prepare(destination=DEFAULT_DEST):
    source=json.loads((OUT/'validation-min24-v5-fresh/catalog.json').read_text(encoding='utf-8'))
    policies={p['id']:p for p in source['policies']}
    native=OUT/'probability-pending.exe'
    if not native.exists():raise FileNotFoundError(native)
    destination=Path(destination).resolve()
    destination.mkdir(parents=True,exist_ok=True)
    opening=[]
    runtime_env=os.environ.copy()
    runtime_env['PATH']=str(ROOT/'.tools/msys64/ucrt64/bin')+os.pathsep+runtime_env.get('PATH','')
    for ident in OPENING_IDS:
        item=deepcopy(policies[ident])
        table=Path(item['table'])
        values=Path(item['dataDirectory'])/'vi.values.bin'
        vi=json.loads(Path(str(table)+'.result.json').read_text(encoding='utf-8'))
        if not values.exists() or vi.get('max_delta',1)>vi.get('tolerance',1e-10):
            raise ValueError(f'Unconverged opening probability table: {ident}')
        header=table_header(table)
        if header['cells']!=6 or header['target']!=item['target'] or not header['successNoExtraCombos']:
            raise ValueError(f'Opening table changed: {ident}')
        pending=destination/(ident+'.bin')
        metadata=destination/(ident+'.json')
        if not pending.exists():
            temporary=destination/(ident+'.building')
            temporary.unlink(missing_ok=True)
            log=destination/(ident+'.build.log')
            with values.open('rb') as probe:magic=probe.read(8)
            if magic not in (b'TALLAVA1',b'TALLVAL4'):
                raise ValueError(f'Unknown values format: {ident}')
            print(json.dumps({'buildingProbabilityTable':ident}),flush=True)
            with log.open('w',encoding='utf-8') as output:
                subprocess.run([str(native),'build',str(table),str(values),str(temporary)],
                               cwd=ROOT,env=runtime_env,stdout=output,stderr=subprocess.STDOUT,check=True)
            temporary.replace(pending)
        digest=fingerprint(pending)
        record={'format':'TNPEND02','pendingSha256':digest,
                'tableSha256':item['hashes']['table'],'policySha256':item['policySha256'],
                'target':item['target'],'exit':item['exit'],'cells':6,
                'maxValue':header['maxValue'],'maxGoalCells':header['maxGoalCells'],
                'successNoExtraCombos':True,'matchEdgeGuard':False,
                'valueSource':str(values),'valueIteration':vi}
        atomic_json(metadata,record)
        item.pop('cacheBuilderNative',None)
        item.update(pendingValue=str(pending.resolve()),pendingValueMeta=str(metadata.resolve()),
                    pendingValueSha256=digest,pendingNative=str(native.resolve()),
                    disableStaticFallback=True,realBoardAlternatives=True,
                    probabilityScope='saved converged VI values; dynamic search on two visible previews')
        opening.append(item)
        print(json.dumps({'openingProbabilityReady':ident,'pendingBytes':pending.stat().st_size}),flush=True)
    opening_path=destination/'opening-catalog.json'
    atomic_json(opening_path,{'policies':opening})
    suffix=json.loads((OUT/'catalog-min24.json').read_text(encoding='utf-8'))
    for item in suffix['policies']:
        if not item.get('pendingValue'):
            raise ValueError('Suffix contains a fixed-policy definition: '+item['id'])
        item['disableStaticFallback']=True
    suffix_path=destination/'suffix-catalog.json'
    atomic_json(suffix_path,suffix)
    return opening_path,suffix_path


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=DEFAULT_DEST)
    args=parser.parse_args()
    print(json.dumps([str(p) for p in prepare(args.out)]),flush=True)
