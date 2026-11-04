import tempfile
from pathlib import Path
import unittest
from core import Ledger
from data_location import data_directory, import_legacy


class DataLocationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent/'.test-data')
        self.root=Path(self.temp.name)
        (self.root/'build_release.py').touch();(self.root/'app.py').touch()
    def tearDown(self): self.temp.cleanup()

    def test_shared_directory_and_live_sqlite_backup_import_once(self):
        old=self.root/'data'
        ledger=Ledger(old)
        ledger.db.execute('PRAGMA wal_autocheckpoint=0')
        ledger.save_settings(dict(room='12345',theme='black',session_cookie_protected='synthetic-protected'))
        ledger.attach('12345','room')
        shared=data_directory(self.root,appdata=self.root/'appdata')
        imported=Ledger(shared)
        self.assertEqual(imported.get('room'),'12345')
        self.assertEqual(imported.get('theme'),'black')
        self.assertEqual(imported.db.execute('SELECT count(*) FROM sessions').fetchone()[0],1)
        imported.set('room','999')
        later=data_directory(self.root/'releases/0.4.0/SCMaru',appdata=self.root/'appdata')
        self.assertEqual(later,shared)
        reopened=Ledger(later)
        self.assertEqual(reopened.get('room'),'999')
        reopened.db.close()
        self.assertEqual(ledger.get('room'),'12345')
        imported.db.close();ledger.db.close()

    def test_explicit_data_and_demo_are_isolated(self):
        self.assertEqual(data_directory(self.root,override=self.root/'qa'),self.root/'qa')
        self.assertEqual(data_directory(self.root,demo=True),self.root/'demo-data')

    def test_existing_settings_are_never_overwritten(self):
        source,target=self.root/'old',self.root/'shared'
        source.mkdir();target.mkdir()
        (source/'config.json').write_text('{"room":"old"}')
        (target/'config.json').write_text('{"room":"new"}')
        import_legacy(source,target)
        self.assertIn('new',(target/'config.json').read_text())
