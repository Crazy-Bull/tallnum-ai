"""Per-template variant manifests, bound to model and fixed-policy identities."""
from pathlib import Path

from .common import atomic_json
from .library import load_catalog, prepare_missing
from .route_search import identity, template_alphas


def matching(policy, requirement):
    return (policy['target'] == requirement['target'] and policy['exit'] == requirement['exit']
            and policy.get('maxValue', policy['target']) == requirement['maxValue']
            and policy.get('bases') == requirement['bases']
            and policy.get('maxGoalCells') == requirement['maxGoalCells']
            and policy.get('matchEdgeGuard',False)==requirement.get('matchEdgeGuard',False)
            and ('successNoExtraCombos' not in requirement
                 or policy.get('successNoExtraCombos',False)==requirement['successNoExtraCombos']))


def manifest(directory, requirement, catalog=None):
    requirement = {**requirement, 'aggressiveness': template_alphas(requirement['target'], requirement.get('aggressiveness'))}
    catalog = catalog if catalog is not None else load_catalog(directory,include_shared=True)
    variants = []
    for policy in catalog['policies']:
        if not matching(policy, requirement):
            continue
        stats = policy.get('statistics', {})
        alpha = float(policy.get('variantAggressiveness', policy.get('aggressiveness', 0)))
        if alpha not in requirement['aggressiveness']:
            continue
        certified = (policy.get('petsc', {}).get('verified', False)
                  and policy.get('petsc', {}).get('exitEvaluationRounds', 0) >= 2
                  and policy.get('exitSemantics') == ('success-board-clean-v3' if requirement.get('successNoExtraCombos')
                                                       else 'success-board-v2')
                  and policy.get('successNoExtraCombos',False)==bool(requirement.get('successNoExtraCombos')))
        p, u, v = (stats.get(k) for k in ('p', 'u', 'v'))
        certified=certified and p is not None
        usable=certified and stats.get('usable',False) and p > 0
        c = u+v if u is not None and v is not None else None
        variants.append({'id': policy['id'], 'aggressiveness': alpha,
                         'p': p, 'c': c, 'u': u, 'v': v,
                         'expectedTotalDrops': c/p if usable and p and c is not None else None,
                         'usable': bool(usable),'certified':bool(certified), 'policy': policy['policy'],
                         'policySha256': policy['policySha256'], 'statistics': stats,
                         'petsc': policy.get('petsc', {})})
    alphas = requirement['aggressiveness']
    missing = [a for a in alphas if not any(v['certified'] and v['aggressiveness']==a for v in variants)]
    result = {'version': 2, 'requirement': requirement, 'variants': variants,
              'missingAggressiveness': missing, 'complete': not missing,
              'evaluation': 'fixed-policy-original-rules-no-artificial-death'}
    key = identity({k: v for k, v in requirement.items() if k != 'aggressiveness'})
    path = Path(directory)/'templates'/(key+('-cleanexit' if requirement.get('successNoExtraCombos') else ''))/'variants.json'
    atomic_json(path, result)
    return result


def prepare_variants(directory, requirements, rounds=5000):
    from .certify import certify_baselines
    from .aggressive import calculate
    from .route_storage import prune_completed
    for requirement in requirements:
        requirement={**requirement,'successNoExtraCombos':True}
        report = manifest(directory, requirement)
        if report['complete']:
            continue
        if 0 in report['missingAggressiveness']:
            prepare_missing(directory, [requirement], rounds)
            certify_baselines(directory)
        report = manifest(directory, requirement)
        remaining = [a for a in report['missingAggressiveness'] if a != 0]
        if remaining:
            calculate(directory, requirement['target'], remaining,
                      (requirement['exit'],), rounds, requirement=requirement)
        report = manifest(directory, requirement)
        prune_completed(directory)
        if not report['complete']:
            raise RuntimeError('Variants remain uncertified/unusable: '+requirement['key'])
    return manifest(directory, requirements[-1]) if requirements else None
