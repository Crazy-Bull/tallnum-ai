import unittest
from automation import game
from automation.opening128_40 import ContractExecutor
from automation.single_six import use_single_six


class SingleSixTests(unittest.TestCase):
    def test_conversion_binds_every_six_match_to_single_and_preserves_five(self):
        single = {'id': 'six-single', 'cells': 6, 'exit': 'single', 'target': 40,
                  'successNoExtraCombos': True}
        alias = {**single, 'id': 'six-match', 'exit': 'match', 'workerKey': single['id']}
        five = {'id': 'five-match', 'cells': 5, 'exit': 'match', 'target': 40}
        before, after = [[40, 1, False]], [[80, 1, False]]
        route = {'steps': [
            {'kind': 'leaf', 'policy': alias['id'], 'target': 40, 'exit': 'match',
             'policyCells': 6, 'template': '6:40:match', 'before': before, 'after': after},
            {'kind': 'leaf', 'policy': five['id'], 'target': 40, 'exit': 'match',
             'policyCells': 5, 'template': '5:40:match', 'before': before, 'after': after}]}
        converted, catalog = use_single_six(route, {'policies': [single, alias, five]})
        self.assertEqual(converted['steps'][0]['exit'], 'single')
        self.assertEqual(converted['steps'][0]['policy'], single['id'])
        self.assertEqual(converted['steps'][0]['singleConnectionAfter'], after)
        self.assertEqual(converted['steps'][1], route['steps'][1])
        self.assertEqual({p['id'] for p in catalog['policies']}, {single['id'], five['id']})
        self.assertEqual(route['steps'][0]['exit'], 'match')

    def execute(self, values, queue, expected, ops, residual_group=False):
        class Worker:
            def __init__(self, item):
                self.item = item
            def query(self, *args):
                return {'status': 'ok', 'success': False, 'ops': ops}
            def close(self):
                pass
        state = game.new_game(1, 10)
        state['tower'] = [game.tile(state, v) for v in values]
        if residual_group:
            group = game.tile(state, 21, kind='group', physicalCount=2)
            state['tower'].insert(0, group)
        state['queue'] = queue
        anchor = next(t for t in state['tower'] if t['value'] == 40)
        before_contract = [[40, 1, False]]
        leaf = {'kind': 'leaf', 'target': 40, 'exit': 'single', 'policy': 'single',
                'policyCells': 6, 'before': before_contract, 'after': expected,
                'singleConnectionAfter': expected}
        route = {'version': 2, 'kind': 'stages', 'target': -1, 'cells': 10,
                 'initialPrefix': before_contract, 'completionContract': expected, 'steps': [leaf]}
        item = {'id': 'single', 'target': 40, 'exit': 'single', 'cells': 6,
                'maxGoalCells': 1, 'successNoExtraCombos': True}
        executor = ContractExecutor(route, {'policies': [item]}, Worker)
        executor.fixed_ids = {anchor['id']}
        executor.initial_bound = True
        obs = game.observation(state)
        action = executor.next_action(obs)
        after = game.apply(state, action)
        executor.accept(obs, action, game.observation(after))
        return executor, after

    def test_single_macro_accepts_exact_automatic_merge_before_model_success(self):
        executor, after = self.execute((40, 20, 10), [10, 2, 4, 6], [[80, 1, False]],
                                       [{'kind': 'drop'}, {'kind': 'edge'}])
        self.assertIsNone(executor.failure_reason)
        self.assertEqual(game.signature(after), [(80, 1, 'tile')])
        self.assertIsNone(executor.next_action(game.observation(after)))
        self.assertEqual(executor.stage, 1)
        executor.close()

    def test_single_connection_rejects_wrong_prefix_contract(self):
        executor, after = self.execute((40, 20, 10), [10, 2, 4, 6], [[160, 1, False]],
                                       [{'kind': 'drop'}])
        self.assertEqual(executor.failure_reason, 'fixed-policy-action-would-merge-protected-segment')
        self.assertEqual(executor.stage, 0)
        executor.close()

    def test_single_connection_rejects_an_extra_group(self):
        executor, after = self.execute((40, 20, 10), [10, 2, 4, 6], [[80, 1, False]],
                                       [{'kind': 'drop'}], residual_group=True)
        self.assertEqual(executor.failure_reason, 'fixed-policy-action-would-merge-protected-segment')
        self.assertEqual(executor.stage, 0)
        executor.close()

    def test_existing_single_goal_with_extra_group_is_not_a_clean_victory(self):
        class Worker:
            def __init__(self, item):
                pass
            def query(self, *args):
                return {'status': 'dead'}
            def close(self):
                pass
        from automation.runtime import Executor
        state = game.new_game(1, 10)
        state['tower'] = [game.tile(state, 80), game.tile(state, 32),
                          game.tile(state, 21, kind='group', physicalCount=2)]
        item = {'id': 'single', 'target': 32, 'exit': 'single', 'cells': 6,
                'maxGoalCells': 1, 'successNoExtraCombos': True}
        leaf = {'kind': 'leaf', 'target': 32, 'exit': 'single', 'policy': 'single', 'policyCells': 6}
        executor = Executor({'target': -1, 'towerLimit': 10, 'kind': 'stage', 'children': [leaf]},
                            {'policies': [item]}, Worker)
        executor.fixed_ids = {state['tower'][0]['id']}
        executor.next_action(game.observation(state))
        self.assertEqual(executor.failure_reason, 'fixed-policy-dead')
        self.assertEqual(executor.stage, 0)
        executor.close()


if __name__ == '__main__':
    unittest.main()
