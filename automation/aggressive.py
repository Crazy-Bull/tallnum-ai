"""Build short-duration 128 policies with risk-aware VI and PETSc refinement."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess

from .common import atomic_json, event, fingerprint, link_or_copy
from .library import ROOT, NATIVE_DIR, SHARED_CLEAN_LIBRARY, load_catalog, register, table_rule, table_header, current_rule

RISK = ('0.05', '0.01', '0.005', '0.001')
PETSC_BIN = (ROOT/'aggressive-version/bin' if (ROOT/'aggressive-version/bin/tallnum_policy_eval.exe').exists()
             else ROOT/'native/petsc')


def execute(stage, argv, work, dll_dir=None, table_path=None):
    marker=work/f'{stage}.complete.json'
    identity={'tableSha256':fingerprint(table_path or work/'table.bin')}
    is_exit=stage.startswith('exit_probability')
    if is_exit:
        identity['graphSha256']=fingerprint(argv[1])
        identity['solverSha256']=fingerprint(argv[0])
    if marker.exists():
        data=json.loads(marker.read_text(encoding='utf-8'))
        if all(data.get(k)==v for k,v in identity.items()) and (not is_exit or Path(argv[2]).exists()):
            return
    env=os.environ.copy()
    if dll_dir:
        env['PATH']=str(dll_dir)+os.pathsep+env.get('PATH','')
    log=work/f'{stage}.log'
    event('aggressive-stage', stage=stage, directory=str(work))
    with log.open('w',encoding='utf-8') as output:
        process=subprocess.run(list(map(str,argv)),cwd=work,stdout=output,
                               stderr=subprocess.STDOUT,env=env)
    if process.returncode:
        raise RuntimeError(f'{stage} failed ({process.returncode}): '+log.read_text(encoding='utf-8',errors='replace')[-4000:])
    atomic_json(marker,identity)


def calculate(directory, target=128, risk=RISK, kinds=('match','extend'), vi_rounds=1500, requirement=None):
    if target<24:
        raise ValueError('Template targets must be at least 24')
    if target<48:
        risk=('0',)
    directory=Path(directory).resolve()
    catalog=load_catalog(directory,include_shared=True)['policies']
    vi=NATIVE_DIR/'tallnum_vi_aggressive.exe'
    petsc=PETSC_BIN/'tallnum_policy_eval.exe'
    if not vi.exists() or not petsc.exists():
        raise FileNotFoundError('Build aggressive VI and provide PETSc evaluator first')
    for kind in kinds:
        base=next((p for p in catalog if p['target']==target and p['exit']==kind
                   and table_header(p['table'])['successNoExtraCombos']
                   and (requirement is None or p.get('maxValue',target)==requirement['maxValue']
                        and p.get('bases')==requirement['bases']
                        and p.get('matchEdgeGuard',False)==requirement.get('matchEdgeGuard',False))),None)
        if base is None:
            raise ValueError(f'Prepare the {target} {kind} base policy first')
        table=Path(base['table'])
        if table_rule(table)!=current_rule():
            raise ValueError('Base table uses an outdated EDGE rule')
        for alpha in map(str, risk):
            label='a'+alpha.replace('.','')
            suffix='' if requirement is None else '-'+fingerprint(table)[:12]
            shared_base=table.resolve().is_relative_to(SHARED_CLEAN_LIBRARY.resolve())
            work_root=SHARED_CLEAN_LIBRARY/'aggressive' if shared_base else directory/'aggressive'
            work=work_root/f'{target}-{kind}-{label}{suffix}-cleanexit'
            work.mkdir(parents=True,exist_ok=True)
            link=work/'table.bin'
            if not link.exists():
                # PETSc reads its transition table by path; no large duplicate.
                link_or_copy(table,link)
            if fingerprint(link)!=fingerprint(table):
                raise ValueError('Aggressive table link no longer matches base')
            execute('01_vi',[vi,'table.bin',vi_rounds,'1e-10','01_vi.values.bin',
                             '--aggressiveness',alpha],work)
            values='01_vi.values.bin'
            previous=None
            for step in range(1,7):
                actual=step==6
                stage=f'{step+1:02d}_petsc_'+('actual' if actual else 'aggressive')
                policy=f'{stage}.policy.bin'
                result=f'{stage}.values.bin'
                args=[petsc,'-tallnum_table','table.bin','-tallnum_values',values,
                      '-tallnum_aggressiveness','0' if actual else alpha,
                      '-tallnum_save_policy',policy,'-tallnum_save_values',result,
                      '-tallnum_result',f'{stage}.result.json',
                      '-ksp_type','dgmres','-ksp_gmres_restart','50',
                      '-ksp_rtol','1e-10','-ksp_atol','1e-12',
                      '-ksp_max_it','20000','-pc_type','jacobi']
                if previous:
                    args+=['-tallnum_previous_policy',previous]
                if actual:
                    args+=['-tallnum_input_aggressiveness',alpha]
                    if requirement is not None:
                        # Evaluate the aggressive policy unchanged under actual
                        # risk=0, rather than improving it for another objective.
                        position=args.index('-tallnum_values')
                        args[position:position+2]=['-tallnum_policy',previous]
                        position=args.index('-tallnum_previous_policy')
                        del args[position:position+2]
                execute(stage,args,work,PETSC_BIN)
                values=result
                previous=policy
            item=register(directory,table,work/previous,kind,
                          variant_aggressiveness=float(alpha))
            final=json.loads((work/'07_petsc_actual.result.json').read_text(encoding='utf-8'))
            if (not final.get('converged') or final.get('aggressiveness')!=0
                    or final.get('input_aggressiveness')!=float(alpha)):
                raise RuntimeError(f'PETSc and fixed-policy success probability disagree: {work}')
            from .certify import attach
            item=attach(directory,item,work/'07_petsc_actual.result.json',6)
            if requirement is not None:
                from .library import store_policy
                item['variantAggressiveness']=float(alpha)
                atomic_json(directory/(item['id']+'.json'),item)
                store_policy(directory,item)
            if requirement is not None:
                from .route_storage import prune_completed
                prune_completed(directory)
            event('aggressive-complete',target=target,exit=kind,aggressiveness=alpha,
                  policy=item['id'],petscSuccess=item['petsc']['successProbability'],
                  statistics=item['statistics'])


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--target',type=int,default=128)
    parser.add_argument('--risk',nargs='+',default=list(RISK))
    parser.add_argument('--exit',nargs='+',choices=('match','extend'),default=['match','extend'])
    parser.add_argument('--vi-rounds',type=int,default=1500)
    args=parser.parse_args()
    calculate(args.directory,args.target,args.risk,args.exit,args.vi_rounds)
