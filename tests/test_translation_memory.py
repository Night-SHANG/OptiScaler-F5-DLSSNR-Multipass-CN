import sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import update_translation_memory
from loclib import sha

class TranslationMemoryTests(unittest.TestCase):
    def test_only_fresh_reviewed_entries_enter_memory(self):
        cat={'entries':{
            'reviewed':{'source':'Quality','source_hash':sha('Quality'),'obsolete':False},
            'machine':{'source':'Balanced','source_hash':sha('Balanced'),'obsolete':False},
            'stale':{'source':'New source','source_hash':sha('New source'),'obsolete':False},
        }}
        zh={'entries':{
            'reviewed':{'text':'质量','state':'reviewed','source_hash':sha('Quality')},
            'machine':{'text':'均衡','state':'machine_translated','source_hash':sha('Balanced')},
            'stale':{'text':'旧文本','state':'reviewed','source_hash':sha('Old source')},
        }}
        result=update_translation_memory.merged_memory({'Existing':'已有'},cat,zh)
        self.assertEqual(result,{'Existing':'已有','Quality':'质量'})

if __name__=='__main__': unittest.main()
