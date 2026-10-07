"""Finish each unpenalized five-cell policy with PETSc and verify its probability."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import struct

from .aggressive import PETSC_BIN, execute
from .common import atomic_json, fingerprint, event, link_or_copy
from .library import load_catalog, register, table_rule, table_header, current_rule, NATIVE_DIR, store_policy


def attach(directory, item, result, rounds, restart=50):
    directory=Path(directory).resolve()
    clean=table_header(item['table'])['successNoExtraCombos']
    if clean!=item.get('successNoExtraCombos',False):
        raise ValueError('Certification victory condition differs from transition table')
    data=json.loads(Path(result).read_text(encoding='utf-8'))
    p=item['statistics']['p']
    if not data.get('converged') or data.get('aggressiveness')!=0:
        raise RuntimeError(f'PETSc probability does not match fixed-policy graph: {result}')
    work=Path(result).parent
    if not work.resolve().is_relative_to(directory) or not (work/'table.bin').exists():
        work=directory/'certification'/item['id']
        work.mkdir(parents=True,exist_ok=True)
    # Export names end in .policy.bin; graph shares the policy identifier.
    graph=Path(directory)/(item['id']+'.graph.bin')
    evaluations=[]
    for step,rtol in ((1,'1e-11'),(2,'1e-12')):
        stage=f'exit_probability_{step:02d}'
        bound=work/f'{stage}.result.json'
        execute(stage,[NATIVE_DIR/'petsc_graph_eval.exe',graph,bound,
                 '-ksp_type','dgmres','-ksp_gmres_restart',str(restart),'-ksp_rtol',rtol,
                 '-ksp_atol','1e-13','-ksp_max_it','20000','-pc_type','jacobi'],work,PETSC_BIN,table_path=item['table'])
        actual=json.loads(bound.read_text(encoding='utf-8'))
        if not actual.get('converged') or abs(actual['successProbability']-p)>1e-5:
            raise RuntimeError(f'PETSc exit probability does not match fixed-policy graph: {bound}')
        evaluations.append(str(bound.resolve()))
    item=dict(item)
    # Evaluation at zero risk does not change the policy's construction variant.
    item['variantAggressiveness']=data.get('input_aggressiveness',data['aggressiveness'])
    stats=dict(item['statistics'])
    stats['momentSolverSuccessProbability']=p
    stats['p']=actual['successProbability']
    stats['failureProbability']=max(0,1-stats['p']-stats['nonterminationProbability'])
    stats['successDrops']=stats['u']/stats['p'] if stats['p'] else None
    stats['failureDrops']=stats['v']/stats['failureProbability'] if stats['failureProbability'] else None
    stats['expectedTotalDrops']=(stats['u']+stats['v'])/stats['p'] if stats['usable'] and stats['p'] else None
    stats['probabilitySolver']='PETSc-fixed-exit-graph'
    stats['probabilityResidual']=actual['residualInf']
    item['statistics']=stats
    item['petsc']={'verified':True,'rounds':rounds,'successNoExtraCombos':clean,
                   'successProbability':actual['successProbability'],
                   'difference':abs(actual['successProbability']-p),
                   'exitEvaluationRounds':len(evaluations),'exitEvaluationResults':evaluations,
                   'result':str(bound.resolve()), 'improvementResult':str(Path(result).resolve())}
    directory=Path(directory)
    atomic_json(directory/(item['id']+'.json'),item)
    store_policy(directory,item)
    return item


def convert_value(source, output):
    with open(source,'rb') as src, open(output,'wb') as dst:
        if src.read(8)!=b'TALLVAL4':
            raise ValueError('Expected complete TALLVAL4 baseline values')
        dst.write(b'TALLAVA1')
        dst.write(struct.pack('<d',0.0))
        shutil.copyfileobj(src,dst,1024*1024)


def certify_baselines(directory, restart=50):
    if not 1 <= restart <= 200:
        raise ValueError('Solver restart must be in 1..200')
    directory=Path(directory).resolve()
    petsc=PETSC_BIN/'tallnum_policy_eval.exe'
    policies=list(load_catalog(directory)['policies'])
    certified_sources={Path(p['petsc']['improvementResult']).parent.name for p in policies
                       if p.get('petsc',{}).get('verified') and p['petsc'].get('improvementResult')}
    for item in policies:
        if item['id'] in certified_sources:
            continue
        if item.get('petsc',{}).get('verified') or not Path(item['source']).exists():
            continue
        with open(item['source'],'rb') as file:
            if file.read(8)!=b'TALLVAL4':
                continue
        table=Path(item['table'])
        if table_rule(table)!=current_rule():
            raise ValueError('Uncertified transition table uses the old EDGE rule')
        work=directory/'certification'/item['id']
        work.mkdir(parents=True,exist_ok=True)
        link=work/'table.bin'
        if not link.exists():
            link_or_copy(table,link)
        if fingerprint(link)!=fingerprint(table):
            raise ValueError('PETSc table link changed')
        values=work/'01_values.bin'
        if not values.exists():
            convert_value(item['source'],values)
        previous=None
        for step in (2,3):
            stage=f'{step:02d}_petsc_improve'
            args=[petsc,'-tallnum_table','table.bin','-tallnum_values',
                  '01_values.bin' if step==2 else '02_petsc_improve.values.bin',
                  '-tallnum_aggressiveness','0',
                  '-tallnum_save_policy',f'{stage}.policy.bin',
                  '-tallnum_save_values',f'{stage}.values.bin',
                  '-tallnum_result',f'{stage}.result.json',
                  '-ksp_type','dgmres','-ksp_gmres_restart',str(restart),
                  '-ksp_rtol','1e-10','-ksp_atol','1e-12',
                  '-ksp_max_it','20000','-pc_type','jacobi']
            if previous:
                args+=['-tallnum_previous_policy',previous]
            execute(stage,args,work,PETSC_BIN)
            previous=f'{stage}.policy.bin'
        final='04_petsc_actual'
        execute(final,[petsc,'-tallnum_table','table.bin',
                       '-tallnum_policy',previous,
                       '-tallnum_aggressiveness','0',
                       '-tallnum_save_values',f'{final}.values.bin',
                       '-tallnum_result',f'{final}.result.json',
                       '-ksp_type','dgmres','-ksp_gmres_restart',str(restart),
                       '-ksp_rtol','1e-10','-ksp_atol','1e-12',
                       '-ksp_max_it','20000','-pc_type','jacobi'],work,PETSC_BIN)
        certified=register(directory,table,work/previous,item['exit'])
        certified=attach(directory,certified,work/f'{final}.result.json',3,restart)
        event('certified-baseline',target=item['target'],exit=item['exit'],
              policy=certified['id'],statistics=certified['statistics'])


def attach_variants(directory):
    directory=Path(directory).resolve()
    for item in list(load_catalog(directory)['policies']):
        source=Path(item['source'])
        if (item.get('petsc',{}).get('verified') or
                source.name!='07_petsc_actual.policy.bin' or
                source.parent.parent!=directory/'aggressive'):
            continue
        attach(directory,item,source.parent/'07_petsc_actual.result.json',6)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--solver-restart',type=int,default=50)
    args=parser.parse_args()
    certify_baselines(args.directory,args.solver_restart)
    attach_variants(args.directory)
    for item in list(load_catalog(args.directory)['policies']):
        evidence=item.get('petsc',{})
        if evidence.get('verified') and item['statistics'].get('probabilitySolver')!='PETSc-fixed-exit-graph':
            attach(args.directory,item,evidence['improvementResult'],evidence['rounds'])
