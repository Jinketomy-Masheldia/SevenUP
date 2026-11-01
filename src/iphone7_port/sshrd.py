"""Isolated two-stage builds derived from SSHRD_Script, with explicit sources."""

from __future__ import annotations

from .console import say

import hashlib
import os
import platform
import plistlib
import shutil
import socket
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from .confirm import confirm_action, require_confirmed
from .assets import asset, bootstrap_ticket
from .core import Project, digest_file, load_json, publish_directory, require, save_json
from .device import query_device
from .firmware import fetch_bootstrap, resource
from .img4 import reticket, split_image, wrap
from .kernel import prepare_bootstrap_donor, reference


@contextmanager
def attached(project: Project, image: Path, mountpoint: Path, *, readonly=False):
    mountpoint.mkdir(parents=True, exist_ok=True)
    arguments = ["hdiutil", "attach", "-nobrowse", "-owners", "off", "-mountpoint", mountpoint]
    if readonly:
        arguments.append("-readonly")
    project.run([*arguments, image], timeout=180)
    try:
        yield mountpoint
    finally:
        # Never continue with a possibly mounted, incomplete image.
        project.run(["hdiutil", "detach", mountpoint], timeout=90)


def ssh_archive(project: Project) -> Path:
    return asset(project, 'ssh.tar.gz')


def build_ramdisk(project: Project, role: str, work: Path, output: Path, ticket: bytes):
    source = work / "source-ramdisk.dmg"
    writable = work / "ssh-ramdisk.dmg"
    project.run([project.tool("img4"), "-i", resource(project, role, "RestoreRamDisk"), "-o", source])
    with attached(project, source, work / "mount-source", readonly=True) as mount:
        project.run(["hdiutil", "create", "-size", "384m", "-fs", "HFS+", "-layout", "NONE", "-format", "UDRW",
                     "-srcfolder", mount, "-copyuid", "root", writable], timeout=600)
    with attached(project, writable, work / "mount-ssh") as mount:
        project.run([project.tool("gtar"), "-x", "--no-overwrite-dir", "-f", ssh_archive(project), "-C", mount])
        require((mount / "usr/bin/mount_filesystems").is_file(), "The SSH payload does not provide mount_filesystems.")
        require((mount / "usr/local/bin/dropbear").is_file(), "The SSH payload does not provide Dropbear.")
    project.run(["hdiutil", "resize", "-sectors", "min", writable])
    make_image(project, writable, output, ticket, "rdsk", raw=True)


def make_image(project: Project, source: Path, output: Path, ticket: bytes, kind: str, *, raw=False):
    ticket_file = output.parent / "build.im4m"
    ticket_file.write_bytes(ticket)
    ticket_file.chmod(0o600)
    arguments = [project.tool("img4"), "-i", source, "-o", output, "-M", ticket_file, "-T", kind]
    if raw:
        arguments.append("-A")
    project.run(arguments)
    _, actual_ticket = split_image(output.read_bytes())
    require(actual_ticket == ticket, f"Ticket mismatch after building {output.name}.")


def receipt(project: Project, folder: Path, stage: str, ticket: bytes, identity: dict, extra=None):
    images = {}
    for path in sorted(folder.glob("*.img4")):
        _, actual_ticket = split_image(path.read_bytes())
        require(actual_ticket == ticket, f"Mixed IM4M inputs: {path.name}")
        images[path.name] = digest_file(path)
    record = {"stage": stage, "ecid": identity["ECID"], "cpid": identity["CPID"],
              "real_product": identity["PRODUCT"], "real_model": identity["MODEL"],
              "ticket_sha256": hashlib.sha256(ticket).hexdigest(), "images": images,
              "boot_args": project.profile["ramdisk_boot_args"], **(extra or {})}
    save_json(folder / "receipt.json", record)
    return record


def build_bootstrap(project: Project):
    require_confirmed(project)
    require(platform.system() == "Darwin", "The initial release builds ramdisks on macOS only.")
    # Verify all local resources before asking the phone to change state.
    fetch_bootstrap(project)
    for name in ["iBSS", "iBEC", "KernelCache", "DeviceTree", "RestoreRamDisk", "RestoreTrustCache"]:
        resource(project, "iphone7_bootstrap", name)
    prepare_bootstrap_donor(project)
    ssh_archive(project)
    ticket = bootstrap_ticket(project)
    destination = project.output / "bootstrap-15.6"
    require(not destination.exists(), f"Output already exists: {destination}")
    confirm_action("Decrypt and build the 15.6 SSHRD using the connected D10 in DFU mode. No partitions will be created.", "BUILD BOOTSTRAP")
    identity = query_device(project, require_dfu=True)
    project.run([project.tool("gaster"), "pwn"], private=True, timeout=90)
    parent = project.work / "build"
    parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="bootstrap-", dir=parent))
    images = work / "images"
    images.mkdir()
    try:
        for component, kind in [("iBSS", "ibss"), ("iBEC", "ibec")]:
            decoded, patched = work / f"{component}.dec", work / f"{component}.patched"
            project.run([project.tool("gaster"), "decrypt", resource(project, "iphone7_bootstrap", component), decoded])
            command = [project.tool("iBoot64Patcher"), decoded, patched]
            if component == "iBEC":
                command += ["-b", project.profile["ramdisk_boot_args"], "-n"]
            project.run(command)
            make_image(project, patched, images / f"{component}.img4", ticket, kind, raw=True)
        donor_folder = project.work / "kernel-inputs/iphone7_bootstrap"
        patched, patch = donor_folder / "kernel.sshrd.raw", donor_folder / "kernel.bpatch"
        source_kernel = resource(project, "iphone7_bootstrap", "KernelCache")
        ticket_file = images / "build.im4m"
        ticket_file.write_bytes(ticket)
        project.run([project.tool("img4"), "-i", source_kernel, "-o", images / "kernelcache.img4",
                     "-M", ticket_file, "-T", "rkrn", "-P", patch])
        # The migration donor is the SSHRD-patched kernel, not a pristine IPSW kernel.
        donor = work / "iphone7-15.6-sshrd.raw"
        project.run([project.tool("img4"), "-i", images / "kernelcache.img4", "-o", donor])
        require(donor.read_bytes() == patched.read_bytes(), "Packed bootstrap kernel differs from the patcher output.")
        donor_hash = digest_file(donor, ("sha256",))["sha256"]
        expected_donor = load_json(project.root / "profiles/kernel-reference.json")["research_input_raw_sha256"]["iphone7_bootstrap"]
        say(f"15.6 SSHRD-patched donor SHA256: {donor_hash}", 'success')
        say(f"Matches the historical research donor: {donor_hash == expected_donor}", 'success' if donor_hash == expected_donor else 'warning')
        make_image(project, resource(project, "iphone7_bootstrap", "DeviceTree"), images / "devicetree.img4", ticket, "rdtr")
        make_image(project, resource(project, "iphone7_bootstrap", "RestoreTrustCache"), images / "trustcache.img4", ticket, "rtsc")
        build_ramdisk(project, "iphone7_bootstrap", work, images / "ramdisk.img4", ticket)
        record = receipt(project, images, "bootstrap", ticket, identity, {"version": "15.6", "sep_loaded_by_mount_filesystems": True})
        publish_directory(images, destination)
        project.record("build-bootstrap", {"folder": str(destination), "receipt": record,
                       "patched_donor": str(donor), "patched_donor_sha256": donor_hash,
                       "historical_donor_match": donor_hash == expected_donor})
        say("15.6 bootstrap SSHRD built. Run 'boot bootstrap' when ready.", 'success')
    finally:
        # Retain failed build work for diagnosis; never remove a mounted directory.
        say(f"Build workspace retained: {work}", 'info')


def build_ios16(project: Project):
    require_confirmed(project)
    require(platform.system() == "Darwin", "The initial release builds ramdisks on macOS only.")
    capture = project.stage("capture")
    identity = project.stage("device")["identity"]
    require(capture["ecid"] == identity["ECID"], "Captured firmware belongs to a different ECID.")
    original_sep = Path(capture["sep"])
    require(digest_file(original_sep) == capture["sep_hashes"], "Collected SEP image changed.")
    _, ticket = split_image(original_sep.read_bytes())
    require(ticket == Path(capture["ticket"]).read_bytes(), "Captured IM4M changed.")
    bootstrap = Path(project.stage("build-bootstrap")["folder"])
    check_images(bootstrap)
    kernel = reference(project)
    for name in ["RestoreRamDisk", "RestoreTrustCache"]:
        resource(project, "ipad_target", name)
    destination = project.output / "ios16-sshrd"
    require(not destination.exists(), f"Output already exists: {destination}")
    parent = project.work / "build"
    parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="ios16-", dir=parent))
    images = work / "images"
    images.mkdir()
    # These are D10 bootstrap payloads, not iPad DFU/DT payloads.
    for name in ["iBSS.img4", "iBEC.img4", "devicetree.img4"]:
        (images / name).write_bytes(reticket((bootstrap / name).read_bytes(), ticket))
    (images / "sep.img4").write_bytes(original_sep.read_bytes())
    (images / "kernelcache.img4").write_bytes(reticket(kernel.read_bytes(), ticket))
    make_image(project, resource(project, "ipad_target", "RestoreTrustCache"), images / "trustcache.img4", ticket, "rtsc")
    build_ramdisk(project, "ipad_target", work, images / "ramdisk.img4", ticket)
    # IMG4 bytes change with the user's ticket; the compressed IM4P must not.
    require(split_image((images / "kernelcache.img4").read_bytes())[0] == split_image(kernel.read_bytes())[0],
            "The HC3 kernel IM4P changed during device-ticket wrapping.")
    raw = work / "final-kernel.raw"
    project.run([project.tool("img4"), "-i", images / "kernelcache.img4", "-o", raw])
    lock = load_json(project.root / "profiles/kernel-reference.json")
    require(digest_file(raw, ("sha256",))["sha256"] == lock["raw_sha256"], "Final kernel payload is not byte-identical to HC3.")
    record = receipt(project, images, "ios16-sshrd", ticket, identity,
                     {"version": "16.1", "resource_product": "iPad7,5", "resource_model": "j71bap",
                      "kernel_raw_sha256": lock["raw_sha256"], "device_ticket_sha384": capture["preboot_hash"]})
    publish_directory(images, destination)
    project.record("build-ios16-sshrd", {"folder": str(destination), "receipt": record})
    say("iOS 16.1 SSHRD built with D10 bootloaders/DT, stock SEP, device IM4M, and exact HC3 kernel payload.", 'success')


def check_images(folder: Path) -> dict:
    record = load_json(folder / "receipt.json")
    require(record.get("stage") in {"bootstrap", "ios16-sshrd", "ios16"}, "Unrecognized boot bundle stage.")
    expected_names = {"iBSS.img4", "iBEC.img4", "devicetree.img4", "kernelcache.img4", "trustcache.img4", "ramdisk.img4"}
    if record["stage"] != "bootstrap":
        expected_names.add("sep.img4")
    if record['stage'] == 'ios16':
        expected_names.remove('ramdisk.img4')
        require(record.get('boot_args', '').split().count('rd=disk1s8') == 1 and
                not any(arg.startswith(('rd=', 'rootdev=')) and arg != 'rd=disk1s8'
                        for arg in record['boot_args'].split()), 'Full iOS must boot disk1s8, never a ramdisk.')
    require(set(record["images"]) == expected_names, "The boot bundle does not contain exactly the required images.")
    for name, expected in record["images"].items():
        path = folder / name
        require(path.is_file() and digest_file(path) == expected, f"Boot image changed or missing: {name}")
        _, ticket = split_image(path.read_bytes())
        require(hashlib.sha256(ticket).hexdigest() == record["ticket_sha256"], f"Mixed ticket in {name}")
    return record


def build_system(project: Project):
    """Reuse the verified 16.1 bundle, rebuilding only the D10 iBEC arguments."""
    require_confirmed(project)
    source = Path(project.stage('build-ios16-sshrd')['folder'])
    source_record = check_images(source)
    identity = project.stage('device')['identity']
    require(source_record['stage'] == 'ios16-sshrd' and source_record['ecid'] == identity['ECID'],
            'Build the 16.1 SSHRD for this phone first.')
    capture = project.stage('capture')
    _, ticket = split_image((source / 'sep.img4').read_bytes())
    require(capture['ecid'] == identity['ECID'] and ticket == Path(capture['ticket']).read_bytes(),
            'The full-iOS bundle must use this phone\'s captured ticket.')
    destination = project.output / 'ios16'
    require(not destination.exists(), f'Output already exists: {destination}')
    # Retained stock plaintext from the bootstrap build avoids needing a second
    # DFU decryption. Reproduce the original patch before trusting this input.
    bootstrap_stage = project.stage('build-bootstrap')
    bootstrap = Path(bootstrap_stage['folder'])
    check_images(bootstrap)
    decoded = Path(bootstrap_stage['patched_donor']).parent / 'iBEC.dec'
    require(decoded.is_file(), 'Missing retained bootstrap iBEC.dec. Rebuild the bootstrap before creating full-iOS boot files.')
    parent = project.work / 'build'
    parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='ios16-system-', dir=parent))
    images = work / 'images'
    images.mkdir()
    original = work / 'bootstrap-ibec.raw'
    reproduced = work / 'bootstrap-ibec.reproduced'
    project.run([project.tool('img4'), '-i', bootstrap / 'iBEC.img4', '-o', original])
    project.run([project.tool('iBoot64Patcher'), decoded, reproduced,
                 '-b', project.profile['ramdisk_boot_args'], '-n'])
    require(original.read_bytes() == reproduced.read_bytes(), 'Retained iBEC.dec does not reproduce the verified bootstrap iBEC.')
    arguments = project.profile['system_boot_args']
    require(arguments.split().count('rd=disk1s8') == 1 and
            not any(arg.startswith(('rd=', 'rootdev=')) and arg != 'rd=disk1s8' for arg in arguments.split()),
            'Full-system boot arguments must select disk1s8 only.')
    patched = work / 'iBEC.disk1s8'
    project.run([project.tool('iBoot64Patcher'), decoded, patched, '-b', arguments, '-n'])
    require(arguments.encode() + b'\0' in patched.read_bytes(), 'The patched iBEC does not contain the requested boot arguments.')
    for name in ('iBSS.img4', 'devicetree.img4', 'trustcache.img4', 'sep.img4', 'kernelcache.img4'):
        shutil.copyfile(source / name, images / name)
    make_image(project, patched, images / 'iBEC.img4', ticket, 'ibec', raw=True)
    record = receipt(project, images, 'ios16', ticket, identity,
                     {'version': '16.1', 'boot_args': arguments, 'root_volume': '/dev/disk1s8',
                      'device_ticket_sha384': capture['preboot_hash'],
                      'kernel_raw_sha256': source_record['kernel_raw_sha256']})
    check_images(images)
    publish_directory(images, destination)
    project.record('build-ios16', {'folder': str(destination), 'receipt': record})
    say('Full iOS 16.1 boot bundle built: disk1s8, unchanged HC3 kernel, no AVE and no ramdisk.', 'success')


def boot(project: Project, stage: str):
    require_confirmed(project)
    state_name = 'build-' + stage
    folder = Path(project.stage(state_name)["folder"])
    record = check_images(folder)
    require(record['stage'] == stage, 'Boot bundle stage mismatch.')
    if stage == 'ios16':
        installed = project.stage('install-rootfs')
        require(project.stage('install-finalize')['installation_id'] == installed['installation_id'],
                'Run install finalize for this installation before the first full-iOS boot.')
    confirm_action(f"Boot {stage} on the same iPhone. This changes its running boot state but does not format storage.",
                   'BOOT IOS16' if stage == 'ios16' else 'BOOT RAMDISK')
    identity = query_device(project, require_dfu=True)
    require(identity["ECID"] == record["ecid"], "Boot artifacts were created for another phone.")
    project.run([project.tool("gaster"), "pwn"], private=True, timeout=90)
    project.run([project.tool("gaster"), "reset"], private=True)
    def recovery(*args):
        project.run([project.tool("irecovery"), "-i", identity["ECID"], *args], private=True, timeout=120, live=True)
    recovery("-f", folder / "iBSS.img4")
    time.sleep(2)
    recovery("-f", folder / "iBEC.img4")
    recovery("-c", "go")
    time.sleep(2)
    if stage != 'ios16':
        recovery("-f", folder / "ramdisk.img4")
        recovery("-c", "ramdisk")
    recovery("-f", folder / "devicetree.img4")
    recovery("-c", "devicetree")
    if stage == 'ios16':
        recovery('-f', folder / 'trustcache.img4')
        recovery('-c', 'firmware')
    if stage != "bootstrap":
        recovery("-f", folder / "sep.img4")
        recovery("-c", "rsepfirmware")
    if stage != 'ios16':
        recovery("-f", folder / "trustcache.img4")
        recovery("-c", "firmware")
    recovery("-f", folder / "kernelcache.img4")
    recovery("-c", "bootx")
    project.record('boot-' + stage,
                   {"ecid": identity["ECID"], "commands_sent": True, "ssh_verified": False})
    if stage == 'ios16':
        say('Full-iOS boot commands sent. Allow first-boot migration to finish, then connect with ./run.sh ssh --system.', 'success')
        say('Built-in iOS apps may crash after migration. This is a known issue; delete the affected apps and download them again from the App Store to fix it.', 'warning')
    else:
        say("Boot commands sent. This does not prove the ramdisk has booted; verify SSH before collecting files.", 'success')


@contextmanager
def forward(project: Project, port: int, *, use_existing=False):
    require(1 <= port <= 65535, "Invalid local port.")
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            occupied = True
    except OSError:
        occupied = False
    if occupied:
        require(use_existing, f"Port {port} is already in use. Keep its owner untouched; choose another port or explicitly use --existing-forward.")
        yield
        return
    process = subprocess.Popen([project.tool("iproxy"), str(port), "22"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            require(process.poll() is None, "iproxy exited before opening the local port.")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                    break
            except OSError:
                time.sleep(0.2)
        else:
            require(False, "iproxy did not open the local port in time.")
        yield
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
