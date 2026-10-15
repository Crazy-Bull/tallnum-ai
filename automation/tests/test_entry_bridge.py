import unittest
from automation import game
from automation.route_runtime import RouteExecutor
from automation.entry_bridge import find_entry_bridge


class EntryBridgeTests(unittest.TestCase):
    def fixture(self):
        state = game.new_game(2868527136, 10)
        state['tower'] = [game.tile(state, v) for v in (4, 6, 4, 5120, 960, 640, 256, 32)]
        state['queue'] = [15, 8, 4, 4]
        prefix = [[v, 1, False] for v in (5120, 960, 640, 256, 32)]
        leaf = {'kind': 'leaf', 'before': prefix, 'after': prefix[:-1] + [[64, 1, False]],
                'target': 32, 'exit': 'match', 'policy': 'p', 'policyCells': 5}
        item = {'id': 'p', 'target': 32, 'exit': 'match', 'cells': 5, 'maxValue': 64,
                'matchEdgeGuard': True}
        return state, leaf, item

    def test_recorded_entry_groups_before_alignment_and_clears_combo(self):
        queried = []
        class Worker:
            def __init__(self, item): pass
            def query(self, board, fpos, queue):
                queried.append(([(t['value'], t['physicalCount']) for t in board], fpos, queue[:]))
                self_test.assertNotIn(None, queue)
                if fpos:
                    return {'status': 'error', 'error': 'out-of-model-board'}
                if [t['value'] for t in board] == [2]:
                    return {'status': 'ok', 'success': False, 'ops': [{'kind': 'drop'}]}
                return {'status': 'dead'}
            def close(self): pass
        self_test = self
        state, leaf, item = self.fixture()
        executor = RouteExecutor({'version': 2, 'kind': 'stages', 'cells': 10,
                                  'target': 10240, 'steps': [leaf]}, {'policies': [item]}, Worker)
        executor.fixed_ids = {t['id'] for t in state['tower'][3:]}
        fixed = executor.fixed_ids.copy()
        drops = state['drops']
        for expected in ({'kind': 'group', 'indices': [0, 1, 2]}, {'kind': 'up'}, {'kind': 'edge'}):
            before = game.observation(state)
            action = executor.next_action(before)
            self.assertEqual(action, expected)
            state = game.apply(state, action)
            executor.accept(before, action, game.observation(state))
            self.assertTrue(fixed <= {t['id'] for t in state['tower']})
            self.assertIsNone(executor.failure_reason)
        self.assertEqual(game.physical(state), 6)
        self.assertEqual([t['value'] for t in state['tower']], [5120, 960, 640, 256, 32, 2])
        self.assertFalse(any(t['kind'] == 'group' for t in state['tower']))
        self.assertEqual(state['drops'], drops + 1)
        checked = [q[1] for board, pos, q in queried if pos == 0 and board == [(2, 1)]]
        self.assertEqual(set(checked), set(state['unlocked']))
        executor.close()

    def test_unknown_replacement_must_be_valid_for_every_visible_pool_value(self):
        state, leaf, item = self.fixture()
        fixed = {t['id'] for t in state['tower'][3:]}
        def viable(obs):
            active = [t for t in obs['tower'] if t['id'] not in fixed]
            return [t['value'] for t in active] == [2] and obs['queue'][1] != 15
        self.assertIsNone(find_entry_bridge(game.observation(state), fixed, leaf, item, viable))

    def test_hidden_queue_and_rng_do_not_influence_the_bridge(self):
        state, leaf, item = self.fixture()
        fixed = {t['id'] for t in state['tower'][3:]}
        def viable(obs):
            return [t['value'] for t in obs['tower'] if t['id'] not in fixed] == [2]
        first = find_entry_bridge(game.observation(state), fixed, leaf, item, viable)
        state['queue'][2:] = [10, 15]
        state['rngState'] = 999
        second = find_entry_bridge(game.observation(state), fixed, leaf, item, viable)
        self.assertIsNotNone(first)
        self.assertEqual(first, second)


if __name__ == '__main__':
    unittest.main()
