import unittest

from automation import game
from automation.route_runtime import RouteExecutor


class DeadMatchWorker:
    def __init__(self, item):
        self.item = item

    def query(self, *args):
        if self.item['exit'] == 'buffer':
            return {'status': 'error', 'error': 'out-of-model-board'}
        return {'status': 'dead'}

    def close(self):
        pass


class BufferRescueTests(unittest.TestCase):
    def fixture(self, values):
        route = {'version': 2, 'kind': 'stages', 'cells': 10,
                 'target': 10240, 'initialPrefix': [],
                 'bufferRescuePolicies': {'32': ['buffer30']},
                 'steps': [
                     {'kind': 'leaf', 'target': 32, 'exit': 'single',
                      'policy': 'single32', 'policyCells': 6,
                      'before': [[256, 1, False]],
                      'after': [[256, 1, False], [32, 1, False]]},
                     {'kind': 'leaf', 'target': 32, 'exit': 'match',
                      'policy': 'match32', 'policyCells': 5,
                      'before': [[256, 1, False], [32, 1, False]],
                      'after': [[256, 1, False], [64, 1, False]]}]}
        catalog = {'policies': [
            {'id': 'single32', 'target': 32, 'exit': 'single',
             'cells': 6, 'maxGoalCells': 1},
            {'id': 'match32', 'target': 32, 'exit': 'match',
             'cells': 5, 'maxGoalCells': 5},
            {'id': 'buffer30', 'target': 30, 'exit': 'buffer',
             'cells': 5, 'maxGoalCells': 4, 'maxValue': 64}]}
        state = game.new_game(10)
        state['towerLimit'] = 10
        state['tower'] = [game.tile(state, value) for value in values]
        runner = RouteExecutor(route, catalog, DeadMatchWorker)
        runner.stage = 1
        runner.fixed_ids = {t['id'] for t in state['tower'] if t['value'] in (256, 32)}
        return runner, state

    def test_buffer_edge_consumes_anchor_and_rewinds_single(self):
        route = {'version': 2, 'kind': 'stages', 'cells': 10,
                 'target': 10240, 'initialPrefix': [[256, 1, False]],
                 'bufferRescuePolicies': {'32': ['buffer30']},
                 'steps': [
                     {'kind': 'leaf', 'target': 32, 'exit': 'single',
                      'policy': 'single32', 'policyCells': 6,
                      'before': [[256, 1, False]],
                      'after': [[256, 1, False], [32, 1, False]]},
                     {'kind': 'leaf', 'target': 32, 'exit': 'match',
                      'policy': 'match32', 'policyCells': 5,
                      'before': [[256, 1, False], [32, 1, False]],
                      'after': [[256, 1, False], [64, 1, False]]}]}
        catalog = {'policies': [
            {'id': 'single32', 'target': 32, 'exit': 'single',
             'cells': 6, 'maxGoalCells': 1},
            {'id': 'match32', 'target': 32, 'exit': 'match',
             'cells': 5, 'maxGoalCells': 5},
            {'id': 'buffer30', 'target': 30, 'exit': 'buffer',
             'cells': 5, 'maxGoalCells': 4, 'maxValue': 64}]}
        state = game.new_game(10)
        state['towerLimit'] = 10
        state['tower'] = [game.tile(state, value) for value in (256, 32, 30)]
        runner = RouteExecutor(route, catalog, DeadMatchWorker)
        try:
            before = game.observation(state)
            runner.bind_initial(before)
            runner.stage = 1
            runner.fixed_ids = {state['tower'][0]['id'], state['tower'][1]['id']}
            action = runner.next_action(before)
            self.assertEqual(action, {'kind': 'edge'})
            after = game.apply(state, action)
            runner.accept(before, action, game.observation(after))
            self.assertEqual(game.signature(after), [(256, 1, 'tile'), (6, 1, 'tile')])
            self.assertEqual(runner.stage, 0)
            self.assertEqual(runner.fixed_ids, {state['tower'][0]['id']})
            self.assertEqual(len(runner.buffer_rescue_events), 1)
        finally:
            runner.close()

    def test_risky_entry_rotates_ready_buffer_then_rewinds(self):
        runner, state = self.fixture((30, 256, 32))
        try:
            before = game.observation(state)
            action = runner.next_action(before)
            self.assertEqual(action, {'kind': 'up'})
            state = game.apply(state, action)
            runner.accept(before, action, game.observation(state))
            before = game.observation(state)
            action = runner.next_action(before)
            self.assertEqual(action, {'kind': 'edge'})
            state = game.apply(state, action)
            runner.accept(before, action, game.observation(state))
            self.assertEqual(runner.stage, 0)
            self.assertEqual(state['tower'][0]['value'], 256)
            self.assertEqual(state['tower'][1]['value'], 6)
        finally:
            runner.close()

    def test_risky_entry_with_upper_residual_keeps_normal_route(self):
        runner, state = self.fixture((30, 256, 32, 8))
        try:
            action = runner.next_action(game.observation(state))
            self.assertEqual(action, {'kind': 'drop'})
            self.assertEqual(runner.failure_reason, 'fixed-policy-dead')
        finally:
            runner.close()

    def test_match_chain_rescue_rewinds_to_chain_start(self):
        route = {'version': 2, 'kind': 'stages', 'cells': 10,
                 'target': 10240, 'initialPrefix': [[256, 1, False]],
                 'bufferRescuePolicies': {'80': ['buffer84']},
                 'steps': [
                     {'kind': 'leaf', 'target': 40, 'exit': 'single',
                      'before': [[256, 1, False]],
                      'after': [[256, 1, False], [40, 1, False]]},
                     {'kind': 'leaf', 'target': 40, 'exit': 'match',
                      'before': [[256, 1, False], [40, 1, False]],
                      'after': [[256, 1, False], [80, 1, False]]},
                     {'kind': 'leaf', 'target': 80, 'exit': 'match',
                      'policyCells': 5, 'policy': 'match80',
                      'before': [[256, 1, False], [80, 1, False]],
                      'after': [[256, 1, False], [160, 1, False]]}]}
        catalog = {'policies': [
            {'id': 'match80', 'target': 80, 'exit': 'match',
             'cells': 5, 'maxGoalCells': 5},
            {'id': 'buffer84', 'target': 84, 'exit': 'buffer',
             'cells': 5, 'maxGoalCells': 4, 'maxValue': 84}]}
        state = game.new_game(10)
        state['towerLimit'] = 10
        state['tower'] = [game.tile(state, value) for value in (256, 80, 84)]
        runner = RouteExecutor(route, catalog, DeadMatchWorker)
        try:
            before = game.observation(state)
            runner.bind_initial(before)
            runner.stage = 2
            runner.fixed_ids = {state['tower'][0]['id'], state['tower'][1]['id']}
            action = runner.next_action(before)
            self.assertEqual(action, {'kind': 'edge'})
            state = game.apply(state, action)
            runner.accept(before, action, game.observation(state))
            self.assertEqual(runner.stage, 0)
            self.assertEqual(runner.buffer_rescue_events[0]['toStage'], 0)
            self.assertEqual(game.signature(state), [(256, 1, 'tile'), (16, 1, 'tile')])
        finally:
            runner.close()


if __name__ == '__main__':
    unittest.main()
