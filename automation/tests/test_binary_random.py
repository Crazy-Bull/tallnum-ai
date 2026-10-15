import unittest
from automation import game
from automation.binary_random import initial_state


class BinaryRandomTests(unittest.TestCase):
    def test_real_opening_preserves_rng_queue_and_locked_pool(self):
        for seed in (1,1121083590,4294967295):
            actual=initial_state(seed,10)
            self.assertEqual(actual,game.new_game(seed,10))
            self.assertEqual(len(game.observation(actual)['queue']),2)
            self.assertEqual(len(actual['queue']),4)
            self.assertEqual(actual['unlocked'],[2,4,8])
            after=game.apply(actual,{'kind':'drop'})
            self.assertEqual(after,game.apply(game.new_game(seed,10),{'kind':'drop'}))

    def test_diagnostic_checkpoint_does_not_change_real_opening(self):
        state=initial_state(123,10,10)
        self.assertEqual(game.signature(state),[(10,1,'tile')])
        self.assertEqual(state['unlocked'],game.POOL)
        self.assertEqual(game.signature(initial_state(123,10)),[(2,1,'tile'),(4,1,'tile')])


if __name__=='__main__':unittest.main()
