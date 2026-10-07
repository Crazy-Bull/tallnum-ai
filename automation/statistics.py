"""Absorption probabilities and conditional first moments for a fixed policy.

Closed nonterminal classes are separate from finite failure. Terminal edge
costs are supplied by native macro recovery, including a final successful drop.
"""
from __future__ import annotations

import struct
import numpy as np
from scipy import sparse
from scipy.sparse.csgraph import connected_components
from scipy.sparse.linalg import bicgstab, lgmres, spsolve


def evaluate(kind, cost, next_states, initial=None, tolerance=1e-9, max_iterations=20000):
    kind = np.asarray(kind, dtype=np.uint8)
    cost = np.asarray(cost, dtype=float)
    next_states = np.asarray(next_states, dtype=np.int64)
    n = len(kind)
    if cost.shape != (n,) or next_states.shape != (n, 6) or np.any(kind > 2) or np.any(cost < 0):
        raise ValueError('Invalid fixed-policy graph')
    if not np.all(np.isfinite(cost)):
        raise ValueError('Invalid costs')
    initial = np.arange(min(36, n)) if initial is None else np.asarray(initial, dtype=np.int64)
    if not len(initial) or np.any(initial < 0) or np.any(initial >= n):
        raise ValueError('Invalid entry states')
    live = np.flatnonzero(kind == 0)
    if np.any(next_states[live] < 0) or np.any(next_states[live] >= n):
        raise ValueError('Invalid successor')
    rows = np.repeat(live, 6)
    cols = next_states[live].ravel()
    edges = sparse.csr_matrix((np.ones(len(rows), dtype=np.uint8), (rows, cols)), shape=(n, n))
    count, labels = connected_components(edges, directed=True, connection='strong')
    closed = np.ones(count, dtype=bool)
    cross = labels[rows] != labels[cols]
    closed[labels[rows[cross]]] = False
    # Terminal nodes are intentionally isolated SCCs, not infinite loops.
    closed[labels[kind != 0]] = False
    trap = closed[labels] & (kind == 0)
    transient = np.flatnonzero((kind == 0) & ~trap)
    index = np.full(n, -1, dtype=np.int64)
    index[transient] = np.arange(len(transient))
    successors = next_states[transient]
    mapped = index[successors]
    rr = np.repeat(np.arange(len(transient)), 6)
    keep = mapped.ravel() >= 0
    q = sparse.csr_matrix((np.full(np.count_nonzero(keep), 1/6),
                          (rr[keep], mapped.ravel()[keep])), shape=(len(transient), len(transient)))
    a = sparse.eye(len(transient), format='csr') - q
    residuals = []

    def solve(rhs):
        if not len(rhs):
            return np.empty(0)
        if not np.any(rhs):
            return np.zeros_like(rhs)
        if len(rhs) < 50000:
            x = spsolve(a, rhs)
        else:
            # Iterative solvers stop on an L2 criterion; the acceptance check
            # below uses maximum component error. Refine from the current
            # solution when the former passes but the latter does not.
            x = None
            bound = tolerance * 10 * max(1., float(np.max(np.abs(rhs))))
            for refinement in range(4):
                precision = tolerance * 0.1**refinement
                x, info = bicgstab(a, rhs, x0=x, rtol=precision,
                                  atol=precision*0.01, maxiter=max_iterations)
                if info != 0:
                    x, info = lgmres(a, rhs, x0=x, rtol=precision, atol=precision*0.01,
                                     maxiter=max_iterations, inner_m=30)
                if info != 0:
                    raise RuntimeError(f'Moment solver did not converge: {info}')
                if not np.all(np.isfinite(x)):
                    raise RuntimeError('Nonfinite moment solution')
                if float(np.max(np.abs(a @ x - rhs))) <= bound:
                    break
        residual = float(np.max(np.abs(a @ x - rhs)))
        residuals.append(residual)
        if not np.all(np.isfinite(x)) or residual > tolerance * 10 * max(1., float(np.max(np.abs(rhs)))):
            raise RuntimeError(f'Invalid moment solution; residual={residual}')
        return x

    def probability(boundary):
        out = boundary.astype(float)
        out[transient] = solve(out[successors].mean(axis=1))
        if np.any(out < -1e-7) or np.any(out > 1+1e-7):
            raise RuntimeError('Probability outside [0,1]')
        return np.clip(out, 0, 1)

    success = probability(kind == 1)
    failure = probability(kind == 2)
    nontermination = probability(trap)

    def moment(prob, boundary_kind):
        out = np.where(kind == boundary_kind, cost, 0.)
        # E[(c + remaining cost) 1_outcome] = c P(outcome) + Q moment.
        out[transient] = solve(cost[transient]*prob[transient] + out[successors].mean(axis=1))
        if np.any(out < -1e-7):
            raise RuntimeError('Negative first moment')
        return np.maximum(out, 0)

    u = moment(success, 1)
    v = moment(failure, 2)
    p, f, loop, um, vm = [float(x[initial].mean()) for x in (success, failure, nontermination, u, v)]
    # Determine reachability structurally: never discard a tiny positive trap
    # probability merely because it falls beneath the linear solver tolerance.
    seen = np.zeros(n, dtype=bool)
    stack = list(map(int, initial))
    while stack:
        s = stack.pop()
        if seen[s]:
            continue
        seen[s] = True
        if kind[s] == 0:
            stack.extend(int(t) for t in next_states[s] if not seen[t])
    usable = not bool(np.any(trap & seen))
    return {'p': p, 'u': um, 'v': vm, 'failureProbability': f,
            'nonterminationProbability': loop, 'usable': usable,
            'successDrops': um/p if p else None,
            'failureDrops': vm/f if f else None,
            'expectedTotalDrops': (um+vm)/p if usable and p else None,
            'maxResidual': max(residuals, default=0), 'states': n,
            'entry': 'uniform-first-36', 'model': 'iid-six-original-table',
            'infiniteExpectedDuration': not usable}


def evaluate_file(path, **kwargs):
    with open(path, 'rb') as f:
        if f.read(8) != b'TNGRAPH1':
            raise ValueError('Unknown graph format')
        n, = struct.unpack('<Q', f.read(8))
    kind = np.memmap(path, mode='r', dtype='u1', offset=16, shape=(n,))
    cost = np.memmap(path, mode='r', dtype='u1', offset=16+n, shape=(n,))
    nxt = np.memmap(path, mode='r', dtype='<u4', offset=16+2*n, shape=(n, 6))
    from pathlib import Path
    if Path(path).stat().st_size != 16 + 26*n:
        raise ValueError('Graph size mismatch')
    return evaluate(kind, cost, nxt, **kwargs)
