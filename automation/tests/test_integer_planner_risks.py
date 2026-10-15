import unittest

from automation.integer_planner import execution_risks


class IntegerPlannerRiskTests(unittest.TestCase):
    def test_flags_early_five_cell_sixty_on_ten_cell_pool(self):
        step={'kind':'leaf','template':'5:60:single','before':[[96,1,False]]}
        self.assertEqual(execution_risks([step],10),[
            {'step':1,'template':'5:60:single','fixedTotal':96,'unlockThreshold':200}])
        self.assertEqual(execution_risks([step],7),[])
        self.assertEqual(execution_risks([{**step,'before':[[200,1,False]]}],10),[])


if __name__=='__main__':unittest.main()
