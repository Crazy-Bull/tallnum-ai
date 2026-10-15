import unittest
from automation.no80_metrics import compact_record,compact_summary
from automation.validate_buffer_rescue import summary


class MetricsTests(unittest.TestCase):
    def test_template_counts_include_retries_and_rescues(self):
        record={'seed':1,'outcome':'success','reason':'','drops':30,'stage':4,
                'templateCalls':[{'cells':5,'target':64,'exit':'match','rescue':False},
                                 {'cells':5,'target':60,'exit':'buffer','rescue':True},
                                 {'cells':5,'target':64,'exit':'match','rescue':False}]}
        baseline={1:{'outcome':'success'}}
        actual=compact_summary([compact_record(record,baseline)],baseline)
        self.assertEqual(actual['templateCalls'],{'5:64:match':2,'5:60:buffer':1})
        self.assertEqual(actual['forbiddenTemplateCalls'],0)
        self.assertEqual(actual['successfulGameFive64Calls'],{'minimum':2,'maximum':2,'mean':2})

    def test_compact_statistics_preserve_all_decisions_and_paired_outcomes(self):
        records=[{'seed':1,'outcome':'success','reason':'','drops':30,'stage':4,
                  'liveSearch':[{'score':.9},{'score':.5,'error':'out-of-model-board','policy':'x','searchFallback':'legacy'}],
                  'bufferRescues':[{'outcome':'recovered'}],
                  'sixSingleExits':[{'strict':True,'tidy':True}]},
                 {'seed':2,'outcome':'failure','reason':'dead','drops':20,'stage':2,
                  'liveSearch':[{'score':.3},{'error':'other','policy':'y'}],
                  'bufferRescues':[{'outcome':'unavailable'}],
                  'sixSingleExits':[{'strict':True,'tidy':False}]}]
        baseline={1:{'outcome':'failure'},2:{'outcome':'success'}}
        expected=summary(records,baseline)
        compact=[compact_record(r,baseline) for r in records]
        self.assertTrue(all('liveSearch' not in r for r in compact))
        actual=compact_summary(compact,baseline)
        self.assertEqual({k:actual[k] for k in expected},expected)
        self.assertEqual(actual['unfinished'],0)


if __name__=='__main__':unittest.main()
