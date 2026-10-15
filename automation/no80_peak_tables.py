"""Prepare certified pending-state probability tables needed by peak-count search."""
from __future__ import annotations

from copy import deepcopy
import argparse
import json
import os
from pathlib import Path
import subprocess

from .common import atomic_json, fingerprint
from .library import current_rule, table_fingerprint, table_header, table_rule
from .no80_route import OUT, ROOT


ARCHIVE=Path('F:/TallnumData/tallnumai-templates/automation/runs/missing-expected')
SOURCE48=ARCHIVE/'generated/edge-recheck-v1/5-48-1-max48/table.bin'
VALUES48=ARCHIVE/'certification/48-single-cc28bd56530a-4298e31048c0-07149a81/04_petsc_actual.values.bin'
RESULT48=VALUES48.with_name('04_petsc_actual.result.json')
TABLE40=Path('F:/TallnumData/tallnumai-cleanexit/generated/edge-recheck-v1/5-40-1-max80-cleanexit/table.bin')
VALUES40=TABLE40.with_name('values.bin')
RESULT40=Path(str(TABLE40)+'.result.json')


def prepare_44_model(destination,env):
    work=destination/'5-44-single-model';work.mkdir(parents=True,exist_ok=True)
    table,values=work/'table.bin',work/'values.bin'
    generator=OUT/'real-boundary-generator.exe'
    if not table.exists():
        with (work/'generate.log').open('w',encoding='utf-8') as log:
            subprocess.run([str(generator),'--cells','5','--target','44',
                            '--max-value','64','--max-goal-cells','1','--bases','1,3,5,15',
                            '--success-side','above','--success-no-extra-combos','1',
                            '--output',str(table)],cwd=ROOT,env=env,stdout=log,
                           stderr=subprocess.STDOUT,check=True)
        atomic_json(Path(str(table)+'.rules.json'),{'ruleSha256':current_rule(),
                    'tableSha256':fingerprint(table),
                    'modelSha256':fingerprint(str(table)+'.model.json')})
    if not values.exists():
        with (work/'vi.log').open('w',encoding='utf-8') as log:
            subprocess.run([str(ROOT/'tallnum_vi.exe'),str(table),'5000','1e-10',str(values)],
                           cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
    return table,values,Path(str(table)+'.result.json')


def prepare(source_catalog,destination):
    destination=Path(destination).resolve();destination.mkdir(parents=True,exist_ok=True)
    source=json.loads(Path(source_catalog).read_text(encoding='utf-8'))
    catalog={'policies':[deepcopy(p) for p in source['policies']]}
    for item in catalog['policies']:
        if not item.get('pendingValue') or not item.get('disableStaticFallback'):
            raise ValueError('Peak-count planner requires probability-only source policies')
        # Historical policy binaries may be archived; pending search reads
        # only the certified table and the verified probability file.
        item['pendingOnlyIdentity']=True
    native=(OUT/'probability-pending-v2.exe').resolve()
    if not native.exists():raise FileNotFoundError(native)
    env=os.environ.copy();env['PATH']=str(ROOT/'.tools/msys64/ucrt64/bin')+os.pathsep+env.get('PATH','')
    for target,table,values,result in ((40,TABLE40,VALUES40,RESULT40),
                                       (48,SOURCE48,VALUES48,RESULT48)):
        header=table_header(table)
        if table_rule(table)!=current_rule() or header['target']!=target or header['cells']!=5 or header['maxGoalCells']!=1:
            raise ValueError(f'Uncertified single-success model: {target}')
        info=json.loads(result.read_text(encoding='utf-8'))
        if target in (40,44) and (info['max_delta']>info['tolerance'] or info['iterations']<=0):
            raise ValueError(f'{target} probability VI did not converge')
        if target==48 and (not info['converged'] or info['true_residual_inf']>1e-9):
            raise ValueError('48 policy-value evaluation did not converge')
        ident=f'5-{target}-single-pending-peak13'
        pending=destination/(ident+'.bin')
        if not pending.exists():
            temporary=pending.with_suffix('.building')
            temporary.unlink(missing_ok=True)
            with (destination/(ident+'.build.log')).open('w',encoding='utf-8') as log:
                subprocess.run([str(native),'build',str(table),str(values),str(temporary)],
                               cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
            temporary.replace(pending)
        digest=fingerprint(pending)
        value_sha=fingerprint(values)
        table_sha=table_fingerprint(table)
        metadata={'format':'TNPEND02','pendingSha256':digest,'tableSha256':table_sha,
                  'policySha256':value_sha,'target':target,'exit':'single',
                  'successNoExtraCombos':header['successNoExtraCombos'],
                  'matchEdgeGuard':False,'maxValue':header['maxValue'],
                  'maxGoalCells':1,'cells':5,'probabilitySource':str(values),
                  'probabilitySourceSha256':value_sha,'convergence':info,
                  'actionSelection':'pending-state probability search; no fixed policy actions'}
        meta=destination/(ident+'.json');atomic_json(meta,metadata)
        item={'id':ident,'cells':5,'target':target,'exit':'single','table':str(table),
              'policy':str(values),'policySha256':value_sha,'pendingOnlyIdentity':True,
              'hashes':{'table':table_sha},'ruleSha256':current_rule(),
              'maxValue':header['maxValue'],'maxGoalCells':1,'bases':header['bases'],
              'successNoExtraCombos':header['successNoExtraCombos'],
              'pendingValue':str(pending),'pendingValueSha256':digest,
              'pendingValueMeta':str(meta),'pendingNative':str(native),
              'disableStaticFallback':True,'realBoardAlternatives':True,
              'statistics':{'p':info.get('weighted',info.get('weighted_policy_value',0.99)),
                            'u':50,'v':0},
              'probabilityScope':'converged state success probabilities; live action search'}
        catalog['policies'].append(item)
        print(json.dumps({'probabilityTableReady':ident,'bytes':pending.stat().st_size}),flush=True)
    atomic_json(destination/'catalog.json',catalog)
    opening_source=Path(source_catalog).parent/'opening-catalog.json'
    if opening_source.exists():
        opening=json.loads(opening_source.read_text(encoding='utf-8'))
        for item in opening['policies']:
            if not item.get('pendingValue') or not item.get('disableStaticFallback'):
                raise ValueError('Opening has a fixed-policy definition')
            item['pendingOnlyIdentity']=True
        atomic_json(destination/'opening-catalog.json',opening)
    return destination/'catalog.json'


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-catalog',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    print(prepare(args.source_catalog,args.out),flush=True)
