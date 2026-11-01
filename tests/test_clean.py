"""Host-only cleanup tests; never clean the real project workspace."""

import fcntl
import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from iphone7_port.clean import clean, mounted_paths
from iphone7_port.cli import main
from iphone7_port.core import PortError, Project

ROOT = Path(__file__).resolve().parents[1]


class CleanTests(unittest.TestCase):
    def project(self, directory):
        root = Path(directory)
        (root / 'profiles').mkdir()
        for name in ('d10-20b82.json', 'sources.lock.json'):
            (root / 'profiles' / name).write_bytes((ROOT / 'profiles' / name).read_bytes())
        return Project(root)

    def put(self, root, name, content=b'keep this file'):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def test_default_clean_retains_boot_bundles_tickets_ipsws_and_boot_state(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            project = self.project(temp)
            kept = [self.put(project.root, name) for name in (
                'inputs/ipsw/test.ipsw', 'Darwin/img4', 'resources/helper.c',
                'work/devices/example/device.im4m', 'work/build/bootstrap/iBEC.dec',
                'work/kernel-source/kernelcache.raw', 'output/ios16/kernelcache.img4')]
            project.record('build-ios16', {'folder': str(project.output / 'ios16')})
            project.record('install-rootfs', {'installation_id': 'installed'})
            project.record('install-finalize', {'installation_id': 'installed'})
            project.record('capture', {'ticket': str(kept[3])})
            project.record('install-media', {'generated': True})
            before = project.read_state()
            before['stages'].pop('install-media')
            removed = [self.put(project.root, name).parent for name in (
                'work/install-media/root.dmg', 'work/rootfs-source/tree/file',
                'work/install-patches/patches.json', 'logs/command.json',
                'src/iphone7_port/__pycache__/cli.pyc')]
            with patch('iphone7_port.clean.mounted_paths', return_value=[]):
                self.assertEqual(main(['--project', temp, 'clean']), 0)
            self.assertTrue(all(path.exists() for path in kept))
            self.assertFalse(any(path.exists() for path in removed))
            self.assertEqual(project.read_state(), before)

    def test_all_clean_removes_boot_state_and_ipsws_but_keeps_bundled_resources(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.project(temp)
            kept = [self.put(project.root, name) for name in (
                'inputs/ipsw/README.md', 'local.json.bak', 'Darwin/img4',
                'src/iphone7_port/cli.py', 'resources/sshrd/ssh.tar.gz', 'run.sh')]
            before = {path: path.read_bytes() for path in kept}
            removed = [self.put(project.root, name) for name in (
                'inputs/ipsw/test.ipsw', 'inputs/ipsw/second.IPSW',
                'work/capture/sep.img4', 'output/ios16/kernelcache.img4',
                'logs/command.json', 'src/iphone7_port/__pycache__/cli.pyc',
                'tests/__pycache__/test.pyc', 'tools/__pycache__/tool.pyc')]
            output = io.StringIO()
            with patch('iphone7_port.clean.mounted_paths', return_value=[]), redirect_stdout(output):
                self.assertEqual(main(['--project', temp, 'clean', '--all']), 0)
            self.assertIn('FULL CLEAN', output.getvalue())
            self.assertFalse(any(path.exists() for path in removed))
            self.assertFalse(any((project.root / name).exists() for name in ('work', 'output', 'logs')))
            self.assertEqual(before, {path: path.read_bytes() for path in kept})

    def test_nested_symlink_never_deletes_its_firmware_target(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            project = self.project(temp)
            firmware = self.put(project.root, 'resources/sshrd/ssh.tar.gz')
            project.work.mkdir()
            (project.work / 'linked-inputs').symlink_to(firmware.parent, target_is_directory=True)
            with patch('iphone7_port.clean.mounted_paths', return_value=[]):
                clean(project, all_files=True)
            self.assertTrue(firmware.exists())
            self.assertFalse(project.work.exists())

    def test_top_level_symlink_refuses_before_any_deletion(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            project = self.project(temp)
            sentinel = self.put(project.root, 'work/state.json')
            firmware = self.put(project.root, 'inputs/ipsw/test.ipsw')
            project.output.symlink_to(firmware.parent, target_is_directory=True)
            with self.assertRaisesRegex(PortError, 'symbolic link'):
                clean(project, all_files=True)
            self.assertTrue(sentinel.exists())
            self.assertTrue(firmware.exists())

    def test_mounted_filesystem_refuses_before_any_deletion(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            project = self.project(temp)
            sentinel = self.put(project.root, 'work/state.json')
            other = self.put(project.root, 'logs/command.json')
            with patch('iphone7_port.clean.mounted_paths', return_value=[project.work / 'mounted-image']):
                with self.assertRaisesRegex(PortError, 'mounted inside'):
                    clean(project, all_files=True)
            self.assertTrue(sentinel.exists())
            self.assertTrue(other.exists())

    def test_active_kernel_build_refuses_before_any_deletion(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            project = self.project(temp)
            sentinel = self.put(project.root, 'work/state.json')
            with self.put(project.root, 'work/kernel-build.lock').open('r+') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with patch('iphone7_port.clean.mounted_paths', return_value=[]):
                    with self.assertRaisesRegex(PortError, 'kernel build is active'):
                        clean(project, all_files=True)
            self.assertTrue(sentinel.exists())

    def test_empty_cleanup_is_idempotent_and_does_not_create_logs_or_state(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            project = self.project(temp)
            with patch('iphone7_port.clean.mounted_paths') as mounts:
                clean(project)
                clean(project)
                mounts.assert_not_called()
            self.assertFalse(any((project.root / name).exists() for name in ('work', 'output', 'logs')))

    def test_active_installation_prevents_cleanup(self):
        from iphone7_port.install import installation_lock
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            project = self.project(temp)
            with installation_lock(project), patch('iphone7_port.clean.mounted_paths', return_value=[]):
                with self.assertRaisesRegex(PortError, 'installation or preparation is active'):
                    clean(project, all_files=True)
            self.assertTrue(project.work.is_dir())

    def test_install_only_cleanup_preserves_boot_capture_inputs_and_other_progress(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            project = self.project(temp)
            retained = [self.put(project.root, name) for name in (
                'work/devices/example/device.im4m', 'work/devices/example/stock-resources/D10.mtprops', 'work/extracted/ipad_target/OS.dmg',
                'output/ios16-sshrd/kernelcache.img4', 'logs/last-command.json', 'inputs/ipsw/test.ipsw')]
            for name in ('install-media', 'install-patches', 'install-tools', 'rootfs-source'):
                self.put(project.work, name + '/generated')
            project.record('boot-ios16-sshrd', {'commands_sent': True})
            project.record('capture', {'saved': True})
            project.record('install-media', {'build': '20B82'})
            project.record('install-rootfs', {'installation_id': 'existing'})
            before = project.read_state()
            with patch('iphone7_port.clean.mounted_paths', return_value=[]):
                self.assertEqual(main(['--project', temp, 'clean', '--install']), 0)
            self.assertTrue(all(path.exists() for path in retained))
            self.assertFalse(any((project.work / name).exists() for name in ('install-media', 'install-patches', 'install-tools', 'rootfs-source')))
            before['stages'].pop('install-media')
            self.assertEqual(project.read_state(), before)

    def test_install_only_cleanup_refuses_redirected_work(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            project = self.project(temp)
            external = project.root / 'retained'
            sentinel = self.put(external, 'install-media/root.dmg')
            project.work.symlink_to(external, target_is_directory=True)
            with self.assertRaisesRegex(PortError, 'symbolic work'):
                clean(project, install_only=True)
            self.assertTrue(sentinel.exists())

    def test_all_clean_refuses_a_redirected_ipsw_directory_before_any_deletion(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            project = self.project(temp)
            external = project.root / 'retained'
            archive = self.put(external, 'test.ipsw')
            sentinel = self.put(project.work, 'keep')
            (project.root / 'inputs').mkdir()
            (project.root / 'inputs/ipsw').symlink_to(external, target_is_directory=True)
            with self.assertRaisesRegex(PortError, 'symbolic firmware'):
                clean(project, all_files=True)
            self.assertTrue(archive.exists())
            self.assertTrue(sentinel.exists())

    def test_mount_query_decodes_spaces_and_fails_closed(self):
        listing = '/dev/disk7s1 on /private/tmp/my\\040project/work/image (apfs, local)\n'
        with patch('iphone7_port.clean.subprocess.run', return_value=subprocess.CompletedProcess([], 0, listing, '')):
            self.assertEqual(mounted_paths(), [Path('/private/tmp/my project/work/image').resolve()])
        with patch('iphone7_port.clean.subprocess.run', side_effect=subprocess.TimeoutExpired('mount', 10)):
            with self.assertRaisesRegex(PortError, 'nothing was cleaned'):
                mounted_paths()


if __name__ == '__main__':
    unittest.main()
