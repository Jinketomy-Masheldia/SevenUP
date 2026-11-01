"""Regression coverage for the bundled SSHRD ioreg's text-only output."""

import plistlib
import unittest

from iphone7_port.core import PortError
from iphone7_port.install import inventory, walk
from iphone7_port.registry import read_registry


class RegistryTests(unittest.TestCase):
    def test_colored_tree_properties_keep_their_ancestors(self):
        text = '''+-o Root  <class IORegistryEntry, id 0x100>
  +-o physical  <class IOMedia, id 0x101>
  |   {
  |     "BSD Name" = "disk0s1"
  |     "UUID" = "physical"
  |   }
  | +-o media  <class AppleAPFSMedia, id 0x102>
  | |   {
  | |     "BSD Name" = "disk1"
  | |   }
  | | +-o AppleAPFSContainer  <class AppleAPFSContainer, id 0x103>
  | | |   {
  | | |     "UUID" = "container"
  | | |   }
'''
        for index, role in enumerate((1, 64, 256, 128, 320, 16, 192), 1):
            text += f'''  | | | +-o Volume@{index}  <class AppleAPFSVolume, id 0x200>
  | | | |   {{
  | | | |     "BSD Name" = "disk1s{index}"
  | | | |     "UUID" = "volume-{index}"
  | | | |     "RoleValue" = {role}
  | | | |     "FullName" = "Volume {index}"
  | | | |   }}
'''
        colored = '\x1b[36m' + text.replace('\n', '\x1b[0m\n\x1b[36m') + '\x1b[0m'
        result = inventory(colored)
        self.assertEqual(result['uuid'], 'container')
        self.assertEqual(set(result['volumes']), set(range(1, 8)))
        self.assertEqual(result['volumes'][2]['name'], 'Volume 2')
        self.assertEqual(result['volumes'][2]['role'], 64)

    def test_chosen_data_and_hex_numbers_are_not_evaluated_as_code(self):
        text = '''+-o chosen  <class IODeviceTreeNode, id 0x100>
  | {
  |   "unique-chip-id" = <3412000000000000>
  |   "RoleValue" = 0x40
  |   "unneeded-property" = {"UUID"="nested"}
  |     "UUID" = "ignore this nested field"
  | }
'''
        node = read_registry(text)[0]
        self.assertEqual(int.from_bytes(node['unique-chip-id'], 'little'), 0x1234)
        self.assertEqual(node['RoleValue'], 64)
        self.assertNotIn('UUID', node)

    def test_xml_input_remains_compatible(self):
        expected = [{'IORegistryEntryName': 'chosen', 'unique-chip-id': b'12345678'}]
        self.assertEqual(read_registry(plistlib.dumps(expected)), expected)
        self.assertEqual(read_registry(plistlib.dumps(expected).decode()), expected)

    def test_missing_tree_or_ambiguous_properties_are_rejected(self):
        with self.assertRaisesRegex(PortError, 'unrecognized'):
            read_registry("ioreg: error: can't open file.\n")
        with self.assertRaisesRegex(PortError, 'Duplicate'):
            read_registry('+-o chosen  <class IODeviceTreeNode, id 0x100>\n      "UUID" = "one"\n      "UUID" = "two"\n')


if __name__ == '__main__':
    unittest.main()
