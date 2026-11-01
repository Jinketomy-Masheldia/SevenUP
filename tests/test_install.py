"""Destructive deployment is tested against a simulated phone, never hardware."""

import hashlib
import io
import json
import os
import plistlib
import struct
import subprocess
import tarfile
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from iphone7_port.core import PortError, Project
from iphone7_port.install import (TARGET, container_mounts, delete_tool, deletion_plan, install_rootfs,
                                 install_preboot, inventory, ramdisk_root, unmount_container, verify_ramdisk)
from iphone7_port.install_media import apfs_size, archive_entries
from iphone7_port.rootfs_patches import patch_script
from iphone7_port.signing import verify_detached

ROOT = Path(__file__).resolve().parents[1]
ROLES = [1, 64, 256, 128, 320, 16, 192]
SW_VERS = 'ProductName:\tiPhone OS\nProductVersion:\t16.1\nBuildVersion:\t20B82\n'


def registry(volumes):
    return [{'BSD Name': 'disk0s1', 'IORegistryEntryChildren': [
        {'BSD Name': 'disk1', 'IORegistryEntryChildren': [
            {'IOClass': 'AppleAPFSContainer', 'UUID': 'container-A', 'IORegistryEntryChildren': [
                {'BSD Name': 'disk1s' + str(index), 'UUID': row['uuid'], 'FullName': row['name'], 'RoleValue': row['role']}
                for index, row in sorted(volumes.items())]}]}]}]


class Phone:
    def __init__(self, extra=()):
        self.volumes = {index: {'device': f'/dev/disk1s{index}', 'uuid': 'stock-' + str(index),
                               'name': ['System', 'Data', 'xART', 'Baseband Data', 'Hardware', 'Preboot', 'Update'][index-1],
                               'role': role} for index, role in enumerate(ROLES, 1)}
        for index in extra:
            self.volumes[index] = {'device': f'/dev/disk1s{index}', 'uuid': 'old-' + str(index), 'name': 'old', 'role': 4}
        self.mounted = {'/mnt1': '/dev/disk1s1', '/mnt2': '/dev/disk1s2', '/mnt6': '/dev/disk1s6'}
        self.commands = []
        self.fail_unmount = False
        self.fail_upload = False

    def info(self):
        return inventory(plistlib.dumps(registry(self.volumes)))

    def run(self, command, **kwargs):
        self.commands.append(command)
        if command == '/usr/sbin/ioreg -l -w 0':
            return plistlib.dumps(registry(self.volumes)).decode()
        if command == '/sbin/mount':
            return '/dev/md0 on / (hfs, local)\n' + ''.join(device + ' on ' + path + ' (apfs, local)\n' for path, device in self.mounted.items())
        if command.startswith('/sbin/umount '):
            if self.fail_unmount:
                raise PortError('Device busy')
            self.mounted.pop(command.split(' ', 1)[1])
        elif command.startswith('/sbin/apfs_deletefs '):
            assert not self.mounted
            self.volumes.pop(int(command.split('disk1s')[1]))
        elif command.startswith('/sbin/newfs_apfs '):
            assert not self.mounted and set(self.volumes) == set(range(1, 8))
            self.volumes[8] = {'device': '/dev/disk1s8', 'uuid': 'new-8', 'name': 'Xystem', 'role': 4}
        elif command.startswith('/System/Library/Filesystems/apfs.fs/apfs_invert '):
            assert not self.mounted
        elif command.startswith('if [ -d /mnt6/'):
            return 'FOUND'
        return ''

    def script(self, script, **kwargs):
        self.commands.append(script)
        if 'for p in /sbin/apfs_deletefs' in script:
            return '/sbin/apfs_deletefs\n'
        if '/sbin/mount_apfs /dev/disk1s8 /mnt8' in script:
            self.mounted['/mnt8'] = '/dev/disk1s8'
        if '/sbin/mount_apfs /dev/disk1s6 /mnt6' in script:
            self.mounted['/mnt6'] = '/dev/disk1s6'
        return ''

    def upload(self, source, destination, **kwargs):
        self.commands.append('UPLOAD ' + destination)
        if self.fail_upload:
            raise PortError('SCP failed')

    def target_version(self):
        return {'ProductVersion': '16.1', 'ProductBuildVersion': '20B82'}


class InstallTests(unittest.TestCase):
    def project(self, temp):
        root = Path(temp)
        (root / 'profiles').mkdir()
        for name in ('d10-20b82.json', 'sources.lock.json'):
            (root / 'profiles' / name).write_bytes((ROOT / 'profiles' / name).read_bytes())
        project = Project(root)
        project.record('device', {'identity': {'ECID': '0x1234'}})
        media = root / 'work/install-media'
        media.mkdir()
        (media / 'root.dmg').write_bytes(b'raw APFS fixture')
        return project

    def deploy(self, project, phone):
        media = {'artifacts': {'root': {'sha256': 'root-hash'}}}
        with patch('iphone7_port.install.verify_ramdisk', return_value=phone.info()), patch('iphone7_port.install.confirm_action') as confirm:
            result = install_rootfs(project, phone, media)
            return result, confirm

    def test_inventory_binds_physical_store_and_preserves_seven_stock_roles(self):
        phone = Phone((8, 9, 10))
        data = registry(phone.volumes)
        info = inventory(plistlib.dumps(data))
        self.assertEqual([row['device'] for row in deletion_plan(info)], ['/dev/disk1s10', '/dev/disk1s9', '/dev/disk1s8'])
        data[0]['BSD Name'] = 'disk0s2'
        with self.assertRaisesRegex(PortError, 'physical store'):
            inventory(plistlib.dumps(data))
        phone.volumes[2]['role'] = 4
        with self.assertRaisesRegex(PortError, 'Stock APFS roles'):
            phone.info()

    def test_rootfs_flow_unmounts_every_volume_and_never_calls_mount_filesystems(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            project, phone = self.project(temp), Phone((8, 9))
            result, confirm = self.deploy(project, phone)
            self.assertEqual(confirm.call_args.args[1], 'DELETE disk1s9 disk1s8')
            deleted = [command for command in phone.commands if command.startswith('/sbin/apfs_deletefs ')]
            self.assertEqual(deleted, ['/sbin/apfs_deletefs /dev/disk1s9', '/sbin/apfs_deletefs /dev/disk1s8'])
            self.assertEqual(set(phone.volumes), set(range(1, 9)))
            self.assertEqual(result['volume_uuid'], 'new-8')
            self.assertEqual(phone.mounted, {'/mnt8': '/dev/disk1s8'})
            self.assertFalse(any('mount_filesystems' in command for command in phone.commands))
            self.assertEqual([command for command in phone.commands if command.startswith('UPLOAD ')], ['UPLOAD /mnt8/root.dmg'])
            self.assertFalse(any('helper' in command or '/tmp/' in command for command in phone.commands))
            self.assertLess(phone.commands.index('UPLOAD /mnt8/root.dmg'), phone.commands.index('/System/Library/Filesystems/apfs.fs/apfs_invert -d /dev/disk0s1 -s 8 -n root.dmg'))
            self.assertEqual(project.stage('install-rootfs')['installation_id'], result['installation_id'])

    def test_clean_stock_layout_still_requires_explicit_install_confirmation(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            project, phone = self.project(temp), Phone()
            _, confirm = self.deploy(project, phone)
            self.assertEqual(confirm.call_args.args[1], 'INSTALL DISK1S8')
            self.assertFalse(any('apfs_deletefs /dev/' in command for command in phone.commands))

    def test_cancel_or_busy_unmount_stops_before_delete_create_or_invert(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            project, phone = self.project(temp), Phone((8,))
            media = {'artifacts': {'root': {'sha256': 'root-hash'}}}
            with patch('iphone7_port.install.verify_ramdisk', return_value=phone.info()), patch('iphone7_port.install.confirm_action', side_effect=PortError('cancelled')):
                with self.assertRaisesRegex(PortError, 'cancelled'):
                    install_rootfs(project, phone, media)
            self.assertFalse(any(command.startswith('/sbin/apfs_deletefs ') or command.startswith('/sbin/newfs_apfs ') for command in phone.commands))
            phone.fail_unmount = True
            with self.assertRaisesRegex(PortError, 'Device busy'):
                self.deploy(project, phone)
            self.assertFalse(any(command.startswith('/sbin/apfs_deletefs ') or 'apfs_invert -d' in command for command in phone.commands))

    def test_scp_failure_never_runs_invert_or_records_completed_root(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            project, phone = self.project(temp), Phone()
            phone.fail_upload = True
            with self.assertRaisesRegex(PortError, 'SCP failed'):
                self.deploy(project, phone)
            self.assertFalse(any('apfs_invert -d' in command for command in phone.commands))
            self.assertNotIn('install-rootfs', project.read_state()['stages'])

    def test_mount_filter_catches_physical_and_synthesized_nodes(self):
        text = '/dev/md0 on / (hfs, local)\n/dev/disk0s1s2 on /mnt2 (apfs, local)\n/dev/disk1s6 on /mnt6 (apfs, local)\n'
        self.assertEqual(container_mounts(text), [('/dev/disk0s1s2', '/mnt2'), ('/dev/disk1s6', '/mnt6')])
        with self.assertRaises(PortError):
            container_mounts('/dev/disk1s8 unparseable mount')

    def test_actual_sshrd_root_device_hfs_alias_is_accepted(self):
        actual = 'root_device on / (hfs, local, read-only)\ndevfs on /dev (devfs, local, nosuid, nobrowse)\n'
        self.assertTrue(ramdisk_root(actual))
        self.assertTrue(ramdisk_root('/dev/md0 on / (hfs, local)\n'))
        self.assertTrue(ramdisk_root('/dev/md0s1 on / (hfs, local, read-only)\n'))
        for invalid in ('root_device on / (apfs, local, read-only)\n',
                        '/dev/disk1s8 on / (apfs, local)\n',
                        '/dev/disk1s1 on / (hfs, local)\n',
                        'root_device on /mnt8 (hfs, local)\n',
                        'root_device on / (hfs, local)\n/dev/md0 on / (hfs, local)\n'):
            self.assertFalse(ramdisk_root(invalid), invalid)

    def test_root_device_hfs_alias_passes_the_entire_readonly_preflight(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            project = self.project(temp)
            project.record('boot-ios16-sshrd', {})
            chosen = plistlib.dumps([{'unique-chip-id': (0x1234).to_bytes(8, 'little')}]).decode()
            ssh = Mock()
            ssh.run.side_effect = [SW_VERS, 'root_device on / (hfs, local, read-only)\n', chosen,
                                   'iPhone9,1\n', plistlib.dumps(registry(Phone().volumes)).decode()]
            with patch('iphone7_port.install.require_confirmed'):
                result = verify_ramdisk(project, ssh)
            self.assertEqual(set(result['volumes']), set(range(1, 8)))
            ssh.script.assert_not_called()
            ssh.upload.assert_not_called()

    def test_full_ios_or_wrong_ecid_is_rejected_without_modification(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            project = self.project(temp)
            project.record('boot-ios16-sshrd', {})
            ssh = Mock()
            ssh.run.side_effect = [SW_VERS, '/dev/disk1s8 on / (apfs, local)\n']
            with patch('iphone7_port.install.require_confirmed'), self.assertRaisesRegex(PortError, 'not a ramdisk'):
                verify_ramdisk(project, ssh)
            chosen = plistlib.dumps([{'unique-chip-id': (0x999).to_bytes(8, 'little')}]).decode()
            ssh.run.side_effect = [SW_VERS, '/dev/md0 on / (hfs, local)\n', chosen]
            with patch('iphone7_port.install.require_confirmed'), self.assertRaisesRegex(PortError, 'ECID'):
                verify_ramdisk(project, ssh)
            ssh.script.assert_not_called()

    def test_sw_vers_mismatch_stops_before_any_other_device_command(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.project(temp)
            project.record('boot-ios16-sshrd', {})
            for output in (SW_VERS.replace('16.1', '15.6'), SW_VERS.replace('20B82', 'wrong-build'), ''):
                ssh = Mock()
                ssh.run.return_value = output
                with patch('iphone7_port.install.require_confirmed'), self.assertRaisesRegex(PortError, 'sw_vers must report'):
                    verify_ramdisk(project, ssh)
                ssh.run.assert_called_once_with('/usr/bin/sw_vers')
                ssh.script.assert_not_called()
                ssh.upload.assert_not_called()

    def test_missing_delete_utility_is_detected_before_deletion(self):
        ssh = Mock()
        ssh.script.return_value = ''
        with self.assertRaisesRegex(PortError, 'No supported'):
            delete_tool(ssh)
        ssh.run.assert_not_called()

    def test_raw_container_check_rejects_gpt_and_truncated_data(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'root.dmg'
            block = bytearray(4096)
            block[32:36] = b'NXSB'
            struct.pack_into('<IQ', block, 36, 4096, 1)
            path.write_bytes(block)
            self.assertEqual(apfs_size(path), 4096)
            path.write_bytes(b'GPT' + block)
            with self.assertRaisesRegex(PortError, 'raw APFS'):
                apfs_size(path)
            path.write_bytes(block + b'trailing')
            with self.assertRaisesRegex(PortError, 'length'):
                apfs_size(path)

    def test_unsafe_archive_paths_and_symlink_traversal_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'payload.tar.gz'
            for name in ('../escaped', '/usr/file', 'Volumes/cryptex/usr/file'):
                with tarfile.open(path, 'w:gz') as archive:
                    entry = tarfile.TarInfo(name)
                    entry.size = 1
                    archive.addfile(entry, io.BytesIO(b'x'))
                with self.assertRaises(PortError):
                    archive_entries(path)
            with tarfile.open(path, 'w:gz') as archive:
                entry = tarfile.TarInfo('usr/lib')
                entry.type, entry.linkname = tarfile.SYMTYPE, '../System'
                archive.addfile(entry)
                entry = tarfile.TarInfo('usr/lib/escaped')
                archive.addfile(entry, io.BytesIO(b''))
            with self.assertRaisesRegex(PortError, 'traverses a symlink'):
                archive_entries(path)

    def test_preboot_uses_ticket_hash_and_runtime_absolute_links(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            project, phone = self.project(temp), Phone((8,))
            stage = {'installation_id': 'abc'}
            project.record('capture', {'preboot_hash': 'A' * 96})
            project.record('install-cryptex', stage)
            with patch('iphone7_port.install.verify_target', return_value=stage):
                install_preboot(project, phone)
            script = '\n'.join(phone.commands)
            self.assertIn('/mnt6/' + 'A' * 96 + '/usr/standalone/firmware', script)
            self.assertIn('ln -sfn /usr/libexec /mnt6/Cryptexes/App/usr/libexec', script)
            self.assertNotIn('ln -s /System /mnt6/', script)
            self.assertNotIn('ln -s /mnt8', script)
            self.assertFalse(any('apfs_deletefs ' in command for command in phone.commands))

    def test_patch_install_script_preserves_backups_and_checks_all_before_writes(self):
        record = {'variants': {'without-ssh': {'files': [
            {'path': 'usr/libexec/watchdogd', 'mode': 0o755, 'sha256': 'a'*64},
            {'path': 'System/Library/DriverExtensions/test.dext/program', 'mode': 0o755, 'sha256': 'b'*64}]}}}
        script = patch_script(record, 'without-ssh', '/mnt8/.stage')
        self.assertLess(script.index('test.dext/program.bak ]'), script.index('cp '))
        self.assertNotIn('helper', script)
        self.assertNotIn('sha256', script)
        self.assertIn('/mnt8/usr/libexec/watchdogd.bak', script)
        self.assertIn('/mnt8/usr/local/share/iphone7-ios16-backups/System/Library/DriverExtensions/test.dext/program.bak', script)
        self.assertNotIn('test.dext/program /mnt8/System/Library/DriverExtensions/test.dext/program.bak', script)
        result = subprocess.run(['/bin/sh', '-n'], input=script, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_actual_patch_script_installs_files_and_retains_originals_in_a_fixture(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'root'
            stage = Path(temp) / 'payload'
            rows = []
            for relative in ('usr/libexec/watchdogd', 'System/Library/DriverExtensions/test.dext/program'):
                for base, content in [(root, b'original'), (stage, b'candidate')]:
                    path = base / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
                rows.append({'path': relative, 'mode': 0o755, 'sha256': hashlib.sha256(b'candidate').hexdigest()})
            (root / 'usr/sbin').mkdir()
            (root / 'usr/sbin/fairplayd.A2').write_bytes(b'original A2')
            (root / 'usr/sbin/fairplayd.H2').write_bytes(b'original H2')
            # Owner changes are stubbed: this test must not require root on the Mac.
            commands = Path(temp) / 'commands'
            commands.mkdir()
            (commands / 'chown').write_text('#!/bin/sh\nexit 0\n')
            (commands / 'chown').chmod(0o755)
            env = {**os.environ, 'PATH': str(commands) + ':' + os.environ.get('PATH', '')}
            record = {'variants': {'without-ssh': {'files': rows}}}
            script = patch_script(record, 'without-ssh', str(stage)).replace('/mnt8', str(root))
            result = subprocess.run(['/bin/sh', '-eu'], input=script, text=True, capture_output=True, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root / rows[0]['path']).read_bytes(), b'candidate')
            self.assertEqual((root / (rows[0]['path'] + '.bak')).read_bytes(), b'original')
            backup = root / ('usr/local/share/iphone7-ios16-backups/' + rows[1]['path'] + '.bak')
            self.assertEqual(backup.read_bytes(), b'original')
            self.assertFalse((root / (rows[1]['path'] + '.bak')).exists())
            self.assertEqual(os.readlink(root / 'usr/sbin/fairplayd.A2'), 'fairplayd.H2')
            self.assertEqual((root / 'usr/sbin/fairplayd.A2.bak').read_bytes(), b'original A2')

    def test_detached_cache_signature_detects_changed_content(self):
        data = b'cache content'
        cd = bytearray(44)
        struct.pack_into('>IIIIIIIII', cd, 0, 0xfade0c02, 76, 0x20001, 2, 44, 0, 0, 1, len(data))
        cd[36:40] = bytes([32, 2, 0, 12])
        cd.extend(hashlib.sha256(data).digest())
        blob = struct.pack('>IIIII', 0xfade0cc0, 20 + len(cd), 1, 0, 20) + cd
        self.assertEqual(verify_detached(blob, data)[0]['pages'], 1)
        with self.assertRaisesRegex(PortError, 'page hash mismatch'):
            verify_detached(blob, b'CACHE content')


if __name__ == '__main__':
    unittest.main()
