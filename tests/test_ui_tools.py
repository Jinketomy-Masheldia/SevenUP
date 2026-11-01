"""Host-only terminal, dependency resolution and optional reboot regressions."""

import io
import json
import os
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

from iphone7_port.cli import main
from iphone7_port.console import paint
from iphone7_port.core import PortError, Project, save_json
from iphone7_port.device import SSH, offer_reboot

ROOT = Path(__file__).resolve().parents[1]


class UiToolTests(unittest.TestCase):
    def project(self, directory):
        root = Path(directory)
        (root / 'profiles').mkdir()
        for name in ['d10-20b82.json', 'sources.lock.json']:
            (root / 'profiles' / name).write_bytes((ROOT / 'profiles' / name).read_bytes())
        return Project(root)

    def executable(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#!/bin/sh\nexit 0\n')
        path.chmod(0o755)
        return path

    def test_color_is_terminal_only_and_respects_no_color(self):
        tty = Mock()
        tty.isatty.return_value = True
        with patch.dict(os.environ, {'TERM': 'xterm-256color'}, clear=True):
            self.assertEqual(paint('done', 'success', tty), '\033[32mdone\033[0m')
            self.assertEqual(paint('done', 'success', io.StringIO()), 'done')
            with patch.dict(os.environ, {'NO_COLOR': ''}):
                self.assertEqual(paint('done', 'success', tty), 'done')

    def test_bundle_is_project_relative_and_legacy_configuration_is_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.project(temp)
            bundled = self.executable(project.root / 'Darwin/img4')
            linker = self.executable(project.root / 'Darwin/ld64.lld')
            with patch('iphone7_port.core.shutil.which', return_value='/external/img4'):
                self.assertEqual(project.tool('img4'), str(bundled))
                self.assertEqual(project.linker(), str(linker))
            self.executable(project.root / 'custom/img4')
            (project.root / 'local.json').write_text('invalid legacy JSON must not be read')
            self.assertEqual(Project(project.root).tool('img4'), str(bundled))

    def test_scp_runs_in_the_foreground_and_keeps_password_out_of_arguments(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            project = self.project(temp)
            project.record('device', {'identity': {'ECID': '0x1234'}})
            project._ssh_password = 'private-transfer-password'
            self.executable(project.root / 'resources/ssh-transport.sh')
            ssh = SSH(project, 2222)
            with patch.object(project, 'tool', return_value='/bundle/sshpass'), patch.object(project, 'run') as run:
                ssh.transfer('/tmp/source.dmg', 'root@127.0.0.1:/mnt8/root.dmg')
            command = run.call_args.args[0]
            self.assertEqual(command[0], 'scp')
            self.assertIn('-S', command)
            self.assertNotIn('private-transfer-password', str(command))
            self.assertTrue(run.call_args.kwargs['live'])
            self.assertEqual(run.call_args.kwargs['env']['IPHONE7_SSHPASS'], '/bundle/sshpass')

    def test_private_command_errors_show_the_action_and_actual_stderr(self):
        import sys
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            project = self.project(temp)
            with self.assertRaisesRegex(PortError, 'cannot create directory'):
                project.run([sys.executable, '-c', 'import sys;print("tar: cannot create directory",file=sys.stderr);sys.exit(1)'],
                            private=True, label='ssh: tar -zxpf archive -C /mnt8')
            report = json.loads((project.root / 'logs/last-command.json').read_text())
            self.assertEqual(report['action'], 'ssh: tar -zxpf archive -C /mnt8')

    def test_reboot_defaults_to_no_and_keeps_capture(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            project = self.project(temp)
            project.record('capture', {'saved': True})
            ssh = Mock()
            self.assertFalse(offer_reboot(project, ssh, ask=lambda _: ''))
            ssh.run.assert_not_called()
            self.assertTrue(project.stage('capture')['saved'])
            self.assertFalse(project.stage('post-capture-reboot')['requested'])

    def test_reboot_requires_a_completed_capture_and_an_affirmative_answer(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            project = self.project(temp)
            ssh = Mock()
            ask = Mock(return_value='yes')
            with self.assertRaises(PortError):
                offer_reboot(project, ssh, ask=ask)
            ask.assert_not_called()
            ssh.run.assert_not_called()
            project.record('capture', {'saved': True})
            self.assertTrue(offer_reboot(project, ssh, ask=ask))
            from iphone7_port.device import REBOOT_REQUEST
            ssh.run.assert_called_once_with(REBOOT_REQUEST, timeout=15)
            self.assertEqual(project.stage('post-capture-reboot')['status'], 'scheduled')

    def test_expected_disconnect_during_reboot_finishes_without_reconnection(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            project = self.project(temp)
            project.record('capture', {'saved': True})
            save_json(project.root/'logs/last-command.json', {'returncode': 255, 'stderr': 'Connection to 127.0.0.1 closed by remote host.'})
            ssh = Mock()
            ssh.run.side_effect = PortError('connection closed')
            self.assertTrue(offer_reboot(project, ssh, ask=lambda _: 'y'))
            self.assertEqual(project.stage('post-capture-reboot')['status'], 'request-sent-disconnected')
            ssh.run.assert_called_once()
            self.assertTrue(project.stage('capture')['saved'])

    def test_capture_asks_before_forwarding_is_closed_and_never_after_failure(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            project = self.project(temp)
            project.record('boot-bootstrap', {'commands_sent': True})
            active = {'value': False}
            @contextmanager
            def forward(*args, **kwargs):
                active['value'] = True
                try:
                    yield
                finally:
                    active['value'] = False
            ssh = Mock()
            def ask(*args):
                self.assertTrue(active['value'])
                self.assertIs(args[1], ssh)
            with patch('iphone7_port.cli.require_confirmed'), patch('iphone7_port.cli.forward', forward), patch('iphone7_port.cli.collect', return_value=ssh) as collect, patch('iphone7_port.cli.offer_reboot', side_effect=ask) as offer:
                self.assertEqual(main(['--project', temp, 'capture', '--already-mounted']), 0)
                self.assertFalse(active['value'])
                offer.assert_called_once()
                offer.reset_mock()
                collect.side_effect = PortError('capture failed')
                self.assertEqual(main(['--project', temp, 'capture']), 2)
                offer.assert_not_called()

    def test_reboot_submission_failure_is_not_hidden_as_an_expected_disconnect(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            project = self.project(temp)
            project.record('capture', {'saved': True})
            save_json(project.root / 'logs/last-command.json', {'returncode': 255, 'stderr': 'Permission denied (publickey,password).'})
            ssh = Mock()
            ssh.run.side_effect = PortError('Authentication failed')
            with self.assertRaisesRegex(PortError, 'Authentication failed'):
                offer_reboot(project, ssh, ask=lambda _: 'y')
            self.assertEqual(project.stage('post-capture-reboot')['status'], 'failed')

    def test_interactive_ssh_inherits_terminal_without_command_logging_or_timeout(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()) as output:
            project = self.project(temp)
            project.record('device', {'identity': {'ECID': '0x1234'}})
            project._ssh_password = 'private-test-password'
            ssh = SSH(project, 2223)
            with patch.object(project, 'tool', return_value='/bundle/sshpass'), patch.object(project, 'run') as logged, patch.object(ssh, 'run') as authenticate, patch('iphone7_port.device.subprocess.run', return_value=Mock(returncode=0)) as run:
                self.assertEqual(ssh.interactive(), 0)
                authenticate.assert_called_once_with(':', timeout=30)
            command = run.call_args.args[0]
            self.assertEqual(command[:3], ['/bundle/sshpass', '-e', 'ssh'])
            self.assertEqual(command[-4:], ['-t', '-p', '2223', 'root@127.0.0.1'])
            self.assertIn('StrictHostKeyChecking=no', command)
            self.assertIn('UserKnownHostsFile=/dev/null', command)
            self.assertEqual(set(run.call_args.kwargs), {'env'})
            self.assertEqual(run.call_args.kwargs['env']['SSHPASS'], 'private-test-password')
            self.assertNotIn('private-test-password', output.getvalue())
            logged.assert_not_called()
            self.assertFalse((project.root / 'logs').exists())

    def test_interactive_ssh_uses_default_password_and_preserves_failure_status(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            project = self.project(temp)
            project.record('device', {'identity': {'ECID': '0x1234'}})
            ssh = SSH(project, 2222)
            with patch.object(project, 'tool', return_value='/bundle/sshpass'), patch.object(ssh, 'run'), patch('iphone7_port.device.subprocess.run', return_value=Mock(returncode=255)) as run:
                self.assertEqual(ssh.interactive(), 255)
                self.assertEqual(run.call_args.kwargs['env']['SSHPASS'], 'alpine')

    def test_usb_connections_ignore_stale_keys_in_both_system_modes(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.project(temp)
            project.record('device', {'identity': {'ECID': '0x1234'}})
            ramdisk = SSH(project, 2222).options()
            project.record('install-rootfs', {'installation_id': 'abc123'})
            first = SSH(project, 2222, system=True).options()
            project.record('install-rootfs', {'installation_id': 'def456'})
            second = SSH(project, 2222, system=True).options()
            self.assertEqual(ramdisk, first)
            self.assertEqual(first, second)
            self.assertIn('StrictHostKeyChecking=no', ramdisk)
            self.assertIn('UserKnownHostsFile=/dev/null', ramdisk)
            self.assertIn('GlobalKnownHostsFile=/dev/null', ramdisk)

    def test_patch_preparation_and_compatibility_alias_ignore_parent_and_config(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            root = Path(temp) / 'relocated'
            root.mkdir()
            self.project(root)
            (root / 'local.json').write_text('not valid JSON')
            with patch('iphone7_port.cli.prepare_patches') as prepare:
                for command in ('prepare-rootfs-patches', 'import-rootfs-patches'):
                    self.assertEqual(main(['--project', str(root), command]), 0)
                self.assertEqual(prepare.call_count, 2)
                self.assertTrue(all(call.args[0].root == root.resolve() for call in prepare.call_args_list))

    def test_rootfs_cli_does_not_upload_or_require_an_install_helper(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            self.project(temp)
            media = {'artifacts': {'root': {'filename': 'root.dmg', 'sha256': 'source'}}}
            with patch('iphone7_port.cli.require_confirmed'), patch('iphone7_port.cli.read_media_receipt', return_value=media), \
                 patch('iphone7_port.cli.verify_media') as deep_media, patch('iphone7_port.cli.verify_patches') as patches, \
                 patch('iphone7_port.cli.forward', return_value=nullcontext()), \
                 patch('iphone7_port.cli.InstallSSH') as ssh, patch('iphone7_port.cli.verify_ramdisk'), \
                 patch('iphone7_port.cli.install_rootfs') as install:
                self.assertEqual(main(['--project', temp, 'install', 'rootfs']), 0)
                install.assert_called_once()
                self.assertIs(install.call_args.args[2], media)
                deep_media.assert_not_called()
                patches.assert_not_called()
                ssh.return_value.upload.assert_not_called()
                ssh.return_value.script.assert_not_called()
                ssh.return_value.run.assert_not_called()

    def test_ssh_cli_keeps_forward_alive_for_session_and_closes_on_failure(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            self.project(temp)
            active = {'value': False}
            @contextmanager
            def forward(project, port, *, use_existing):
                self.assertEqual(port, 2223)
                self.assertTrue(use_existing)
                active['value'] = True
                try:
                    yield
                finally:
                    active['value'] = False
            def session():
                self.assertTrue(active['value'])
                return 255
            with patch('iphone7_port.cli.forward', forward), patch('iphone7_port.cli.SSH') as ssh:
                ssh.return_value.interactive.side_effect = session
                self.assertEqual(main(['--project', temp, 'ssh', '--port', '2223', '--existing-forward']), 255)
                self.assertFalse(active['value'])
                ssh.return_value.interactive.side_effect = OSError('SSH executable unavailable')
                self.assertEqual(main(['--project', temp, 'ssh', '--port', '2223', '--existing-forward']), 2)
                self.assertFalse(active['value'])


if __name__ == '__main__':
    unittest.main()
