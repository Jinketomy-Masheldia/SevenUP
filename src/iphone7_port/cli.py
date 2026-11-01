"""English-only terminal entry point. Device actions are explicit stages."""

import argparse
import json
import platform
import shutil
from pathlib import Path

from . import __version__
from .accessibility import Lockdown, enable_assistive_touch
from .clean import clean
from .confirm import confirm_preconditions, require_confirmed
from .core import PortError, Project, require
from .device import SSH, collect, offer_reboot, query_device
from .console import paint, say
from .firmware import fetch_bootstrap, locate_sources, prepare
from .kernel import import_reference, prepare_bootstrap_donor, prepare_research_input
from .kernel_chain import rebuild
from .install import InstallSSH, install_rootfs, install_cryptex, install_preboot, finalize_install, verify_ramdisk, installation_lock
from .install_media import prepare_install, read_media_receipt, verify_media
from .rootfs_patches import install_patches, verify_patches
from .rootfs_source import prepare_patches
from .assets import ASSETS, asset
from .trollstore import install_trollstore
from .sshrd import boot, build_bootstrap, build_ios16, build_system, forward


def parser():
    root = argparse.ArgumentParser(description="Experimental iPhone 7 Global / iOS 16.1 preparation tool")
    root.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[2])
    root.add_argument("--version", action="version", version=__version__)
    commands = root.add_subparsers(dest="command")
    commands.add_parser("start", help="Confirm each prerequisite and prepare firmware resources; never boots automatically")
    commands.add_parser("confirm", help="Confirm every prerequisite individually")
    commands.add_parser("status", help="Show local progress without exposing device identifiers")
    commands.add_parser("doctor", help="Check host tools and local resource availability")
    cleanup = commands.add_parser("clean", help="Remove disposable installation files and logs; preserve boot bundles, device state and IPSWs")
    cleanup_mode = cleanup.add_mutually_exclusive_group()
    cleanup_mode.add_argument('--install', action='store_true', help='Reset only installation media and rootfs archives; also preserve logs')
    cleanup_mode.add_argument('--all', dest='all_files', action='store_true', help='Delete ALL generated state, boot bundles, captured tickets and IPSW archives; preparation must be repeated')
    commands.add_parser("fetch-bootstrap", help="Fetch only pinned 15.6 SSHRD components; no full 15.6 IPSW or phone required")
    commands.add_parser("bootstrap-donor", help="Reproduce the exact SSHRD-patched 15.6 donor kernel; no phone required")
    inputs = commands.add_parser("kernel-input", help="Reproduce a pinned research kernel input, preserving its original patch state")
    inputs.add_argument("role", choices=["iphone7_bootstrap", "ipad_target", "iphone8_donor"])
    chain = commands.add_parser("kernel-build", help="Rebuild source kernel stages with full historical raw-hash checkpoints")
    chain.add_argument("--through", default="HC3", help="Stop after an explicit historical checkpoint (default: HC3)")
    chain.add_argument("--fresh", action="store_true", help="Rebuild in an empty private workspace, reusing only verified IPSW components")
    source = commands.add_parser("prepare", help="Verify MD5/SHA1 and safely extract pinned IPSW components")
    source.add_argument("--verify-only", action="store_true")
    source.add_argument("--allow-missing", action="store_true", help="Verify present files only; this does not complete resource preparation")
    commands.add_parser("device", help="Query and verify the real device; no fake ECID/serial/nonces")
    kernel = commands.add_parser("kernel", help="Stage the exact local HC3 development reference")
    kernel.add_argument("--reference", required=True, type=Path)
    build = commands.add_parser("build", help="Build an SSHRD or full-iOS boot bundle in an isolated workspace")
    build.add_argument("stage", choices=["bootstrap", "ios16-sshrd", "ios16"])
    start = commands.add_parser("boot", help="Explicitly boot an SSHRD or full iOS on its verified device")
    start.add_argument("stage", choices=["bootstrap", "ios16-sshrd", "ios16"])
    capture = commands.add_parser("capture", help="Run mount_filesystems and collect stock SEP/IM4M and D10 hardware resources")
    capture.add_argument("--port", type=int, default=2222)
    capture.add_argument("--preboot-hash")
    capture.add_argument("--already-mounted", action="store_true")
    capture.add_argument("--existing-forward", action="store_true")
    ssh = commands.add_parser("ssh", help="Open an interactive root shell through USB; type exit to disconnect")
    ssh.add_argument("--port", type=int, default=2222, help="Local forwarded SSH port (default: 2222)")
    ssh.add_argument("--existing-forward", action="store_true", help="Allow reuse of an existing local port forward")
    ssh.add_argument('--system', action='store_true', help='Compatibility flag; USB SSH accepts changing host keys in both SSHRD and full iOS')
    assistive = commands.add_parser('assistive-touch', help='Enable the floating Home button in full iOS over USB lockdown; no SSH or iproxy needed')
    assistive.add_argument('--udid', help='Select a USB device explicitly when multiple devices are attached')
    commands.add_parser('prepare-install', help='Prepare root.dmg, both Cryptex archives and rootfs fixes from firmware and captured stock files; no phone action')
    commands.add_parser('prepare-rootfs-patches', aliases=['import-rootfs-patches'], help='Reconstruct rootfs fixes from bundled recipes, IPSWs and captured stock files; no phone action')
    install = commands.add_parser('install', help='Explicitly deploy rootfs, Cryptex files, patches and Preboot in the 16.1 SSHRD')
    install.add_argument('step', nargs='?', choices=['all', 'rootfs', 'cryptex', 'patches', 'preboot', 'finalize', 'trollstore'], default='all')
    install.add_argument('--port', type=int, default=2222)
    install.add_argument('--existing-forward', action='store_true')
    install.add_argument('--without-ssh', action='store_true', help='Do not install the optional full-system SSH server')
    return root


def doctor(project: Project):
    print(f"Host: {platform.system()} {platform.machine()}")
    for tool in ["irecovery", "gaster", "img4", "img4tool", "iBoot64Patcher", "KPlooshFinder", "Kernel64Patcher3", "kerneldiff", "gtar", "iproxy", "sshpass", "pzb"]:
        try:
            print(f"{paint('OK:', 'success')} {tool}: {project.tool(tool)}")
        except PortError as exc:
            say(f"MISSING: {exc}", 'error')
    try:
        print(f"{paint('OK:', 'success')} ld64.lld: {project.linker()}")
    except PortError as exc:
        say(f'MISSING: {exc}', 'error')
    ready = bool(shutil.which('xcrun'))
    print(f"{paint('OK:' if ready else 'MISSING:', 'success' if ready else 'error')} xcrun / Xcode iPhoneOS SDK required for kernel helper compilation")
    for name in ASSETS:
        try:
            print(f"{paint('OK:', 'success')} pinned SSHRD resource: {asset(project, name)}")
        except PortError as exc:
            say(f'MISSING: {exc}', 'error')
    try:
        lockdown = Lockdown(project)
        for name, loaded in [('libimobiledevice', lockdown.mobile), ('libplist', lockdown.plist)]:
            print(f"{paint('OK:', 'success')} {name} (AssistiveTouch): {loaded._name}")
        say('USB lockdown libraries and required APIs loaded successfully.', 'success')
    except PortError as exc:
        say(f'MISSING: Optional AssistiveTouch dependency: {exc}', 'error')
        say('Install/update with: brew install libimobiledevice', 'warning')
    locate_sources(project, allow_missing=True)
    print("Device operations are not performed by doctor.")


def main(argv=None):
    args = parser().parse_args(argv)
    project = Project(args.project)
    try:
        if args.command is None:
            say("iPhone 7 Global / iOS 16.1 Port Tool (development preview)", 'title')
            print("Run './run.sh start' for individual prerequisite confirmations.")
            print("Run './run.sh doctor' to inspect tools and missing firmware without touching the phone.")
            print("Run './run.sh prepare-install' before the explicit SSHRD rootfs installation stage.")
            return 0
        if args.command == "start":
            confirm_preconditions(project)
            prepare(project)
            say("Resources prepared. Next: './run.sh fetch-bootstrap', then './run.sh kernel-build'. No device action has started.", 'success')
        elif args.command == "confirm":
            confirm_preconditions(project)
        elif args.command == "status":
            print(json.dumps({key: {"at": value["at"]} for key, value in project.read_state()["stages"].items()}, indent=2))
        elif args.command == "doctor":
            doctor(project)
        elif args.command == "clean":
            clean(project, install_only=args.install, all_files=args.all_files)
        elif args.command == "prepare":
            prepare(project, extract=not args.verify_only, allow_missing=args.allow_missing)
        elif args.command == "fetch-bootstrap":
            fetch_bootstrap(project)
        elif args.command == "bootstrap-donor":
            fetch_bootstrap(project)
            prepare_bootstrap_donor(project)
        elif args.command == "kernel-input":
            if args.role == "iphone7_bootstrap":
                fetch_bootstrap(project)
            prepare_research_input(project, args.role)
        elif args.command == "kernel-build":
            rebuild(project, args.through, fresh=args.fresh)
        elif args.command == "device":
            query_device(project)
        elif args.command == "kernel":
            import_reference(project, args.reference.expanduser().resolve())
        elif args.command == "build":
            {'bootstrap': build_bootstrap, 'ios16-sshrd': build_ios16, 'ios16': build_system}[args.stage](project)
        elif args.command == "boot":
            boot(project, args.stage)
        elif args.command == "capture":
            require_confirmed(project)
            project.stage("boot-bootstrap")
            with forward(project, args.port, use_existing=args.existing_forward):
                ssh = collect(project, args.port, args.preboot_hash, args.already_mounted)
                offer_reboot(project, ssh)
        elif args.command == "ssh":
            ssh = SSH(project, args.port, system=args.system)
            with forward(project, args.port, use_existing=args.existing_forward):
                return ssh.interactive()
        elif args.command == 'assistive-touch':
            enable_assistive_touch(project, args.udid)
        elif args.command == 'prepare-install':
            with installation_lock(project):
                prepare_patches(project)
                prepare_install(project)
        elif args.command in ('prepare-rootfs-patches', 'import-rootfs-patches'):
            with installation_lock(project):
                prepare_patches(project)
        elif args.command == 'install':
            # Check all host inputs before opening a device connection or
            # offering any destructive action.
            require_confirmed(project)
            if args.step == 'trollstore':
                ssh = InstallSSH(project, args.port)
                with installation_lock(project), forward(project, args.port, use_existing=args.existing_forward):
                    install_trollstore(project, ssh)
                return 0
            if args.step == 'finalize':
                ssh = InstallSSH(project, args.port)
                with installation_lock(project), forward(project, args.port, use_existing=args.existing_forward):
                    finalize_install(project, ssh)
                    offer_reboot(project, ssh, completed_stage='install-finalize')
                return 0
            say('Using prepared root.dmg.' if args.step == 'rootfs' else 'Checking prepared installation media on the Mac.')
            media = read_media_receipt(project) if args.step == 'rootfs' else verify_media(project)
            if args.step in ('all', 'patches'):
                say('Checking prepared rootfs patch archives on the Mac.')
            patches = verify_patches(project) if args.step in ('all', 'patches') else None
            with_ssh = not args.without_ssh
            ssh = InstallSSH(project, args.port)
            with installation_lock(project), forward(project, args.port, use_existing=args.existing_forward):
                verify_ramdisk(project, ssh)
                if args.step in ('all', 'patches') and with_ssh:
                    import sys
                    require(sys.stdin.isatty(), 'SSH selection requires an interactive terminal.')
                    answer = input(paint('Install full-system SSH? Recommended for first-boot setup and debugging. [Y/n]: ', 'warning')).strip().lower()
                    require(answer in ('', 'y', 'yes', 'n', 'no'), 'Please enter y or n.')
                    with_ssh = answer not in ('n', 'no')
                if args.step in ('all', 'patches') and with_ssh:
                    ssh.script('[ -x /usr/local/bin/dropbearkey ]\n')
                if args.step in ('all', 'rootfs'):
                    install_rootfs(project, ssh, media)
                if args.step in ('all', 'cryptex'):
                    install_cryptex(project, ssh, media)
                if args.step in ('all', 'patches'):
                    install_patches(project, ssh, patches, with_ssh=with_ssh)
                if args.step in ('all', 'preboot'):
                    install_preboot(project, ssh)
            say('Requested installation stage completed. The iPhone remains in SSHRD; full-iOS boot preparation is a separate stage.', 'success')
        return 0
    except PortError as exc:
        say(f"ERROR: {exc}", 'error')
        return 2
    except (OSError, ValueError, KeyError) as exc:
        say(f"ERROR: Local input or state is invalid: {exc}. No subsequent stage will run.", 'error')
        return 2
    except (KeyboardInterrupt, EOFError):
        say("\nStopped by the user. Completed stage records are preserved.", 'warning')
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
