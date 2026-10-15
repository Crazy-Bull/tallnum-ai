"""Replace an exact two-leaf32 construction by a certified64 match."""
from copy import deepcopy


def select_match64_policy(route,catalog,policy):
    if (policy['target']!=64 or policy['exit']!='match' or policy.get('cells',5)!=5
            or policy['maxValue']<64 or not policy.get('petsc',{}).get('verified')
            or policy['petsc'].get('exitEvaluationRounds',0)<2):
        raise ValueError('Need certified bound>=64 five-cell match64')
    result=deepcopy(route);selected=0
    for step in result['steps']:
        if step['kind']=='leaf' and step['target']==64 and step['exit']=='match' and step.get('policyCells',5)==5:
            step['policy']=policy['id'];selected+=1
    result['match64Variant']={'policy':policy['id'],'aggressiveness':policy.get('variantAggressiveness',0),
                             'calls':selected,'fixedExitProbabilityRounds':policy['petsc']['exitEvaluationRounds']}
    return result,{'policies':deepcopy(catalog['policies'])+[deepcopy(policy)]}


def compress_match64(route,catalog):
    policy=next(p for p in catalog['policies'] if p['target']==64 and p['exit']=='match' and p.get('cells',5)==5)
    if policy['maxValue']<48 or not policy['petsc']['verified'] or policy['petsc']['exitEvaluationRounds']<2:
        raise ValueError('Need two PETSc rounds for bound>=48 match64')
    result=deepcopy(route);steps=route['steps'];out=[];replacements=[];i=0
    while i<len(steps):
        a=steps[i];b=steps[i+1] if i+1<len(steps) else {}
        eligible=(a['kind']=='leaf' and b.get('kind')=='leaf' and a.get('target')==32
                  and b.get('target')==32 and a['exit']=='single' and b['exit']=='match'
                  and a['after']==b['before'] and a['before'] and a['before'][-1]==[64,1,False]
                  and sum(x[1] for x in a['before'])+5<=route['cells'])
        if eligible:
            # Verify the prescribed result by the ordinary right-to-left cascade.
            board=deepcopy(a['before'])+[[64,1,False]]
            while True:
                j=next((j for j in range(len(board)-2,-1,-1) if board[j][0]==board[j+1][0]),None)
                if j is None:break
                board[j:j+2]=[[2*board[j][0],1,False]]
            if board!=b['after']:raise ValueError('Compressed match exit differs')
            out.append({**a,'target':64,'exit':'match','template':'5:64:match','policyCells':5,
                        'availableCells':route['cells']-sum(x[1] for x in a['before']),
                        'policy':policy['id'],'after':deepcopy(b['after'])})
            replacements.append({'oldStages':[i,i+1],'newStage':len(out)-1,'before':a['before'],'after':b['after']})
            i+=2
        else:out.append(deepcopy(a));i+=1
    result['steps']=out
    result['match64Compression']={'replacements':replacements,'oldSteps':len(steps),'newSteps':len(out),
                                  'fixedPoliciesChanged':False}
    return result
