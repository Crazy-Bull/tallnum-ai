"""Headless Standard seven/ten-cell engine, pinned to site poolVersion=2.

Port of the observed public rules. RNG/hidden queue live only in this engine;
observation() exposes precisely the two visible previews to policy selection.
"""
from __future__ import annotations

from copy import deepcopy

POOL = [2, 4, 8, 6, 10, 15]  # site order matters for seeded parity


def physical(state):
    return sum(t['physicalCount'] for t in state['tower'])


def tile(state, value, **extra):
    state['nextId'] += 1
    return {'id': f"t{state['nextId']}", 'value': value, 'physicalCount': 1, 'kind': 'tile', **extra}


def draw(state):
    x = state['rngState'] or 0x6d2b79f5
    x ^= (x << 13) & 0xffffffff
    x ^= x >> 17
    x ^= (x << 5) & 0xffffffff
    state['rngState'] = x & 0xffffffff
    pool = [v for v in state['unlocked'] if state['repeatCount'] < 4 or v != state['lastRandomValue']]
    value = pool[int(state['rngState'] / 4294967296 * len(pool))]
    state['repeatCount'] = state['repeatCount'] + 1 if value == state['lastRandomValue'] else 1
    state['lastRandomValue'] = value
    return value


def merge(state, i, edge=False):
    tower = state['tower']
    value = (tower[i]['value']//10 if edge else tower[i]['value'])*2
    extra = {}
    if state.get('_trackSources'):
        extra['_sources'] = [s for t in tower[i:i+2] for s in t.get('_sources', [t['id']])]
    tower[i:i+2] = [tile(state, value, **extra)]


def normal(state):
    while True:
        match = next((i for i in range(len(state['tower'])-2, -1, -1)
                      if state['tower'][i]['value'] == state['tower'][i+1]['value']), None)
        if match is None:
            return
        merge(state, match)


def unlock(state):
    state.setdefault('unlocked', POOL[:])
    total = sum(t['value'] for t in state['tower'])
    for threshold, value in ((32, 6), (100, 10), (200, 15)):
        if total >= threshold and value not in state['unlocked']:
            state['unlocked'].append(value)


def new_game(seed, tower_limit=7):
    if tower_limit not in (7, 10):
        raise ValueError('Standard supports seven or ten cells')
    state = {'seed': seed, 'rngState': (seed & 0xffffffff) or 0x6d2b79f5, 'nextId': 0,
             'tower': [], 'queue': [2, 4], 'unlocked': POOL[:] if tower_limit == 7 else [2, 4, 8], 'numberSet': 'standard',
             'towerLimit': tower_limit, 'poolVersion': 2, 'lastRandomValue': None, 'repeatCount': 0,
             'actions': 0, 'drops': 0, 'gameOver': False, 'actionLog': []}
    state['queue'] += [draw(state), draw(state)]
    for _ in range(2):
        add_drop(state)
    return state


def add_drop(state, sample=True):
    value = state['queue'].pop(0)
    state['queue'].append(draw(state) if sample else None)
    state['tower'].append(tile(state, value))
    normal(state)
    unlock(state)


def apply(state, action, sample=True):
    if state['gameOver']:
        raise ValueError('Game is over')
    # Replay strings are immutable. Copy the list in C rather than walking
    # the entire growing replay with deepcopy for every simulated action.
    history = state.get('actionLog', [])
    state = deepcopy({k:v for k,v in state.items() if k!='actionLog'})
    state['actionLog'] = history.copy()
    tower = state['tower']
    kind = action['kind']
    if kind in ('up', 'down', 'drop'):
        if kind != 'drop':
            if len(tower) < 2:
                raise ValueError('Cannot rotate')
            if kind == 'up':
                tower.append(tower.pop(0))
            else:
                tower.insert(0, tower.pop())
            normal(state)
            unlock(state)
        # Actual website always drops even when the rotation itself merged.
        add_drop(state, sample)
        state['drops'] += 1
        state['gameOver'] = physical(state) >= state['towerLimit']
        code = {'up': 'u', 'down': 'n', 'drop': 'd'}[kind]
    elif kind == 'group':
        indices = action['indices']
        if (not 2 <= len(indices) <= 5 or indices != list(range(indices[0], indices[-1]+1))
                or indices[0] < 0 or indices[-1] >= len(tower)
                or any(t['kind'] == 'group' for t in tower)):
            raise ValueError('Illegal group')
        members = tower[indices[0]:indices[-1]+1]
        extra = {}
        if state.get('_trackSources'):
            extra['_sources'] = [s for t in members for s in t.get('_sources', [t['id']])]
        tower[indices[0]:indices[-1]+1] = [tile(state, sum(t['value'] for t in members),
            kind='group', physicalCount=sum(t['physicalCount'] for t in members), members=deepcopy(members),
            **extra)]
        normal(state)
        unlock(state)
        code = 'g:' + ','.join(map(str, indices))
    elif kind == 'edge':
        def pair(i):
            return tower[i]['value']//10 > 0 and tower[i]['value']//10 == tower[i+1]['value']//10
        if not any(pair(i) for i in range(len(tower)-1)):
            raise ValueError('No edge pairs')
        while any(pair(i) for i in range(len(tower)-1)):
            i = len(tower)-2
            while i >= 0:
                if pair(i):
                    merge(state, i, True)
                    i -= 1
                i -= 1
        normal(state)
        unlock(state)
        code = 'e'
    else:
        raise ValueError('Unknown action')
    state['actions'] += 1
    state.setdefault('actionLog', []).append(code)
    return state


def observation(state):
    result = {k: deepcopy(state[k]) for k in ('tower', 'numberSet', 'towerLimit', 'poolVersion', 'actions', 'drops', 'gameOver')} | {'queue': state['queue'][:2], 'unlocked': state.get('unlocked', POOL)[:]}
    for t in result['tower']:
        t.pop('_sources', None)
    return result


def signature(state):
    return [(t['value'], t['physicalCount'], t['kind']) for t in state['tower']]


def predict(obs, action):
    # Placeholder future previews cannot affect a single action's board.
    state = deepcopy(obs)
    state['_trackSources'] = True
    state.update(nextId=max([int(t['id'][1:]) for t in state['tower']]+[0]), actionLog=[])
    return apply(state, action, sample=False)
