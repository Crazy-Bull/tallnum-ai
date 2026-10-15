import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from automation.no80_migration import migrate


class MigrationTests(unittest.TestCase):
    def test_dirty_model_requires_replacement_and_opening_is_preserved(self):
        prefix={'kind':'group','before':[], 'after':[[5120,1,False]]}
        step={'kind':'leaf','policy':'dirty','policyCells':5,'template':'5:64:single',
              'target':64,'exit':'single','before':[[5120,1,False]],
              'after':[[5120,1,False],[64,1,False]]}
        route={'steps':[prefix,step]}
        item={'id':'dirty','cells':5,'target':64,'exit':'single','table':'dirty',
              'bases':[1,3,5,15]}
        replacement={**item,'id':'clean','table':'clean','maxValue':64,
                     'successNoExtraCombos':True}
        with tempfile.TemporaryDirectory() as directory:
            evidence=Path(directory)
            (evidence/'route.json').write_text(json.dumps({'steps':[prefix]}))
            with patch('automation.no80_migration.EVIDENCE',evidence),patch(
                    'automation.no80_migration.table_header',
                    side_effect=lambda p:{'successNoExtraCombos':p=='clean'}):
                with self.assertRaisesRegex(ValueError,'Missing clean replacement'):
                    migrate(route,{'policies':[item]},[])
                result,catalog,report=migrate(route,{'policies':[item]},[replacement])
                self.assertEqual(result['steps'][0],prefix)
                self.assertEqual(result['steps'][1]['policy'],'clean')
                self.assertEqual(route['steps'][1]['policy'],'dirty')
                self.assertEqual([p['id'] for p in catalog['policies']],['clean'])
                self.assertEqual(report['preservedPrefixSteps'],1)
                self.assertEqual(report['wholeGameSuccessRate'],None)
                result['steps'][0]={**prefix,'before':[[2,1,False]]}
                with self.assertRaisesRegex(ValueError,'opening/prefix changed'):
                    migrate(result,catalog,[replacement])


if __name__=='__main__':unittest.main()
