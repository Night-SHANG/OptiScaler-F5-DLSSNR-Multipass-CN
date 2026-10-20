import sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import translate_missing
from loclib import sha

class TranslateMissingTests(unittest.TestCase):
    def test_reviewed_translation_is_never_overwritten_even_if_pending_is_misclassified(self):
        entries={'k':{'text':'人工','source_hash':sha('Old'),'state':'reviewed'}}
        item={'key':'k','source':'New','source_hash':sha('New')}
        translate_missing.apply_translation(entries,'missing',item,'机器','model-x')
        self.assertEqual(entries['k']['text'],'人工')
        self.assertEqual(entries['k']['state'],'reviewed')
        self.assertEqual(entries['k']['candidate']['text'],'机器')
        self.assertEqual(entries['k']['candidate']['source_hash'],sha('New'))

    def test_machine_translation_can_update_unreviewed_entry(self):
        entries={'k':{'text':'旧机器','source_hash':sha('Old'),'state':'machine_translated'}}
        item={'key':'k','source':'New','source_hash':sha('New')}
        translate_missing.apply_translation(entries,'changed',item,'新机器','model-x')
        self.assertEqual(entries['k']['text'],'新机器')
        self.assertEqual(entries['k']['state'],'machine_translated')
        self.assertEqual(entries['k']['source_hash'],sha('New'))

if __name__=='__main__': unittest.main()
