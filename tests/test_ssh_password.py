import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from iphone7_port.core import PortError, Project, save_json
from iphone7_port.device import SSH
from iphone7_port.install import InstallSSH

ROOT = Path(__file__).resolve().parents[1]


class PasswordTests(unittest.TestCase):
    def project(self, temp):
        root = Path(temp)
        (root / 'profiles').mkdir()
        for name in ('d10-20b82.json', 'sources.lock.json'):
            (root / 'profiles' / name).write_bytes((ROOT / 'profiles' / name).read_bytes())
        p = Project(root)
        p.record('device', {'identity': {'ECID': '0x1234'}})
        p.tool = Mock(return_value='sshpass')
        (root / 'resources').mkdir()
        transport = root / 'resources/ssh-transport.sh'
        transport.write_text('#!/bin/sh\n')
        transport.chmod(0o755)
        return p

    def test_new_password_is_shared_by_commands_scripts_and_scp_without_being_saved(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            p = self.project(temp)
            attempts = []
            def run(arguments, **kwargs):
                password = kwargs['env']['SSHPASS']
                attempts.append((list(map(str, arguments)), password))
                if password == 'alpine':
                    save_json(p.root / 'logs/last-command.json', {'returncode': 5, 'stderr': 'Permission denied, please try again.'})
                    raise PortError('authentication failed')
                return Mock(stdout='ok')
            p.run = Mock(side_effect=run)
            with patch('iphone7_port.device.sys.stdin.isatty', return_value=True), \
                 patch('iphone7_port.device.getpass.getpass', return_value='new-private-password') as ask:
                self.assertEqual(SSH(p, 2222).run('true'), 'ok')
                InstallSSH(p, 2222).script('echo done')
                SSH(p, 2222).transfer('/tmp/source', 'root@127.0.0.1:/mnt8/source')
            ask.assert_called_once()
            self.assertEqual([password for _, password in attempts], ['alpine'] + ['new-private-password'] * 3)
            self.assertNotIn('new-private-password', str([arguments for arguments, _ in attempts]))
            self.assertFalse(hasattr(p, 'local'))
            self.assertFalse((p.root / 'local.json').exists())

    def test_remote_permission_error_or_ordinary_exit_five_is_not_replayed(self):
        for report in ({'returncode': 1, 'stderr': 'scp: /mnt8/file: Permission denied'},
                       {'returncode': 5, 'stderr': 'remote script failed'},
                       {'returncode': 255, 'stderr': 'Connection refused'}):
            with self.subTest(report=report), tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
                p = self.project(temp)
                save_json(p.root / 'logs/last-command.json', report)
                p.run = Mock(side_effect=PortError('failed'))
                with patch('iphone7_port.device.getpass.getpass') as ask, self.assertRaises(PortError):
                    SSH(p, 2222).run('some-command')
                ask.assert_not_called()
                p.run.assert_called_once()

    def test_noninteractive_rejection_exits_without_waiting_for_password(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            p = self.project(temp)
            save_json(p.root / 'logs/last-command.json', {'returncode': 255, 'stderr': 'Permission denied (publickey,password).'})
            p.run = Mock(side_effect=PortError('failed'))
            with patch('iphone7_port.device.sys.stdin.isatty', return_value=False), \
                 patch('iphone7_port.device.getpass.getpass') as ask, self.assertRaisesRegex(PortError, 'interactive terminal'):
                SSH(p, 2222).run('true')
            ask.assert_not_called()


if __name__ == '__main__':
    unittest.main()
