import io
import tempfile
import unittest
from contextlib import nullcontext, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from iphone7_port.accessibility import DOMAIN, KEY, Lockdown, enable_assistive_touch
from iphone7_port.core import PortError, Project

ROOT = Path(__file__).resolve().parents[1]


class AccessibilityTests(unittest.TestCase):
    def test_set_value_owns_the_node_even_when_the_device_rejects_the_request(self):
        api = Lockdown.__new__(Lockdown)
        api.mobile, api.plist = Mock(), Mock()
        api.plist.plist_new_uint.return_value = 1234
        api.mobile.lockdownd_strerror.return_value = b'Set value prohibited'
        for result in (0, -1):
            api.mobile.lockdownd_set_value.return_value = result
            if result:
                with self.assertRaises(PortError):
                    api.enable('client')
            else:
                api.enable('client')
            api.mobile.lockdownd_set_value.assert_called_with('client', DOMAIN, KEY, 1234)
            api.plist.plist_free.assert_not_called()

    def project(self, temp):
        root = Path(temp)
        (root / 'profiles').mkdir()
        for name in ('d10-20b82.json', 'sources.lock.json'):
            (root / 'profiles' / name).write_bytes((ROOT / 'profiles' / name).read_bytes())
        p = Project(root)
        p.record('device', {'identity': {'ECID': '0x1234'}})
        return p

    def test_enable_uses_the_itunes_key_only_after_live_device_identity_matches(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            p = self.project(temp)
            api = Mock()
            api.devices.return_value = ['usb-device']
            api.connect.return_value = nullcontext('client')
            info = {'UniqueChipID': 0x1234, 'ProductType': 'iPhone9,1', 'ProductVersion': '16.1', 'BuildVersion': '20B82'}
            api.get.side_effect = [info, 1]
            with patch('iphone7_port.accessibility.Lockdown', return_value=api):
                enable_assistive_touch(p)
            api.enable.assert_called_once_with('client')
            api.get.assert_called_with('client', DOMAIN, KEY)
            self.assertTrue(p.stage('assistive-touch')['enabled'])
            for changed in ({**info, 'UniqueChipID': 1}, {**info, 'ProductType': 'iPhone10,1'}, {**info, 'BuildVersion': '19H422'}):
                api.reset_mock()
                api.get.side_effect = [changed]
                with patch('iphone7_port.accessibility.Lockdown', return_value=api), self.assertRaises(PortError):
                    enable_assistive_touch(p)
                api.enable.assert_not_called()

    def test_multiple_usb_devices_are_not_selected_implicitly(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            p = self.project(temp)
            api = Mock()
            api.devices.return_value = ['first', 'second']
            with patch('iphone7_port.accessibility.Lockdown', return_value=api), self.assertRaisesRegex(PortError, 'Multiple'):
                enable_assistive_touch(p)
            api.connect.assert_not_called()
            api.enable.assert_not_called()

    def test_false_readback_does_not_record_success(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            p = self.project(temp)
            api = Mock()
            api.devices.return_value = ['usb-device']
            api.connect.return_value = nullcontext('client')
            api.get.side_effect = [{'UniqueChipID': 0x1234, 'ProductType': 'iPhone9,1', 'ProductVersion': '16.1', 'BuildVersion': '20B82'}, 0]
            with patch('iphone7_port.accessibility.Lockdown', return_value=api), self.assertRaisesRegex(PortError, 'not confirmed'):
                enable_assistive_touch(p)
            self.assertNotIn('assistive-touch', p.read_state()['stages'])


if __name__ == '__main__':
    unittest.main()
