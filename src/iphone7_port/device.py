"""Live identity checks and explicit SSHRD collection; no global fake device."""

from __future__ import annotations

import os
import getpass
import plistlib
import re
import shlex
import subprocess
import tempfile
import sys
from pathlib import Path
from xml.parsers.expat import ExpatError

from .confirm import confirm_action, require_confirmed
from .core import PortError, Project, digest_file, load_json, require, save_json
from .console import paint, say
from .img4 import im4p_type, split_image, ticket_hash

STOCK_VERSION_PATH = "/mnt1/System/Library/CoreServices/SystemVersion.plist"
SEP_PATH_PATTERN = r"/mnt6/([0-9A-Fa-f]{96})/usr/standalone/firmware/sep-firmware\.img4"


def parse_query(text: str) -> dict:
    result = {}
    for line in text.splitlines():
        key, separator, value = line.partition(":")
        if separator and re.fullmatch(r"[A-Z][A-Z0-9_]*", key.strip()):
            result[key.strip()] = value.strip()
    for key in ["CPID", "ECID", "MODEL", "PRODUCT", "MODE"]:
        require(key in result, f"Live irecovery query is missing {key}.")
    for key in ["CPID", "ECID"]:
        require(bool(re.fullmatch(r"(?:0[xX])?[0-9a-fA-F]+", result[key])), f"Invalid device {key}.")
        result[key] = hex(int(result[key], 16))
    require(int(result["ECID"], 16) > 0, "A real nonzero ECID is required.")
    return result


def validate_device(project: Project, identity: dict, *, require_dfu=False):
    expected = project.profile["device"]
    require(identity["PRODUCT"] == expected["product"] and identity["MODEL"].lower() == expected["model"],
            "Only a real iPhone9,1 / D10AP is accepted. Build-time iPad overrides cannot be used for device queries.")
    require(identity["CPID"] == expected["cpid"], "Unexpected device CPID.")
    if require_dfu:
        require(identity["MODE"].upper() == "DFU", "Put the same phone in DFU mode, then rerun this command.")


def query_device(project: Project, *, require_dfu=False) -> dict:
    result = project.run([project.tool("irecovery"), "-q"], private=True, timeout=15)
    identity = parse_query(result.stdout)
    validate_device(project, identity, require_dfu=require_dfu)
    previous = project.read_state()["stages"].get("device")
    require(not previous or previous["identity"]["ECID"] == identity["ECID"],
            "A different ECID is connected. Use a separate project state for another phone.")
    project.record("device", {"identity": identity})
    say(f"Live device verified: {identity['PRODUCT']} / {identity['MODEL']} / {identity['MODE']}", 'success')
    return identity


class SSH:
    def __init__(self, project: Project, port: int, *, system=False):
        require(1 <= port <= 65535, "Invalid local SSH port.")
        self.project, self.port = project, port
        project.stage("device")
        # All callers address only root@127.0.0.1 through USB forwarding.
        # SSHRD and installed iOS intentionally have different/rebuilt keys.
        # The system argument remains accepted for existing command lines.

    def options(self):
        return ["-F", "/dev/null", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
                "-o", "GlobalKnownHostsFile=/dev/null", "-o", "CheckHostIP=no", "-o", "UpdateHostKeys=no",
                "-o", "LogLevel=ERROR",
                "-o", "ConnectTimeout=8", "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=2"]

    def environment(self, extra=None):
        env = os.environ.copy()
        env['SSHPASS'] = getattr(self.project, '_ssh_password', 'alpine')
        env.update(extra or {})
        return env

    def execute(self, arguments, *, env_extra=None, **kwargs):
        """Retry rejected authentication, never ordinary remote/file errors."""
        while True:
            try:
                return self.project.run(arguments, env=self.environment(env_extra), private=True, **kwargs)
            except PortError:
                report = load_json(self.project.root / 'logs/last-command.json', {})
                output = report.get('stderr', '') + '\n' + report.get('stdout', '')
                rejected = report.get('returncode') in (5, 255) and re.search(
                    r'permission denied, please try again|permission denied \([^\n]*(?:password|publickey)|authentication failed',
                    output, re.IGNORECASE)
                if not rejected:
                    raise
                require(sys.stdin.isatty(), 'SSH authentication failed. Rerun in an interactive terminal to enter the password.')
                say('SSH authentication failed. Enter the current root password to retry.', 'warning')
                password = getpass.getpass('Root SSH password (hidden; Ctrl-C cancels): ')
                require(bool(password), 'Password entry cancelled; no retry was started.')
                # Keep credentials in memory for this invocation only. Never
                # write configuration or place the password in argv/log files.
                self.project._ssh_password = password

    def run(self, command: str, timeout=60):
        return self.execute([self.project.tool("sshpass"), "-e", "ssh", *self.options(), "-p", str(self.port),
                                 "root@127.0.0.1", command], timeout=timeout,
                                live=command.startswith(('/sbin/newfs_apfs ', '/sbin/apfs_deletefs ', '/sbin/apfs_delfs ',
                                                         '/System/Library/Filesystems/apfs.fs/apfs_invert '))).stdout

    def transfer(self, source, destination, timeout=3600, *, recursive=False):
        transport = self.project.root / 'resources/ssh-transport.sh'
        require(transport.is_file() and os.access(transport, os.X_OK), 'Missing executable resources/ssh-transport.sh.')
        return self.execute(['scp', *(['-r'] if recursive else []), '-S', transport, '-O', *self.options(), '-P', str(self.port),
                                 str(source), str(destination)], timeout=timeout,
                            env_extra={'IPHONE7_SSHPASS': self.project.tool('sshpass')}, live=True)

    def interactive(self):
        """Attach SSH directly to the user's terminal without capturing commands."""
        # Authenticate separately so exiting a successful shell with code 5 or
        # 255 is not mistaken for a password rejection and replayed.
        self.run(':', timeout=30)
        env = self.environment()
        say(f'Opening interactive SSH: root@127.0.0.1:{self.port}')
        say("Type 'exit' or press Ctrl-D to disconnect.")
        result = subprocess.run([self.project.tool('sshpass'), '-e', 'ssh',
                                 *self.options(), '-t', '-p', str(self.port),
                                 'root@127.0.0.1'], env=env)
        # Inherit stdin/stdout/stderr and impose no session timeout. Interactive
        # commands and their output must never go through Project.run/logging.
        if result.returncode:
            say(f'SSH session ended with exit code {result.returncode}.', 'error')
        else:
            say('SSH session closed.', 'success')
        return result.returncode if result.returncode >= 0 else 128 - result.returncode

    def download(self, source: str, destination: Path):
        require(source == STOCK_VERSION_PATH or re.fullmatch(SEP_PATH_PATTERN, source) is not None,
                "Unexpected SSHRD collection source path.")
        require(not destination.exists(), f"Refusing to overwrite collected file: {destination}")
        self.transfer('root@127.0.0.1:' + shlex.quote(source), destination)


def read_stock_version(project: Project, ssh: SSH) -> dict:
    """Read XML or binary plist bytes without assuming plutil exists in SSHRD."""
    with tempfile.TemporaryDirectory(prefix=".stock-version-", dir=project.work) as temporary:
        local = Path(temporary) / "SystemVersion.plist"
        ssh.download(STOCK_VERSION_PATH, local)
        require(local.is_file() and 0 < local.stat().st_size <= 1024 * 1024, "Invalid mounted stock SystemVersion.plist size.")
        try:
            version = plistlib.loads(local.read_bytes())
        except (plistlib.InvalidFileException, ValueError, TypeError, OverflowError, ExpatError) as exc:
            raise PortError("Cannot parse the mounted stock SystemVersion.plist on the Mac.") from exc
        require(isinstance(version, dict) and isinstance(version.get("ProductBuildVersion"), str)
                and isinstance(version.get("ProductVersion"), str), "Mounted stock version plist is missing its version/build fields.")
        return version


def select_sep(candidates: list[str], active: str, requested: str | None) -> str:
    valid = []
    for path in candidates:
        match = re.fullmatch(SEP_PATH_PATTERN, path)
        if match:
            valid.append((match[1].upper(), path))
    if requested:
        require(bool(re.fullmatch(r"[0-9A-Fa-f]{96}", requested)), "Preboot hash must contain exactly 96 hexadecimal characters.")
        valid = [row for row in valid if row[0] == requested.upper()]
    elif re.fullmatch(r"[0-9A-Fa-f]{96}", active):
        valid = [row for row in valid if row[0] == active.upper()]
    require(len(valid) == 1, "Cannot uniquely identify the active SEP image. Inspect Preboot, then use --preboot-hash explicitly.")
    return valid[0][1]


def collect(project: Project, port=2222, preboot_hash=None, already_mounted=False):
    require_confirmed(project)
    project.stage("boot-bootstrap")
    ssh = SSH(project, port)
    version = ssh.run("/usr/bin/sw_vers -productVersion").strip()
    require(version == "15.6", f"Expected the 15.6 bootstrap SSHRD, received {version!r}. Do not collect from full iOS.")
    if not already_mounted:
        confirm_action("Run SSHRD /usr/bin/mount_filesystems. This mounts stock volumes and may initialize SEP/xART state.", "MOUNT FILESYSTEMS")
        ssh.run("/usr/bin/mount_filesystems", timeout=240)
    mount = ssh.run("/sbin/mount")
    require(bool(re.search(r" on /mnt6(?: |\()", mount)), "Preboot is not mounted on /mnt6. Mount it manually and use --already-mounted.")
    system = read_stock_version(project, ssh)
    build = system["ProductBuildVersion"]
    require(build == project.profile["stock"]["build"] and system["ProductVersion"] == project.profile["stock"]["version"],
            "Mounted stock rootfs is not the required 15.8.8 / 19H422 installation.")
    active = ssh.run("if [ -f /mnt6/active ]; then /bin/cat /mnt6/active; fi").strip()
    candidates = ssh.run("/usr/bin/find /mnt6 -name sep-firmware.img4 -type f", timeout=90).splitlines()
    source = select_sep(candidates, active, preboot_hash)
    identity = project.stage("device")["identity"]
    folder = project.work / "devices" / identity["ECID"] / "stock"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    sep = folder / "sep-firmware.img4"
    if not sep.exists():
        ssh.download(source, sep)
    else:
        say('Reusing the collected SEP image; checking its ticket against the live stock system.')
    require(0 < sep.stat().st_size < 16 * 1024 * 1024, "Unexpected SEP image size.")
    payload, ticket = split_image(sep.read_bytes())
    require(im4p_type(payload) in ("sepi", "rsep"), "The collected image is not a SEP firmware image.")
    ticket_file = folder / "device.im4m"
    ticket_file.write_bytes(ticket)
    ticket_file.chmod(0o600)
    sep.chmod(0o600)
    details = project.run([project.tool("img4tool"), "-a", ticket_file], private=True).stdout
    ecid = re.search(r"ECID:\s+ECID:\s+(\d+)", details)
    chip = re.search(r"CHIP:\s+CHIP:\s+(\d+)", details)
    require(ecid is not None and int(ecid[1]) == int(identity["ECID"], 16), "Collected ticket ECID does not match the live device.")
    require(chip is not None and int(chip[1]) == int(identity["CPID"], 16), "Collected ticket CPID does not match the live device.")
    hash_value = ticket_hash(ticket)
    directory_hash = source.split("/")[2].upper()
    require(hash_value == directory_hash, "The SEP ticket hash does not match its Preboot directory; review before reusing it.")
    receipt = {"ecid": identity["ECID"], "source": source, "preboot_hash": hash_value, "sep": str(sep),
               "ticket": str(ticket_file), "sep_hashes": digest_file(sep), "stock_build": build}
    from .stock_resources import capture_stock
    capture_stock(project, ssh)
    save_json(folder / "receipt.json", receipt)
    project.record("capture", receipt)
    say("Collected the stock SEP image and matching device IM4M. Private artifacts remain under work/devices/.", 'success')
    return ssh


REBOOT_REQUEST = "/bin/sh -c '[ -x /sbin/reboot ] || exit 127; trap \"\" HUP; (/bin/sleep 2; /sbin/reboot) </dev/null >/dev/null 2>&1 & echo REBOOT_SCHEDULED'"


def offer_reboot(project: Project, ssh: SSH, ask=input, *, completed_stage='capture'):
    """Schedule reboot after SSH exits; never wait for the device to return."""
    project.stage(completed_stage)
    record_name = 'post-capture-reboot' if completed_stage == 'capture' else 'post-install-reboot'
    if not sys.stdin.isatty() and ask is input:
        project.record(record_name, {'requested': False, 'status': 'noninteractive-skipped'})
        say('Complete. Reboot skipped because no interactive terminal is available.', 'success')
        return False
    while True:
        answer = ask(paint('Reboot the iPhone now? [y/N]: ', 'warning')).strip().lower()
        if answer in {'', 'n', 'no'}:
            project.record(record_name, {'requested': False, 'status': 'declined'})
            say('Complete. Reboot skipped; the iPhone remains in SSHRD.', 'success')
            return False
        if answer in {'y', 'yes'}:
            break
        say('Please enter y or n; Enter keeps the iPhone in SSHRD.', 'warning')
    project.record(record_name, {'requested': True, 'status': 'sending'})
    try:
        ssh.run(REBOOT_REQUEST, timeout=15)
    except PortError:
        report = load_json(project.root / 'logs/last-command.json', {})
        closed = re.search(r'connection.*(?:closed|reset)|broken pipe', report.get('stderr', ''), re.IGNORECASE)
        if report.get('returncode') == 255 and closed:
            project.record(record_name, {'requested': True, 'status': 'request-sent-disconnected'})
            say('Complete. Reboot request sent; SSH disconnected. Exiting without waiting for the device.', 'success')
            return True
        project.record(record_name, {'requested': True, 'status': 'failed'})
        raise
    project.record(record_name, {'requested': True, 'status': 'scheduled'})
    say('Complete. Reboot scheduled; exiting without waiting for the device.', 'success')
    return True
