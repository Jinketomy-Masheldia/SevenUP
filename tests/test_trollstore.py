import io
import subprocess
import tempfile
import unittest
from contextlib import nullcontext, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from iphone7_port.cli import main
from iphone7_port.core import Project
from iphone7_port.trollstore import BASE, URL, install_trollstore, replacement_script, tips_search_script

ROOT = Path(__file__).resolve().parents[1]
UUID = '12345678-1234-1234-1234-123456789ABC'


class TrollStoreTests(unittest.TestCase):
    def project(self, temp):
        root = Path(temp)
        (root / 'profiles').mkdir()
        for name in ('d10-20b82.json', 'sources.lock.json'):
            (root / 'profiles' / name).write_bytes((ROOT / 'profiles' / name).read_bytes())
        return Project(root)

    def test_discovery_uses_the_actual_app_container_and_skips_missing_tips(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp).resolve() / 'Application'
            executable = base / UUID / 'Tips.app/Tips'
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b'original')
            script = tips_search_script(str(base))
            result = subprocess.run(['/bin/sh', '-eu'], input=script, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), str(executable))
            executable.unlink()
            result = subprocess.run(['/bin/sh', '-eu'], input=script, text=True, capture_output=True)
            self.assertEqual(result.stdout, '')

    def test_replacement_keeps_original_backup_and_refuses_to_overwrite_it(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp).resolve()
            original, staged = folder / 'Tips', folder / '.new-helper'
            original.write_bytes(b'original Tips')
            staged.write_bytes(b'embedded helper')
            script = replacement_script(str(original), str(staged))
            script = '\n'.join(line for line in script.splitlines() if not line.startswith('chown ') and line != 'sync')
            result = subprocess.run(['/bin/sh', '-eu'], input=script, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(original.read_bytes(), b'embedded helper')
            self.assertEqual((folder / 'Tips.bak').read_bytes(), b'original Tips')
            self.assertEqual(original.stat().st_mode & 0o777, 0o755)
            staged.write_bytes(b'another helper')
            result = subprocess.run(['/bin/sh', '-eu'], input=script, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(original.read_bytes(), b'embedded helper')
            self.assertEqual((folder / 'Tips.bak').read_bytes(), b'original Tips')

    def test_missing_tips_finishes_before_downloading_or_uploading(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()) as output:
            p, ssh = self.project(temp), Mock()
            ssh.run.return_value = '/dev/disk1s2 on /mnt2 (apfs, local)\n'
            ssh.script.return_value = ''
            with patch('iphone7_port.trollstore.verify_ramdisk'), patch('iphone7_port.trollstore.download_helper') as download:
                self.assertFalse(install_trollstore(p, ssh))
            self.assertIn('install Tips from the App Store', output.getvalue())
            download.assert_not_called()
            ssh.transfer.assert_not_called()
            self.assertNotIn('install-trollstore', p.read_state()['stages'])

    def test_installer_uploads_only_into_the_discovered_tips_bundle(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            p, ssh = self.project(temp), Mock()
            executable = BASE + '/' + UUID + '/Tips.app/Tips'
            ssh.run.return_value = '/dev/disk1s2 on /mnt2 (apfs, local)\n'
            ssh.script.side_effect = [executable + '\n', '', '']
            source = Path(temp) / 'PersistenceHelper_Embedded'
            with patch('iphone7_port.trollstore.verify_ramdisk'), patch('iphone7_port.trollstore.download_helper', return_value=source):
                self.assertTrue(install_trollstore(p, ssh))
            destination = ssh.transfer.call_args.args[1]
            self.assertTrue(destination.startswith('root@127.0.0.1:' + str(Path(executable).parent)))
            script = ssh.script.call_args.args[0]
            self.assertNotIn('ldid', script)
            self.assertNotIn('mount_filesystems', script)
            self.assertEqual(p.stage('install-trollstore')['source'], URL)
            self.assertTrue(p.stage('install-trollstore')['persistence_helper_only'])

    def test_cli_does_not_require_rootfs_media_for_optional_helper_installation(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            self.project(temp)
            with patch('iphone7_port.cli.require_confirmed'), patch('iphone7_port.cli.InstallSSH'), \
                 patch('iphone7_port.cli.forward', return_value=nullcontext()), patch('iphone7_port.cli.install_trollstore', return_value=False) as install, \
                 patch('iphone7_port.cli.verify_media') as media:
                self.assertEqual(main(['--project', temp, 'install', 'trollstore']), 0)
                install.assert_called_once()
                media.assert_not_called()


if __name__ == '__main__':
    unittest.main()
