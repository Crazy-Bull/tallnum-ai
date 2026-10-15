import itertools
import unittest

from automation.endgame_peak import BIG, INF, search, solve


class EndgamePeakTests(unittest.TestCase):
    def test_small_grammar_matches_exhaustive_tree_enumeration(self):
        leaves, peak, slots = (2, 4, 6), 6, 2
        memory = {}

        def enumerate_cost(n, s):
            if (n, s) in memory:
                return memory[n, s]
            answer = BIG*(n == peak)+1 if n in leaves else INF
            if n % 2 == 0 and s < slots:
                half = n//2
                first = enumerate_cost(half, s)
                for k in range(1, min(5, slots-s)+1):
                    for parts in itertools.product(range(2, half+1), repeat=k):
                        if sum(parts) != half:
                            continue
                        answer = min(answer, first+sum(enumerate_cost(v, s+i+1)
                                                      for i,v in enumerate(parts)))
            memory[n, s] = answer
            return answer

        for goal in range(2, 33, 2):
            expected = enumerate_cost(goal, 0)
            actual = solve(goal, 7, peak, leaves)
            if expected == INF:
                self.assertIsNone(actual)
            else:
                self.assertEqual(actual['targetCounts'].get(6, 0)*BIG+actual['totalCalls'], expected)

    def test_ten_8192_standard_peak_and_peak_count(self):
        result = search(8192)
        self.assertEqual((result['endgamePeak'], result['peakCalls']), (64, 4))
        self.assertFalse(result['optimalityInFullGameProven'])
        self.assertIn(60, result['excludedPeaks'])

    def test_unknown_nonstandard_contracts_do_not_prove_game_optimum(self):
        result = search(8192, family='all-even')
        self.assertEqual((result['endgamePeak'], result['peakCalls']), (54, 4))
        self.assertFalse(result['leafPoliciesVerified'])
        self.assertFalse(result['optimalityInFullGameProven'])

    def test_odd_fifteen_is_sorted_before_sixteen(self):
        result = search(30, family='all-even')
        self.assertEqual((result['endgamePeak'], result['peakCalls']), (15, 2))


if __name__ == '__main__':
    unittest.main()
