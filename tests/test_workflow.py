import hashlib
import io
import fcntl
import json
import plistlib
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch
from contextlib import redirect_stdout

from iphone7_port.confirm import CHECKS, confirm_preconditions, require_confirmed
from iphone7_port.core import PortError, Project, digest_file
from iphone7_port.device import SSH, STOCK_VERSION_PATH, collect, parse_query, query_device, read_stock_version, select_sep, validate_device
from iphone7_port.firmware import component_paths, extract_source, fetch_bootstrap, safe_member, select_identity, verify_source
from iphone7_port.img4 import children, im4p_type, pack, reticket, split_image, wrap
from iphone7_port.sshrd import check_images
from iphone7_port.kernel_abi import load_plan
from iphone7_port.kernel_chain import rebuild

ROOT = Path(__file__).resolve().parents[1]


class ContainerTests(unittest.TestCase):
    def setUp(self):
        self.payload = pack(0x30, pack(0x16, b"IM4P") + pack(0x16, b"rkrn") + pack(0x16, b"test") + pack(4, b"payload" * 100))
        self.first = pack(0x30, pack(0x16, b"IM4M") + pack(2, b"\x01"))
        self.second = pack(0x30, pack(0x16, b"IM4M") + pack(2, b"\x02"))

    def test_reticket_preserves_payload_and_optional_metadata(self):
        image = pack(0x30, pack(0x16, b"IMG4") + self.payload + pack(0xA0, self.first) + pack(0xA1, b"metadata"))
        out = reticket(image, self.second)
        self.assertEqual(split_image(out), (self.payload, self.second))
        self.assertEqual(children(out)[-1][2], children(image)[-1][2])
        self.assertEqual(im4p_type(self.payload), "rkrn")

    def test_truncated_or_extra_der_is_rejected(self):
        image = wrap(self.payload, self.first)
        for broken in [image[:-1], image + b"x", b"\x30\x80\x00\x00"]:
            with self.assertRaises(PortError):
                split_image(broken)

    def test_wrong_payload_is_not_accepted_as_img4(self):
        with self.assertRaises(PortError):
            wrap(self.first, self.second)


class IdentityTests(unittest.TestCase):
    def real_query(self):
        return parse_query("CPID: 0x8010\nECID: 0x123456\nMODEL: d10ap\nPRODUCT: iPhone9,1\nMODE: DFU\nNONC: abcdef\nSRNM: USER-SERIAL\n")

    def test_real_fields_are_preserved(self):
        identity = self.real_query()
        validate_device(Project(ROOT), identity, require_dfu=True)
        self.assertEqual(identity["ECID"], "0x123456")
        self.assertEqual(identity["NONC"], "abcdef")
        self.assertEqual(identity["SRNM"], "USER-SERIAL")

    def test_fake_ipad_is_not_a_real_device_identity(self):
        identity = self.real_query()
        identity.update(PRODUCT="iPad7,5", MODEL="j71bap")
        with self.assertRaises(PortError):
            validate_device(Project(ROOT), identity)

    def test_zero_or_missing_identity_is_rejected(self):
        for text in ["PRODUCT: iPhone9,1", "CPID: 0x8010\nECID: 0\nMODEL: d10ap\nPRODUCT: iPhone9,1\nMODE: DFU"]:
            with self.assertRaises(PortError):
                parse_query(text)

    def test_non_dfu_device_cannot_start_boot_sequence(self):
        identity = self.real_query()
        identity["MODE"] = "Recovery"
        with self.assertRaises(PortError):
            validate_device(Project(ROOT), identity, require_dfu=True)


class PrebootTests(unittest.TestCase):
    def setUp(self):
        self.one, self.two = "A" * 96, "B" * 96
        self.paths = [f"/mnt6/{value}/usr/standalone/firmware/sep-firmware.img4" for value in [self.one, self.two]]

    def test_active_directory_wins(self):
        self.assertEqual(select_sep(self.paths, self.one.lower(), None), self.paths[0])

    def test_ambiguity_is_never_guessed(self):
        with self.assertRaises(PortError):
            select_sep(self.paths, "", None)

    def test_explicit_directory_is_checked(self):
        self.assertEqual(select_sep(self.paths, "", self.two), self.paths[1])
        for value in ["../elsewhere", "C" * 96]:
            with self.assertRaises(PortError):
                select_sep(self.paths, "", value)


class FirmwareTests(unittest.TestCase):
    def test_zip_traversal_is_rejected(self):
        for name in ["../outside", "/absolute", "safe/../../outside", "safe\\outside"]:
            with self.assertRaises(PortError):
                safe_member(name)

    def test_build_identity_is_selected_by_model_and_erase_variant(self):
        erase = {"Info": {"DeviceClass": "d10ap", "RestoreBehavior": "Erase", "Variant": "Customer Erase Install (IPSW)"}}
        other = {"Info": {"DeviceClass": "j71bap", "RestoreBehavior": "Erase", "Variant": "Customer Erase Install (IPSW)"}}
        self.assertEqual(select_identity({"BuildIdentities": [other, erase]}, "D10AP"), erase)
        with self.assertRaises(PortError):
            select_identity({"BuildIdentities": [erase, erase]}, "d10ap")

    def test_checksum_and_build_mismatch_stop_before_extraction(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "firmware.ipsw"
            manifest = {"ProductVersion": "15.6", "ProductBuildVersion": "19G71", "SupportedProductTypes": ["iPhone9,1"],
                        "BuildIdentities": [{"Info": {"DeviceClass": "d10ap", "RestoreBehavior": "Erase", "Variant": "Customer Erase Install (IPSW)"}}]}
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("BuildManifest.plist", plistlib.dumps(manifest))
            source = {"role": "iphone7_bootstrap", "size": path.stat().st_size, **digest_file(path), "version": "15.6", "build": "19G71", "product": "iPhone9,1", "model": "d10ap"}
            hashes, _ = verify_source(path, source)
            self.assertEqual(hashes["sha256"], source["sha256"])
            for changed in [{**source, "md5": "0" * 32}, {**source, "build": "wrong"}]:
                with self.assertRaises(PortError):
                    verify_source(path, changed)


class ConfirmationTests(unittest.TestCase):
    def project(self, directory):
        root = Path(directory)
        (root / "profiles").mkdir()
        for name in ["d10-20b82.json", "sources.lock.json"]:
            (root / "profiles" / name).write_bytes((ROOT / "profiles" / name).read_bytes())
        return Project(root)

    def test_one_refusal_aborts_without_storing_acceptance(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.project(temp)
            responses = iter([CHECKS[0][2], "NO"])
            with self.assertRaises(PortError):
                confirm_preconditions(project, ask=lambda _: next(responses))
            self.assertNotIn("confirmation", project.read_state()["stages"])

    def test_every_item_is_required_and_expiration_is_enforced(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.project(temp)
            responses = iter([expected for _, _, expected in CHECKS])
            confirm_preconditions(project, ask=lambda _: next(responses))
            require_confirmed(project)
            with patch("iphone7_port.confirm.time.time", return_value=10**12):
                with self.assertRaises(PortError):
                    require_confirmed(project)


class StageSafetyTests(unittest.TestCase):
    def project(self, temp):
        return ConfirmationTests().project(temp)

    def bootstrap_fixture(self, project):
        source = next(s for s in project.sources if s["role"] == "iphone7_bootstrap")
        blobs = {name: ("fixture-" + name).encode() for name in
                 ["iBSS", "iBEC", "DeviceTree", "KernelCache", "RestoreRamDisk", "RestoreTrustCache"]}
        identity = {"Info": {"DeviceClass": "d10ap", "RestoreBehavior": "Erase", "Variant": "Customer Erase Install (IPSW)"},
                    "Manifest": {name: {"Info": {"Path": "Firmware/" + name}, "Digest": hashlib.sha384(data).digest()}
                                 for name, data in blobs.items()}}
        manifest = {"ProductVersion": "15.6", "ProductBuildVersion": "19G71", "SupportedProductTypes": ["iPhone9,1"],
                    "BuildIdentities": [identity]}
        data = plistlib.dumps(manifest)
        source["manifest_sha256"] = hashlib.sha256(data).hexdigest()
        members = {"BuildManifest.plist": data, **{"Firmware/" + name: data for name, data in blobs.items()}}
        project.tool = Mock(return_value="pzb")
        def download(arguments, *, cwd, **kwargs):
            member = arguments[arguments.index("-g") + 1]
            name = arguments[arguments.index("-o") + 1] if "-o" in arguments else Path(member).name
            (Path(cwd) / name).write_bytes(members[member])
        project.run = Mock(side_effect=download)
        return source, manifest, members

    def test_partial_fetch_verifies_digests_and_reuses_without_network(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            project = self.project(temp)
            self.bootstrap_fixture(project)
            result = fetch_bootstrap(project)
            self.assertFalse(result["full_archive_verified"])
            self.assertEqual(project.run.call_count, 7)
            project.run.reset_mock()
            fetch_bootstrap(project)
            project.run.assert_not_called()
            self.assertNotIn("device", project.read_state()["stages"])

    def test_partial_fetch_digest_failure_publishes_nothing(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            project = self.project(temp)
            _, _, members = self.bootstrap_fixture(project)
            members["Firmware/KernelCache"] += b"changed"
            with self.assertRaises(PortError):
                fetch_bootstrap(project)
            self.assertFalse((project.work / "extracted/iphone7_bootstrap").exists())
            self.assertNotIn("bootstrap-resources", project.read_state()["stages"])

    def test_manifest_mismatch_stops_before_component_download(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            project = self.project(temp)
            source, _, _ = self.bootstrap_fixture(project)
            source["manifest_sha256"] = "0" * 64
            with self.assertRaises(PortError):
                fetch_bootstrap(project)
            self.assertEqual(project.run.call_count, 1)

    def test_complete_cached_extraction_does_not_require_more_free_space(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            project = self.project(temp)
            source, manifest, members = self.bootstrap_fixture(project)
            archive = project.root / "fixture.ipsw"
            with zipfile.ZipFile(archive, "w") as stream:
                for name, data in members.items():
                    stream.writestr(name, data)
            hashes = digest_file(archive)
            extract_source(project, archive, source, hashes, manifest)
            with patch("iphone7_port.firmware.shutil.disk_usage", return_value=Mock(free=0)):
                extract_source(project, archive, source, hashes, manifest)

    def test_a_different_ecid_does_not_replace_bound_identity(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            project = self.project(temp)
            original = IdentityTests().real_query()
            project.record("device", {"identity": original})
            project.tool = Mock(return_value="irecovery")
            project.run = Mock(return_value=Mock(stdout="CPID: 0x8010\nECID: 0xabcdef\nMODEL: d10ap\nPRODUCT: iPhone9,1\nMODE: DFU\n"))
            with self.assertRaises(PortError):
                query_device(project)
            self.assertEqual(project.stage("device")["identity"], original)

    def test_failed_mount_never_downloads_or_collects_ticket(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            project = self.project(temp)
            project.record("boot-bootstrap", {"commands_sent": True})
            with patch("iphone7_port.device.require_confirmed"), patch("iphone7_port.device.confirm_action"), patch("iphone7_port.device.SSH") as constructor:
                ssh = constructor.return_value
                ssh.run.side_effect = ["15.6\n", PortError("mount timed out")]
                with self.assertRaises(PortError):
                    collect(project)
                ssh.download.assert_not_called()
            self.assertNotIn("capture", project.read_state()["stages"])

    def test_stock_version_is_parsed_locally_from_xml_and_binary_plists(self):
        version = {"ProductVersion": "15.8.8", "ProductBuildVersion": "19H422", "ProductName": "iPhone OS"}
        for format in [plistlib.FMT_XML, plistlib.FMT_BINARY]:
            with self.subTest(format=format), tempfile.TemporaryDirectory() as temp:
                project = self.project(temp)
                project.initialize()
                ssh = Mock()
                def download(source, destination):
                    self.assertEqual(source, STOCK_VERSION_PATH)
                    destination.write_bytes(plistlib.dumps(version, fmt=format))
                ssh.download.side_effect = download
                self.assertEqual(read_stock_version(project, ssh), version)
                ssh.run.assert_not_called()
                self.assertEqual(list(project.work.glob('.stock-version-*')), [])

    def test_invalid_stock_plist_is_rejected_before_sep_collection(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.project(temp)
            project.initialize()
            ssh = Mock()
            ssh.download.side_effect = lambda source, destination: destination.write_bytes(b'not a plist')
            with self.assertRaisesRegex(PortError, 'Cannot parse'):
                read_stock_version(project, ssh)

    def test_already_mounted_capture_never_runs_plutil_or_remounts(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.project(temp)
            project.initialize()
            project.record('boot-bootstrap', {'commands_sent': True})
            with patch('iphone7_port.device.require_confirmed'), patch('iphone7_port.device.SSH') as constructor, patch('iphone7_port.device.select_sep', side_effect=PortError('stop before SEP transfer')):
                ssh = constructor.return_value
                ssh.run.side_effect = ['15.6\n', '/dev/disk0s1s6 on /mnt6 (apfs, local)\n', 'A'*96, '']
                ssh.download.side_effect = lambda source,destination: destination.write_bytes(plistlib.dumps({
                    'ProductVersion': '15.8.8', 'ProductBuildVersion': '19H422'}, fmt=plistlib.FMT_BINARY))
                with self.assertRaisesRegex(PortError, 'stop before SEP transfer'):
                    collect(project, already_mounted=True)
                commands = [call.args[0] for call in ssh.run.call_args_list]
                self.assertTrue(all('plutil' not in command and 'mount_filesystems' not in command for command in commands))
                self.assertEqual(ssh.download.call_args.args[0], STOCK_VERSION_PATH)

    def test_other_stock_files_cannot_be_downloaded_by_collection(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.project(temp)
            project.record('device', {'identity': IdentityTests().real_query()})
            project.run = Mock()
            ssh = SSH(project, 2222)
            for source in ['/mnt1/etc/passwd', '/mnt6/../mnt1/etc/passwd', STOCK_VERSION_PATH + '\n']:
                with self.assertRaises(PortError):
                    ssh.download(source, project.work/'test-file')
            project.run.assert_not_called()

    def test_empty_boot_bundle_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "receipt.json").write_text(json.dumps({"stage": "bootstrap", "images": {}}))
            with self.assertRaises(PortError):
                check_images(folder)

    def test_parallel_kernel_build_is_rejected_before_processing_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.project(temp)
            project.initialize()
            with (project.work / 'kernel-build.lock').open('a+') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaisesRegex(PortError, 'already running'):
                    rebuild(project)
            self.assertNotIn('kernel-chain', project.read_state()['stages'])

    def test_abi_plan_rejects_an_unexpected_source_instruction(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp) / 'abi.json'
            original = bytes.fromhex('084011f9')
            plan = {'instruction_fields': [{'address': '0x1000', 'expected_sha256': hashlib.sha256(original).hexdigest(),
                    'kind': 'instruction-immediate', 'mask': hex(4095 << 10), 'shift': 10, 'value': 2, 'reason': 'test field'}]}
            profile.write_text(json.dumps(plan))
            donor = Mock()
            donor.read.return_value = b'\0' * 4
            with self.assertRaisesRegex(PortError, 'source word changed'):
                load_plan(donor, profile)

    def test_abi_plan_cannot_overwrite_opcode_bits(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp) / 'abi.json'
            original = bytes.fromhex('084011f9')
            plan = {'instruction_fields': [{'address': '0x1000', 'expected_sha256': hashlib.sha256(original).hexdigest(),
                    'kind': 'instruction-immediate', 'mask': '0xffffffff', 'shift': 0, 'value': 0, 'reason': 'invalid field'}]}
            profile.write_text(json.dumps(plan))
            donor = Mock()
            donor.read.return_value = original
            with self.assertRaisesRegex(PortError, 'immediate mask'):
                load_plan(donor, profile)


if __name__ == "__main__":
    unittest.main()
