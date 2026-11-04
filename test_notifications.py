from pathlib import Path
import tempfile
import unittest
import wave
import struct
from notifications import write_sound, SoundPlayer
from unittest.mock import patch


class SoundTests(unittest.TestCase):
    def test_two_soft_sounds_volume_and_async_playback(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent/'.test-data') as folder:
            first,second=Path(folder)/'sc.wav',Path(folder)/'alarm.wav'
            write_sound(first,'sc',25);write_sound(second,'alarm',25)
            self.assertNotEqual(first.read_bytes(),second.read_bytes())
            with wave.open(str(first),'rb') as audio:
                self.assertEqual(audio.getnchannels(),1)
                self.assertLess(audio.getnframes()/audio.getframerate(),1)
                raw=audio.readframes(audio.getnframes())
            self.assertLess(max(abs(n) for n in struct.unpack('<'+'h'*(len(raw)//2),raw)),1600)
            with patch('winsound.PlaySound') as play:
                player=SoundPlayer(folder)
                player.play('sc',0);play.assert_not_called()
                player.play('sc',25);play.assert_called_once()
