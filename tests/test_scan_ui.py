import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import scan_ui
from loclib import Candidate, sha

class ScanUiTests(unittest.TestCase):
    def c(self, source, line=1, callee='ImGui::Text'):
        return Candidate('OptiScaler/menu/menu_common.cpp',callee,0,source,0,1,line,'"x"',True)

    def test_exact_source_keeps_existing_key_and_reviewed_translation(self):
        old={'ui.custom.quality':{'source':'Quality','source_hash':sha('Quality'),'occurrences':[{'file':'OptiScaler/menu/menu_common.cpp','callee':'ImGui::Text'}],'obsolete':False,'previous_sources':[]}}
        zh={'locale':'zh-CN','entries':{'ui.custom.quality':{'text':'质量','state':'reviewed','source_hash':sha('Quality')}}}
        result=scan_ui.reconcile([self.c('Quality')], old, zh, {'Quality':'质量'})
        self.assertIn('ui.custom.quality',result.catalog_entries)
        self.assertEqual(result.zh_entries['ui.custom.quality']['text'],'质量')
        self.assertEqual(result.missing,[])

    def test_changed_source_preserves_old_key_and_creates_new_missing_key(self):
        old={'ui.custom.apply':{'source':'Apply changes','source_hash':sha('Apply changes'),'occurrences':[{'file':'OptiScaler/menu/menu_common.cpp','callee':'ImGui::Text'}],'obsolete':False,'previous_sources':[]}}
        zh={'locale':'zh-CN','entries':{'ui.custom.apply':{'text':'应用更改','state':'reviewed','source_hash':sha('Apply changes')}}}
        c=Candidate('OptiScaler/menu/menu_common.cpp','ImGui::Text',0,'Apply changes now',0,1,1,'"x"',True)
        result=scan_ui.reconcile([c], old, zh, {})
        new_key=scan_ui.key_for_source('Apply changes now')
        self.assertTrue(result.catalog_entries['ui.custom.apply']['obsolete'])
        self.assertEqual(result.catalog_entries[new_key]['source'],'Apply changes now')
        self.assertIn(new_key,result.missing)
        self.assertEqual(result.zh_entries['ui.custom.apply']['text'],'应用更改')

    def test_translation_memory_seeds_new_exact_source(self):
        result=scan_ui.reconcile([self.c('Balanced')], {}, {'locale':'zh-CN','entries':{}}, {'Balanced':'均衡'})
        key=next(iter(result.catalog_entries))
        self.assertEqual(result.zh_entries[key]['state'],'machine_translated')
        self.assertEqual(result.zh_entries[key]['text'],'均衡')
        self.assertEqual(result.missing,[])

    def test_removed_entry_becomes_obsolete(self):
        old={'ui.old':{'source':'Gone','source_hash':sha('Gone'),'occurrences':[],'obsolete':False,'previous_sources':[]}}
        result=scan_ui.reconcile([], old, {'locale':'zh-CN','entries':{}}, {})
        self.assertTrue(result.catalog_entries['ui.old']['obsolete'])
        self.assertEqual(result.removed,['ui.old'])

if __name__ == '__main__':
    unittest.main()

class DualChannelKeyTests(unittest.TestCase):
    def test_changed_source_gets_new_immutable_key(self):
        old_key='ui.auto.' + __import__('hashlib').sha1(b'Apply changes').hexdigest()[:12]
        old={old_key:{'source':'Apply changes','source_hash':sha('Apply changes'),'occurrences':[{'file':'OptiScaler/menu/menu_common.cpp','callee':'ImGui::Text'}],'obsolete':False,'previous_sources':[]}}
        zh={'locale':'zh-CN','entries':{old_key:{'text':'应用更改','state':'reviewed','source_hash':sha('Apply changes')}}}
        c=Candidate('OptiScaler/menu/menu_common.cpp','ImGui::Text',0,'Apply changes now',0,1,1,'"x"',True)
        result=scan_ui.reconcile([c], old, zh, {})
        new_key='ui.auto.' + __import__('hashlib').sha1(b'Apply changes now').hexdigest()[:12]
        self.assertIn(new_key,result.catalog_entries)
        self.assertTrue(result.catalog_entries[old_key]['obsolete'])
        self.assertIn(new_key,result.missing)
        self.assertTrue(any(row[0] == new_key and row[1] == 'Apply changes' for row in result.changed))
