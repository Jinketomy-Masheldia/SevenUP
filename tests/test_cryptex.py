"""Flatten native Cryptex directory links without following them outside rootfs."""

import io
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from iphone7_port.install import cryptex_extract_script
from iphone7_port.install_media import archive_entries


class CryptexTests(unittest.TestCase):
    def fixture(self, root):
        target = root / 'target'
        outside = root / 'outside'
        outside.mkdir()
        (outside / 'untouched').write_text('original')
        relative = "System/Library/Frameworks/Frame's Test.framework"
        dest = target / relative
        dest.parent.mkdir(parents=True)
        dest.symlink_to(outside, target_is_directory=True)
        archive = root / 'system.tar.gz'
        with tarfile.open(archive, 'w:gz') as stream:
            member = tarfile.TarInfo(relative + '/nested/program')
            member.size = len(b'payload')
            member.uid, member.gid = os.getuid(), os.getgid()
            stream.addfile(member, io.BytesIO(b'payload'))
        script = cryptex_extract_script(archive_entries(archive), str(archive), str(target))
        return target, outside, dest, script

    def test_native_link_is_backed_up_and_files_extract_into_a_real_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            target, outside, dest, script = self.fixture(Path(temp))
            for _ in range(2):
                result = subprocess.run(['/bin/sh', '-eu'], input=script, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(dest.is_symlink())
            self.assertEqual((dest / 'nested/program').read_bytes(), b'payload')
            self.assertTrue(Path(str(dest) + '.bak').is_symlink())
            self.assertEqual((outside / 'untouched').read_text(), 'original')
            self.assertFalse((outside / 'nested').exists())

    def test_backup_conflict_is_reported_before_following_a_link(self):
        with tempfile.TemporaryDirectory() as temp:
            target, outside, dest, script = self.fixture(Path(temp))
            Path(str(dest) + '.bak').write_text('existing backup')
            result = subprocess.run(['/bin/sh', '-eu'], input=script, text=True, capture_output=True)
            self.assertEqual(result.returncode, 22)
            self.assertIn('backup already exists', result.stderr)
            self.assertTrue(dest.is_symlink())
            self.assertEqual(Path(str(dest) + '.bak').read_text(), 'existing backup')
            self.assertFalse((outside / 'nested').exists())


if __name__ == '__main__':
    unittest.main()
