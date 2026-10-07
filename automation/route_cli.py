"""Isolated v2 planning commands; never writes the live player's plan.json."""
import argparse
import json
from pathlib import Path

from .common import atomic_json, event, fingerprint, execution_fingerprint
from .library import load_catalog
from .route_search import RouteSearch, identity
from .route_variants import manifest, prepare_variants


def main(argv=None):
    parser = argparse.ArgumentParser(description='Weighted memoized Tallnum route planner and browser player')
    parser.add_argument('command', choices=['plan', 'continue', 'prepare', 'validate', 'play'])
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--cells', type=int, choices=[7, 10])
    parser.add_argument('--target', type=int)
    parser.add_argument('--max-value', type=int)
    parser.add_argument('--local-template-bounds',action='store_true',default=None)
    parser.add_argument('--max-leaf-target',type=int)
    parser.add_argument('--initial-prefix',type=int,nargs='+')
    parser.add_argument('--resume-current-game',action='store_true')
    parser.add_argument('--finish-current-game',action='store_true')
    parser.add_argument('--restart-settled-game',action='store_true')
    parser.add_argument('--browser',choices=['chrome','msedge'],default='chrome')
    parser.add_argument('--cdp-endpoint')
    parser.add_argument('--weights', type=Path, help='JSON mapping 5:target:exit to positive normalized weight')
    parser.add_argument('--leaf-targets', type=int, nargs='+', help='Explicitly restrict structural leaf domain (recorded in search scope)')
    parser.add_argument('--candidate-limit', type=int)
    parser.add_argument('--node-limit', type=int, default=0, help='New subproblem budget; 0 runs until candidate scope completes')
    parser.add_argument('--rounds', type=int, default=5000)
    parser.add_argument('--attempts', type=int, default=100)
    args = parser.parse_args(argv)
    if not 1 <= args.rounds <= 1000000 or not 1 <= args.attempts <= 1000000:
        parser.error('rounds and attempts must be 1..1000000')
    args.directory = args.directory.resolve()
    args.directory.mkdir(parents=True, exist_ok=True)
    saved = args.directory/'route-request.json'
    config = json.loads(saved.read_text(encoding='utf-8')) if saved.exists() else {}
    for option in ('cells', 'target', 'max_value', 'candidate_limit', 'leaf_targets','local_template_bounds','max_leaf_target'):
        if getattr(args, option) is not None:
            config[option] = getattr(args, option)
    if args.initial_prefix is not None:config['initial_prefix']=[[n,1,False] for n in args.initial_prefix]
    if args.weights:
        config['weights'] = json.loads(args.weights.read_text(encoding='utf-8'))
    config.setdefault('cells', 7)
    if 'target' not in config:
        parser.error('--target is required for a new route search')
    config.setdefault('candidate_limit', 20)
    if args.command not in ('validate','play'):
        # Validate config before publishing request.
        search = RouteSearch(args.directory, load_catalog(args.directory, certified_only=True,clean_only=True,include_shared=True),
                             node_limit=args.node_limit, **config)
        atomic_json(saved, config)
        try:
            result = search.plan()
        finally:
            search.close()
        if config.get('local_template_bounds') and not config.get('initial_prefix'):
            from .route_continuation import link_continuation
            result=link_continuation(args.directory,load_catalog(args.directory,certified_only=True,
                                     clean_only=True,include_shared=True),config,min(args.node_limit or 2000,2000))
        if args.command == 'prepare':
            prepare_variants(args.directory, result['requirements'], args.rounds)
            search = RouteSearch(args.directory, load_catalog(args.directory, certified_only=True,clean_only=True,include_shared=True),
                                 node_limit=args.node_limit, **config)
            try:
                result = search.plan()
            finally:
                search.close()
        if args.command=='prepare' and config.get('local_template_bounds') and not config.get('initial_prefix'):
            result=link_continuation(args.directory,load_catalog(args.directory,certified_only=True,
                                     clean_only=True,include_shared=True),config,2000)
        for requirement in result['requirements']:
            manifest(args.directory, requirement)
        event('route-plan', status=result['status'], routes=len(result['routes']),
              structures=len(result['structures']), missing=len(result['missing']),
              path=str(args.directory/'route-plan.json'))
        return result
    from .validation import rank
    file = args.directory/'route-plan.json'
    result = json.loads(file.read_text(encoding='utf-8'))
    if result.get('version') != 2 or not result['routes']:
        raise ValueError('Prepare a v2 plan with executable candidates first')
    if result['cells'] != config['cells'] or result['target'] != config['target']:
        raise ValueError('Requested cells/target differ from saved plan')
    catalog = load_catalog(args.directory, certified_only=True,clean_only=True,include_shared=True)
    available = {p['id'] for p in catalog['policies']}
    if any(step['policy'] not in available for r in result['routes'] for step in [*r['steps'],*r.get('continuation',{}).get('steps',[])] if step['kind']=='leaf'):
        raise ValueError('Plan references missing or uncertified policies; run plan again')
    if args.command=='play':
        validation=json.loads((args.directory/'route-validation.json').read_text())
        if (not validation.get('verified') or validation['planSha256']!=fingerprint(file)
                or validation['executionSha256']!=execution_fingerprint()
                or validation['catalogIdentity']!=identity(catalog)):
            raise ValueError('Route is unverified or code/plan/catalog changed; validate first')
        route=next(r for r in result['routes'] if r['id']==validation['selectedRoute'])
        if not route.get('continuation'):raise ValueError('Prepare a half-boundary continuation route before live play')
        from .browser import play
        atomic_json(args.directory/'session.json',{'route':route,'routeVersion':2,'planSha256':validation['planSha256']})
        return play(route,catalog,args.directory,args.directory/'control.json',browser=args.browser,
                    cdp_endpoint=args.cdp_endpoint,resume_current_game=args.resume_current_game,
                    finish_current_game=args.finish_current_game,restart_settled_game=args.restart_settled_game)
    before = execution_fingerprint()
    validation = rank(result, catalog, args.attempts, args.directory/'route-validation-cache', config['candidate_limit'])
    if validation.get('selectedRoute'):
        chosen=next(r for r in result['routes'] if r['id']==validation['selectedRoute'])
        continuation=chosen.get('continuation')
        if continuation:
            check=rank({'routes':[continuation]},catalog,args.attempts,args.directory/'continuation-validation-cache',1)
            check['entry']='synthetic-half-boundary-with-opening-residual'
            check['interpretation']='contract validation, not empirical post-target residual distribution'
            validation['continuationValidation']=check
            validation['verified']=validation['verified'] and check['verified']
    if before != execution_fingerprint():
        raise RuntimeError('Execution code changed during validation')
    validation.update(version=2, planSha256=fingerprint(file), executionSha256=before,
                      catalogIdentity=identity(catalog))
    atomic_json(args.directory/'route-validation.json', validation)
    event('route-validated', verified=validation['verified'], selectedRoute=validation['selectedRoute'])
    return validation


if __name__ == '__main__':
    main()
