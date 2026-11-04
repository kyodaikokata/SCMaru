import json
from pathlib import Path
import tempfile
import unittest

from config import Settings, protect, unprotect,load_defaults


class ConfigTests(unittest.TestCase):
    def test_atomic_json_and_reopen(self):
        root = Path(__file__).parent / '.test-data'
        root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as folder:
            path = Path(folder) / 'config.json'
            settings = Settings(path, {'theme': 'pink'})
            settings.update({'room': '123', 'language': 'ja'})
            self.assertEqual(Settings(path).data['language'], 'ja')
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['theme'], 'pink')
            self.assertEqual(list(Path(folder).glob('*.tmp')), [])

    def test_windows_secret_roundtrip(self):
        protected = protect('test-only-value')
        self.assertNotIn('test-only-value', protected)
        self.assertEqual(unprotect(protected), 'test-only-value')

    def test_bundled_defaults_exclude_credentials_and_existing_preferences_win(self):
        defaults=load_defaults()
        raw=json.dumps(defaults)
        for key in ('session_cookie','key_protected','access_key','auth_protected','login_expired'):
            self.assertNotIn(key,raw)
        root=Path(__file__).parent/'.test-data';root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as folder:
            path=Path(folder)/'config.json'
            settings=Settings(path)
            self.assertEqual(settings.data['overlay_effects'],defaults['overlay_effects'])
            settings.update({'theme':'white','overlay_effects':{'stroke_width':3}})
            restored=Settings(path)
            self.assertEqual(restored.data['theme'],'white')
            self.assertEqual(restored.data['overlay_effects']['stroke_width'],3)
            self.assertEqual(restored.data['overlay_effects']['stroke_color'],defaults['overlay_effects']['stroke_color'])


if __name__ == '__main__': unittest.main()
