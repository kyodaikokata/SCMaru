import hashlib
import json
import unittest
from urllib.error import HTTPError
from urllib.request import build_opener, ProxyHandler

# Local fixture requests must never use a user's system HTTP proxy.
_opener = build_opener(ProxyHandler({}))
def urlopen(url):
    return _opener.open(url, timeout=5)

import fonts
from overlay import Overlay, PAGE, REVISION, normalize_effects


class OverlayTests(unittest.TestCase):
    def test_font_assets_and_licenses_are_complete(self):
        self.assertEqual(len(fonts.families()), 8)
        for entry in fonts.entries():
            raw = (fonts.ROOT / entry['file']).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), entry['sha256'])
            self.assertTrue((fonts.ROOT / entry['license']).is_file())
        self.assertIn('font-weight:100 900', fonts.css())
        self.assertTrue(fonts.preview_png('M PLUS Rounded 1c').startswith(b'\x89PNG'))

    def test_centered_page_effects_and_local_font_routes(self):
        overlay = Overlay(port=0)
        try:
            overlay.update('剩余SC： 12', True, '', font='Noto Sans JP', weight=800,
                           glow_enabled=True, glow_blur=16, shadow_enabled=False,
                           stroke_enabled=True,stroke_width=2,stroke_color='#123456',italic_enabled=True,bold_enabled=True)
            base = f'http://127.0.0.1:{overlay.port}'
            self.assertEqual(overlay.url(), base + '/overlay?v=' + REVISION)
            with urlopen(overlay.url()) as r:
                page = r.read()
                self.assertNotIn(b'__SCMARU_REVISION__', page)
                self.assertIn(REVISION.encode(), page)
                self.assertIn(b'location.replace', page)
                self.assertEqual(r.headers['Cache-Control'], 'no-store')
            with urlopen(base+'/state') as r: state = json.load(r)
            self.assertEqual(state['text'], '剩余SC： 12')
            self.assertEqual(state['revision'], REVISION)
            self.assertEqual(state['weight'], 800)
            self.assertTrue(state['glow_enabled'])
            self.assertTrue(state['stroke_enabled'])
            self.assertTrue(state['italic_enabled'])
            self.assertTrue(state['bold_enabled'])
            self.assertEqual(state['stroke_width'],2)
            self.assertEqual(state['stroke_color'],'#123456')
            with urlopen(base+'/fonts.css') as r: self.assertIn(b'@font-face', r.read())
            name = fonts.entries()[0]['file']
            with urlopen(base+'/fonts/'+name) as r:
                self.assertEqual(hashlib.sha256(r.read()).hexdigest(), fonts.entries()[0]['sha256'])
            with self.assertRaises(HTTPError): urlopen(base+'/fonts/%2e%2e/config.py')
            self.assertIn(b'align-items:center;justify-content:center', PAGE)
            self.assertIn(b'text-align:center', PAGE)
        finally: overlay.close()

    def test_effect_values_are_bounded(self):
        result = normalize_effects(dict(weight=5000, glow_opacity=-2, glow_color='bad',stroke_width=100))
        self.assertEqual(result['weight'], 900)
        self.assertEqual(result['glow_opacity'], 0)
        self.assertEqual(result['glow_color'], '#e4b6cd')
        self.assertEqual(result['stroke_width'],12)


if __name__ == '__main__': unittest.main()
