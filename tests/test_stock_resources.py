"""Capture fixed stock hardware inputs without any phone-side writes."""

import hashlib
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from iphone7_port.core import PortError, Project
from iphone7_port.stock_resources import capture_stock, spec, stock_folder

ROOT = Path(__file__).resolve().parents[1]


class StockTests(unittest.TestCase):
    def project(self, temp):
        root = Path(temp)
        (root / 'profiles').mkdir()
        for name in ('d10-20b82.json', 'sources.lock.json'):
            (root / 'profiles' / name).write_bytes((ROOT / 'profiles' / name).read_bytes())
        project = Project(root)
        project.record('device', {'identity': {'ECID': '0x1234'}})
        return project

    def fixture(self):
        names = ['Library/Audio/Tunings/D10/input', 'usr/share/firmware/multitouch/D10.mtprops']
        return {'schema': 1, 'build': '19H422', 'capture_directories': ['Library/Audio/Tunings/D10'],
                'capture_files': [names[1]], 'files': [{'path': name, 'size': 5,
                 'sha256': hashlib.sha256(b'stock').hexdigest()} for name in names]}

    def test_profile_is_complete_and_missing_capture_is_actionable(self):
        self.assertEqual(len(spec(Project(ROOT))['files']), 248)
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(PortError, 'capture in the 15.6 SSHRD'):
                stock_folder(self.project(temp))

    def test_recursive_capture_publishes_only_after_all_host_hashes_pass(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            project, ssh = self.project(temp), Mock()
            def transfer(source, destination, **kwargs):
                if kwargs.get('recursive'):
                    target = destination / 'D10/input'
                else:
                    target = destination
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b'stock')
            ssh.transfer.side_effect = transfer
            with patch('iphone7_port.stock_resources.spec', return_value=self.fixture()):
                folder = capture_stock(project, ssh)
                self.assertEqual(stock_folder(project), folder)
                self.assertEqual(ssh.transfer.call_count, 2)
                self.assertTrue(ssh.transfer.call_args_list[0].kwargs['recursive'])
                capture_stock(project, ssh)
                self.assertEqual(ssh.transfer.call_count, 2)
                project.record('device', {'identity': {'ECID': '0x9999'}})
                with self.assertRaisesRegex(PortError, 'different device'):
                    stock_folder(project)
            ssh.run.assert_not_called()
            ssh.script.assert_not_called()

    def test_failed_capture_never_records_completion_and_can_retry(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            project, ssh = self.project(temp), Mock()
            ssh.transfer.side_effect = PortError('disconnected')
            with patch('iphone7_port.stock_resources.spec', return_value=self.fixture()):
                with self.assertRaises(PortError):
                    capture_stock(project, ssh)
            self.assertNotIn('stock-rootfs-resources', project.read_state()['stages'])
            self.assertFalse((project.work / 'devices/0x1234/stock-resources').exists())


if __name__ == '__main__':
    unittest.main()
