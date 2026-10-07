"""Find a short, real-board bridge into an unchanged fixed policy.

Only one observed drop is consumed. The unseen replacement preview is checked
for every unlocked value before a bridge is accepted; it is never sampled.
"""
from copy import deepcopy
from . import game


def bridge_actions(state, fixed_ids):
    tower = state['tower']
    yield {'kind': 'edge'}
    if not any(t['kind'] == 'group' for t in tower):
        for start in range(len(tower) - 1):
            for end in range(start + 2, min(start + 5, len(tower)) + 1):
                if all(t['id'] not in fixed_ids for t in tower[start:end]):
                    yield {'kind': 'group', 'indices': list(range(start, end))}
    if state['queue'] and state['queue'][0] is not None:
        yield {'kind': 'up'}
        yield {'kind': 'down'}
        yield {'kind': 'drop'}


def find_entry_bridge(obs, fixed_ids, leaf, item, viable, *, depth=4, width=20,
                      max_states=600, max_queries=24):
    """Return fully checked actions, or None rather than a heuristic escape."""
    order = [t['id'] for t in obs['tower'] if t['id'] in fixed_ids]
    if not order or len(obs['queue']) != 2 or any(v is None for v in obs['queue']):
        return None
    initial_occupied = sum(t['physicalCount'] for t in obs['tower'] if t['id'] not in fixed_ids)
    frontier = [(deepcopy(obs), [], 0)]
    seen = {(tuple(game.signature(obs)), tuple(obs['queue']),
             tuple(t['id'] in fixed_ids for t in obs['tower']))}
    best = None
    queries = 0
    visited = 0
    for _ in range(depth):
        following = []
        for state, path, drops in frontier:
            for action in bridge_actions(state, fixed_ids):
                is_drop = action['kind'] in ('up', 'down', 'drop')
                if is_drop and drops >= 1:
                    continue
                if action['kind'] == 'edge' and item.get('matchEdgeGuard') and leaf['exit'] == 'match':
                    positions = [i for i, t in enumerate(state['tower']) if t['id'] in fixed_ids]
                    above = positions[-1] + 1
                    if above < len(state['tower']) and state['tower'][above]['value'] // 10 == leaf['target'] // 10:
                        continue
                try:
                    after = game.predict(state, action)
                except (ValueError, IndexError):
                    continue
                if after['gameOver']:
                    continue
                positions = [i for i, t in enumerate(after['tower']) if t['id'] in fixed_ids]
                if ([after['tower'][i]['id'] for i in positions] != order
                        or positions != list(range(positions[0], positions[-1] + 1))):
                    continue
                active = [t for t in after['tower'] if t['id'] not in fixed_ids]
                if any(t['value'] > item.get('maxValue', max(48, leaf['target'])) for t in active):
                    continue
                key = (tuple(game.signature(after)), tuple(after['queue']),
                       tuple(t['id'] in fixed_ids for t in after['tower']))
                if key in seen:
                    continue
                seen.add(key)
                visited += 1
                next_path = path + [action]
                next_drops = drops + is_drop
                occupied = sum(t['physicalCount'] for t in active)
                groups = sum(t['kind'] == 'group' for t in active)
                rank = (occupied, groups, next_drops, len(next_path))
                # Probe compact, clean entries first, preserving query budget
                # for the group -> rotation/drop -> EDGE cleanup successors.
                if (not groups and occupied < item.get('cells', 5)
                        and (occupied < initial_occupied or positions[0] == 0)
                        and (best is None or rank < best[0]) and queries < max_queries):
                    queries += 1
                    previews = (after['unlocked'] if after['queue'][1] is None
                                else [after['queue'][1]])
                    valid = True
                    for replacement in previews:
                        candidate = deepcopy(after)
                        candidate['queue'][1] = replacement
                        if not viable(candidate):
                            valid = False
                            break
                    if valid:
                        best = (rank, next_path, list(previews))
                following.append((rank, after, next_path, next_drops))
                if visited >= max_states:
                    break
            if visited >= max_states:
                break
        frontier = [(s, p, d) for _, s, p, d in sorted(following, key=lambda x: x[0])[:width]]
        if not frontier or visited >= max_states:
            break
    if best is None:
        return None
    return {'actions': best[1], 'rank': best[0], 'replacementPreviewsChecked': best[2],
            'visitedStates': visited, 'entryQueries': queries}
