import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import generate_cpp
from loclib import sha

class GenerateCppTests(unittest.TestCase):
    def test_utf8_is_emitted_as_ascii_byte_escapes(self):
        out = generate_cpp.c_bytes('中文')
        self.assertTrue(out.isascii())
        self.assertNotIn('中', out)
        self.assertIn('\\', out)

    def test_render_header_uses_only_fresh_approved_translation_without_embedding_sources(self):
        catalog = {'entries': {
            'a': {'source':'Quality','source_hash':sha('Quality'),'obsolete':False},
            'b': {'source':'Changed','source_hash':sha('Changed'),'obsolete':False},
            'c': {'source':'Old','source_hash':sha('Old'),'obsolete':True},
        }}
        zh = {'entries': {
            'a': {'text':'质量','source_hash':sha('Quality'),'state':'reviewed'},
            'b': {'text':'已过期','source_hash':sha('Earlier'),'state':'reviewed'},
            'c': {'text':'旧','source_hash':sha('Old'),'state':'reviewed'},
        }}
        text = generate_cpp.render_header(catalog, zh)
        self.assertNotIn('Quality', text)
        self.assertNotIn('Changed', text)
        self.assertNotIn('"Old"', text)
        self.assertIn('\\350\\264\\250', text) # beginning of UTF-8 for 质量
        self.assertIn(f'0x{generate_cpp.fnv1a64("Quality"):016x}ULL', text)
        self.assertIn(f'0x{generate_cpp.fnv1a64("Changed"):016x}ULL', text)
        self.assertTrue(text.isascii())

    def test_fnv1a64_is_stable_for_runtime_lookup(self):
        self.assertEqual(generate_cpp.fnv1a64(''), 0xcbf29ce484222325)
        self.assertEqual(generate_cpp.fnv1a64('a'), 0xaf63dc4c8601ec8c)
        self.assertEqual(generate_cpp.fnv1a64('Quality'), generate_cpp.fnv1a64('Quality'))
        self.assertNotEqual(generate_cpp.fnv1a64('Quality'), generate_cpp.fnv1a64('quality'))

if __name__ == '__main__':
    unittest.main()
