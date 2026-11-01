"""Full-system bundle isolation, boot ordering and reversible stock-boot guard."""

import io
import subprocess
import tempfile
import unittest
from contextlib import nullcontext, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from iphone7_port.cli import main
from iphone7_port.core import PortError, Project
from iphone7_port.device import REBOOT_REQUEST
from iphone7_port.img4 import pack, split_image, wrap
from iphone7_port.install import finalize_install, kernelcache_backup_script
from iphone7_port.sshrd import build_system, boot, check_images, receipt

ROOT = Path(__file__).resolve().parents[1]


class SystemTests(unittest.TestCase):
    def project(self, temp):
        root = Path(temp)
        (root / 'profiles').mkdir()
        for name in ('d10-20b82.json', 'sources.lock.json'):
            (root / 'profiles' / name).write_bytes((ROOT / 'profiles' / name).read_bytes())
        p = Project(root)
        p.initialize()
        self.identity = {'ECID': '0x1234', 'CPID': '0x8010', 'MODEL': 'd10ap', 'PRODUCT': 'iPhone9,1', 'MODE': 'DFU'}
        p.record('device', {'identity': self.identity})
        return p

    def fixture(self, p):
        ticket = pack(0x30, pack(0x16, b'IM4M'))
        ticket_file = p.work / 'ticket.im4m'
        ticket_file.write_bytes(ticket)
        p.record('capture', {'ecid': '0x1234', 'ticket': str(ticket_file), 'preboot_hash': 'A' * 96})
        source_plain = p.work / 'build/bootstrap/iBEC.dec'
        source_plain.parent.mkdir(parents=True)
        source_plain.write_bytes(b'stock plaintext')
        for stage in ('bootstrap', 'ios16-sshrd'):
            folder = p.output / stage
            folder.mkdir(parents=True)
            for name in ('iBSS', 'iBEC', 'devicetree', 'trustcache', 'kernelcache', 'ramdisk', 'sep'):
                if name == 'sep' and stage == 'bootstrap':
                    continue
                data = (b'patched:' + source_plain.read_bytes() + b':' + p.profile['ramdisk_boot_args'].encode() + b'\0'
                        if name == 'iBEC' else ('fixture-' + name).encode())
                payload = pack(0x30, pack(0x16, b'IM4P') + pack(0x16, b'ibec') + pack(0x04, data))
                (folder / (name + '.img4')).write_bytes(wrap(payload, ticket))
            record = receipt(p, folder, stage, ticket, self.identity, {'kernel_raw_sha256': 'hc3'})
            p.record('build-' + stage, {'folder': str(folder), 'receipt': record,
                                       'patched_donor': str(source_plain.parent / 'donor.raw')})
        p.tool = Mock(side_effect=lambda name: name)
        def run(args, **kwargs):
            if args[0] == 'iBoot64Patcher':
                Path(args[2]).write_bytes(b'patched:' + Path(args[1]).read_bytes() + b':' + args[4].encode() + b'\0')
            elif args[0] == 'img4':
                source, dest = Path(args[2]), Path(args[4])
                if '-A' in args:
                    payload = pack(0x30, pack(0x16, b'IM4P') + pack(0x16, b'ibec') + pack(0x04, source.read_bytes()))
                    dest.write_bytes(wrap(payload, ticket))
                else:
                    from iphone7_port.img4 import children
                    dest.write_bytes(children(split_image(source.read_bytes())[0])[-1][1])
        p.run = Mock(side_effect=run)
        return source_plain

    def test_full_bundle_changes_only_ibec_and_omits_ramdisk_and_ave(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            p = self.project(temp)
            self.fixture(p)
            with patch('iphone7_port.sshrd.require_confirmed'):
                build_system(p)
            full = p.output / 'ios16'
            record = check_images(full)
            self.assertEqual(record['root_volume'], '/dev/disk1s8')
            self.assertIn('rd=disk1s8', record['boot_args'])
            self.assertFalse((full / 'ramdisk.img4').exists())
            self.assertFalse((full / 'AVE.img4').exists())
            for name in ('iBSS', 'devicetree', 'trustcache', 'sep', 'kernelcache'):
                self.assertEqual((full / (name + '.img4')).read_bytes(), (p.output / 'ios16-sshrd' / (name + '.img4')).read_bytes())
            self.assertNotEqual((full / 'iBEC.img4').read_bytes(), (p.output / 'ios16-sshrd/iBEC.img4').read_bytes())
            self.assertIn('rd=md0', check_images(p.output / 'ios16-sshrd')['boot_args'])
            p.record('install-rootfs', {'installation_id': 'new'})
            p.run.reset_mock()
            with patch('iphone7_port.sshrd.require_confirmed'), patch('iphone7_port.sshrd.confirm_action'), \
                 patch('iphone7_port.sshrd.query_device', return_value=self.identity), patch('iphone7_port.sshrd.time.sleep'):
                with self.assertRaises(PortError):
                    boot(p, 'ios16')
                p.run.assert_not_called()
                p.record('install-finalize', {'installation_id': 'new'})
                from iphone7_port.clean import clean
                with patch('iphone7_port.clean.mounted_paths', return_value=[]):
                    clean(p)
                self.assertTrue(Path(p.stage('capture')['ticket']).is_file())
                self.assertTrue(full.is_dir())
                boot(p, 'ios16')
            recovery = [call.args[0][3:] for call in p.run.call_args_list if call.args[0][0] == 'irecovery']
            self.assertEqual(recovery, [
                ['-f', full / 'iBSS.img4'], ['-f', full / 'iBEC.img4'], ['-c', 'go'],
                ['-f', full / 'devicetree.img4'], ['-c', 'devicetree'],
                ['-f', full / 'trustcache.img4'], ['-c', 'firmware'],
                ['-f', full / 'sep.img4'], ['-c', 'rsepfirmware'],
                ['-f', full / 'kernelcache.img4'], ['-c', 'bootx']])

    def test_changed_bootstrap_plaintext_cannot_produce_a_full_bundle(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            p = self.project(temp)
            plain = self.fixture(p)
            plain.write_bytes(b'wrong plaintext')
            with patch('iphone7_port.sshrd.require_confirmed'), self.assertRaisesRegex(PortError, 'does not reproduce'):
                build_system(p)
            self.assertFalse((p.output / 'ios16').exists())

    def test_kernel_backups_are_lossless_retryable_and_conflicts_preflight_all_files(self):
        with tempfile.TemporaryDirectory() as temp:
            first, second = Path(temp).resolve() / 'System/kernelcache', Path(temp).resolve() / 'Preboot/kernelcache'
            for path in (first, second):
                path.parent.mkdir()
                path.write_bytes(b'original kernel bytes')
            script = kernelcache_backup_script([str(first), str(second)]).removesuffix('sync\n')
            backup = Path(str(second) + '.bak')
            backup.write_bytes(b'existing backup')
            def run():
                return subprocess.run(['/bin/sh', '-eu'], input=script, text=True, capture_output=True)
            result = run()
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(first.exists())
            self.assertEqual(backup.read_bytes(), b'existing backup')
            backup.unlink()
            self.assertEqual(run().returncode, 0)
            self.assertFalse(first.exists())
            self.assertFalse(second.exists())
            self.assertEqual(Path(str(first) + '.bak').read_bytes(), b'original kernel bytes')
            self.assertEqual(run().returncode, 0)
            self.assertIn('ALREADY_BACKED_UP', run().stdout)

    def test_missing_or_symbolic_kernel_targets_do_not_claim_success(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp).resolve() / 'kernelcache'
            external = Path(temp) / 'other'
            external.write_bytes(b'untouched')
            script = kernelcache_backup_script([str(target)]).removesuffix('sync\n')
            for linked in (False, True):
                if linked:
                    target.symlink_to(external)
                result = subprocess.run(['/bin/sh', '-eu'], input=script, text=True, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(external.read_bytes(), b'untouched')

    def test_finalize_requires_matching_phases_and_does_not_mount_data(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            p = self.project(temp)
            p.record('build-ios16', {'folder': str(p.output / 'ios16')})
            for name in ('install-cryptex', 'install-patches', 'install-preboot'):
                p.record(name, {'installation_id': 'new', 'preboot_hash': 'A' * 96})
            ssh = Mock()
            ssh.run.return_value = '/dev/disk1s6 on /mnt6 (apfs, local)\n'
            stock = '/mnt1/System/Library/Caches/com.apple.kernelcaches/kernelcache'
            ssh.script.side_effect = ['', 'RENAMED\t' + stock + '\n']
            with patch('iphone7_port.sshrd.check_images', return_value={'stage': 'ios16', 'ecid': '0x1234'}), \
                 patch('iphone7_port.install.verify_target', return_value={'installation_id': 'new'}):
                finalize_install(p, ssh)
            scripts = '\n'.join(call.args[0] for call in ssh.script.call_args_list)
            self.assertNotIn('mount_filesystems', scripts)
            self.assertNotIn('/mnt2', scripts)
            self.assertEqual(p.stage('install-finalize')['kernel_backups'][0]['backup'], stock + '.bak')
            ssh.run.assert_called_with('/sbin/umount /mnt1')
            p.record('install-patches', {'installation_id': 'old'})
            ssh.reset_mock()
            with patch('iphone7_port.sshrd.check_images', return_value={'stage': 'ios16', 'ecid': '0x1234'}), \
                 patch('iphone7_port.install.verify_target', return_value={'installation_id': 'new'}), self.assertRaises(PortError):
                finalize_install(p, ssh)
            ssh.script.assert_not_called()

    def test_finalize_cli_does_not_require_media_or_continue_after_reboot_offer(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            self.project(temp)
            with patch('iphone7_port.cli.require_confirmed'), patch('iphone7_port.cli.InstallSSH') as ssh, \
                 patch('iphone7_port.cli.forward', return_value=nullcontext()), patch('iphone7_port.cli.finalize_install') as finalize, \
                 patch('iphone7_port.cli.offer_reboot') as reboot, patch('iphone7_port.cli.verify_media') as media:
                self.assertEqual(main(['--project', temp, 'install', 'finalize']), 0)
                finalize.assert_called_once()
                reboot.assert_called_once_with(finalize.call_args.args[0], ssh.return_value, completed_stage='install-finalize')
                media.assert_not_called()
                finalize.side_effect = PortError('Kernel backup failed')
                reboot.reset_mock()
                self.assertEqual(main(['--project', temp, 'install', 'finalize']), 2)
                reboot.assert_not_called()

    def test_reboot_shell_returns_before_the_delayed_action(self):
        # Use a harmless local marker in place of reboot. A blocking child would
        # make communicate() wait for sleep and fail the short timeout.
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / 'reboot-requested'
            command = REBOOT_REQUEST.replace('/sbin/reboot', '/usr/bin/true').replace('/bin/sleep 2; /usr/bin/true', f'/bin/sleep 1; /usr/bin/touch {marker}')
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=0.8)
            self.assertEqual(result.returncode, 0)
            self.assertIn('REBOOT_SCHEDULED', result.stdout)
            self.assertFalse(marker.exists())
            import time
            deadline = time.monotonic() + 3
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(marker.exists())


if __name__ == '__main__':
    unittest.main()
