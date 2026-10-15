"""Train a fixed five-cell policy for the numbers currently unlocked in a game.

The transition table still contains all six preview outcomes; zero-weight
outcomes remain represented so that a policy can be queried after an unlock.
"""
from __future__ import annotations

import argparse
import json
import mmap
from pathlib import Path
import struct

import numpy as np


SPAWNS = (2, 4, 6, 8, 10, 15)
INVALID = 0xffffffff
CODE = struct.Struct('<QBI')


def table_arrays(path):
    with Path(path).open('rb') as stream:
        data = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            if data[:8] != b'TALLTRN4':
                raise ValueError('Expected a TALLTRN4 table')
            version, cells, target, states, span, above, nbase = struct.unpack_from('<IIIQIII', data, 8)
            if version != 4 or cells != 5 or not above:
                raise ValueError('Requires a current five-cell table')
            cursor = 8 + struct.calcsize('<IIIQIII') + 4*nbase
            codes = np.empty(states, dtype=np.uint64)
            flags = np.empty(states, dtype=np.uint8)
            offsets = np.empty(states+1, dtype=np.uint32)
            posts = []
            for sid in range(states):
                code, flag, count = CODE.unpack_from(data, cursor)
                codes[sid] = code
                flags[sid] = flag
                offsets[sid] = len(posts)
                cursor += CODE.size
                if count:
                    posts.extend(np.frombuffer(data, dtype='<u8', count=count, offset=cursor))
                    cursor += count*8
            offsets[-1] = len(posts)
            if cursor > len(data):
                raise ValueError('Truncated table')
            post = np.asarray(posts, dtype=np.uint64)
        finally:
            data.close()
    prefixes = codes & np.uint64((1 << 57)-1)
    unique, inverse = np.unique(prefixes, return_inverse=True)
    q2 = ((codes >> np.uint64(57)) & np.uint64(7)).astype(np.uint8)
    groups = np.full((len(unique), 6), INVALID, dtype=np.uint32)
    groups[inverse, q2] = np.arange(states, dtype=np.uint32)
    if (groups == INVALID).any():
        raise ValueError('Incomplete preview groups')
    gids = np.searchsorted(unique, post).astype(np.uint32)
    if not np.array_equal(unique[gids], post):
        raise ValueError('Unknown transition prefix')
    return {'cells':cells,'target':target,'states':states,'span':span,
            'groups':groups,'actions':gids,'offsets':offsets,'flags':flags}


def solve(table, pool, rounds=500, tolerance=1e-10):
    mdp = table_arrays(table)
    weights = np.asarray([int(x in pool) for x in SPAWNS], dtype=np.float64)
    weights /= weights.sum()
    groups, actions, offsets = mdp['groups'], mdp['actions'], mdp['offsets']
    flags = mdp['flags']
    values = np.zeros(mdp['states'], dtype=np.float64)
    nonempty = np.flatnonzero(offsets[1:] > offsets[:-1])
    success = np.flatnonzero(flags & 1)
    for iteration in range(1, rounds+1):
        means = np.zeros(len(groups), dtype=np.float64)
        for i, weight in enumerate(weights):
            if weight: means += weight*values[groups[:,i]]
        action_values = means[actions]
        nxt = np.zeros_like(values)
        nxt[nonempty] = np.maximum.reduceat(action_values, offsets[nonempty])
        nxt[success] = 1
        delta = np.max(np.abs(values-nxt))
        values = nxt
        if iteration % 25 == 0 or delta < tolerance:
            print(json.dumps({'iteration':iteration,'delta':float(delta),
                              'openingValue':float(values[1])}), flush=True)
        if delta < tolerance: break
    means = np.zeros(len(groups), dtype=np.float64)
    for i, weight in enumerate(weights):
        if weight: means += weight*values[groups[:,i]]
    action_values = means[actions]
    best = np.full(mdp['states'], 0xfffffffe, dtype=np.uint32)
    # Stable ties: the native exporter also chooses the first best action.
    for sid in nonempty:
        begin,end = int(offsets[sid]),int(offsets[sid+1])
        best[sid] = int(np.argmax(action_values[begin:end]))
    best[success] = 0xffffffff
    return best, {'target':mdp['target'],'states':mdp['states'],'pool':list(pool),
                  'iterations':iteration,'delta':float(delta),
                  'emptyBoardFirst2Then4Value':float(values[1]),
                  'drawModel':'fixed unlocked pool, independent uniform draws'}


def write_policy(reference, output, choices):
    reference = Path(reference)
    with reference.open('rb') as stream:
        if stream.read(8) != b'TALLPOL4':
            raise ValueError('Expected a matching TALLPOL4 policy')
        stream.seek(8)
        version,cells,target,states,span,above,nbase = struct.unpack('<IIIQIII',stream.read(32))
        if version != 4 or cells != 5 or len(choices) != states:
            raise ValueError('Reference policy does not match transition table')
        header_length = 8+32+4*nbase+8
        stream.seek(0)
        header = stream.read(header_length)
    output = Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('wb') as stream:
        stream.write(header)
        stream.write(choices.astype('<u4',copy=False).tobytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('table',type=Path)
    parser.add_argument('reference_policy',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--pool',required=True,help='Comma-separated unlocked draw values')
    parser.add_argument('--rounds',type=int,default=500)
    args = parser.parse_args()
    pool = tuple(int(x) for x in args.pool.split(','))
    if not pool or any(x not in SPAWNS for x in pool):parser.error('Invalid pool')
    choices, summary = solve(args.table,pool,args.rounds)
    write_policy(args.reference_policy,args.output,choices)
    args.output.with_suffix('.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary),flush=True)


if __name__=='__main__':main()
