"""Bounded-memory statistics; detailed decisions stay in each saved game."""
from collections import Counter
from .validate_buffer_rescue import summary


def compact_record(record,baseline):
    metrics=summary([record],baseline)
    scores=[e['score'] for e in record.get('liveSearch',[]) if isinstance(e.get('score'),(int,float))]
    metrics.update(scoreSum=sum(scores),scoreCount=len(scores))
    if 'handoffChecks' in record:metrics['nextEntryRejections']=len(record['handoffChecks'])
    if 'templateCalls' in record:
        calls=record['templateCalls']
        metrics['templateCalls']=dict(Counter(f"{c['cells']}:{c['target']}:{c['exit']}" for c in calls))
        metrics['five64Calls']=sum(c['cells']==5 and c['target']==64 for c in calls)
        metrics['forbiddenTemplateCalls']=sum(c['cells']<5 or c['target']<24
                                             or c['cells']==5 and c['target']>=80 for c in calls)
    return {k:record[k] for k in ('seed','outcome','reason','drops','stage')}|{'metrics':metrics}


def compact_summary(records,baseline):
    # The original summary supplies identical outcome/paired-seed fields.
    result=summary(records,baseline)
    additive=('rescueAttempts','rescueCompletions','rescueUnavailable','liveSearchDecisions',
              'outOfModelBoardGames','staticSearchFallbacks','sixSingleExits','sixSingleExitViolations')
    for key in additive:result[key]=sum(r['metrics'][key] for r in records)
    for key in ('searchErrors','searchErrorPolicies'):
        counter=Counter()
        for r in records:counter.update(r['metrics'][key])
        result[key]=dict(counter)
    count=sum(r['metrics']['scoreCount'] for r in records)
    result['meanSelectedPolicyProbability']=sum(r['metrics']['scoreSum'] for r in records)/count if count else None
    result['unfinished']=sum(r['outcome']=='limit' for r in records)
    if any('nextEntryRejections' in r['metrics'] for r in records):
        result['nextEntryRejections']=sum(r['metrics'].get('nextEntryRejections',0) for r in records)
    if any('templateCalls' in r['metrics'] for r in records):
        calls=Counter()
        for r in records:calls.update(r['metrics'].get('templateCalls',{}))
        result['templateCalls']=dict(calls)
        result['forbiddenTemplateCalls']=sum(r['metrics'].get('forbiddenTemplateCalls',0) for r in records)
        successes=[r['metrics']['five64Calls'] for r in records
                   if r['outcome']=='success' and 'five64Calls' in r['metrics']]
        result['successfulGameFive64Calls']={'minimum':min(successes),'maximum':max(successes),
            'mean':sum(successes)/len(successes)} if successes else None
    return result
