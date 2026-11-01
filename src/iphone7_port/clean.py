"""Clean disposable files; remove boot resources and IPSWs only with --all."""

import fcntl
import os
import re
import shutil
import subprocess
from contextlib import ExitStack
from pathlib import Path

from .console import say
from .core import PortError, Project, require, save_json


def mounted_paths():
    # Do not use Project.run: it would create the directories being cleaned.
    try:
        result = subprocess.run(['/sbin/mount'], capture_output=True, text=True,
                                check=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        raise PortError('Cannot inspect mounted filesystems; nothing was cleaned.') from exc
    paths = []
    for line in result.stdout.splitlines():
        if ' on ' in line and ' (' in line:
            value = line.split(' on ', 1)[1].rsplit(' (', 1)[0]
            value = re.sub(r'\\([0-7]{3})', lambda match: chr(int(match[1], 8)), value)
            paths.append(Path(value).resolve())
    return paths


def cache_directories(root):
    for name in ('src', 'tests', 'tools'):
        parent = root / name
        if parent.is_symlink() or not parent.is_dir():
            continue
        for current, directories, _ in os.walk(parent, followlinks=False):
            if '__pycache__' in directories:
                yield Path(current) / '__pycache__'
                directories.remove('__pycache__')


def clean(project: Project, *, install_only=False, all_files=False):
    require(not (install_only and all_files), 'Choose either --install or --all.')
    require(not project.work.is_symlink(), 'Refusing a symbolic work directory. Nothing was cleaned.')
    firmware = []
    if all_files:
        say('FULL CLEAN: removing all generated state, boot bundles, captured SEP/IM4M and D10 files, logs, and IPSW archives. You will need to prepare everything again before booting iOS16.', 'warning')
        targets = [project.work, project.output, project.root / 'logs']
        targets.extend(cache_directories(project.root))
        inputs = project.root / 'inputs'
        ipsws = inputs / 'ipsw'
        require(not inputs.is_symlink() and not ipsws.is_symlink(), 'Refusing symbolic firmware input directories. Nothing was cleaned.')
        if ipsws.exists():
            require(ipsws.is_dir(), 'Expected inputs/ipsw to be a directory. Nothing was cleaned.')
            firmware = [path for path in ipsws.iterdir() if path.suffix.lower() == '.ipsw']
    else:
        say('IPSW files will NOT be deleted. Boot bundles, device tickets, captured D10 resources, build files and installation progress are preserved.', 'warning')
        targets = [project.work / name for name in ('install-media', 'install-patches', 'install-tools', 'rootfs-source')]
        if not install_only:
            targets += [project.root / 'logs', *cache_directories(project.root)]
    # Validate every target before removing anything. Never follow a redirected
    # generated directory, even when its destination is inside the project.
    for target in targets:
        require(not target.is_symlink(), f'Refusing to clean a symbolic link: {target}. Nothing was cleaned.')
        require(not target.exists() or target.is_dir(),
                f'Expected a generated directory: {target}. Nothing was cleaned.')
    for target in firmware:
        require(not target.is_symlink() and target.is_file(), f'Refusing a symbolic or non-file IPSW: {target}. Nothing was cleaned.')
    targets = [target for target in targets if target.exists()]
    reset_receipt = not all_files and 'install-media' in project.read_state()['stages']
    for mount in mounted_paths() if targets or firmware else []:
        for target in targets:
            require(not mount.is_relative_to(target),
                    f'A filesystem is mounted inside {target.relative_to(project.root)}. Detach it before cleaning. Nothing was cleaned.')
    with ExitStack() as stack:
        for filename, operation in [('kernel-build.lock', 'kernel build'), ('install.lock', 'rootfs installation or preparation')]:
            lock_path = project.work / filename
            require(not lock_path.is_symlink(), f'Refusing a symbolic {filename}. Nothing was cleaned.')
            if lock_path.exists():
                lock = stack.enter_context(lock_path.open('r+'))
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise PortError(f'A {operation} is active. Wait for it to finish before cleaning. Nothing was cleaned.') from exc
        if not targets and not firmware and not reset_receipt:
            say('Already clean. Boot resources and IPSWs were retained.' if not all_files else 'Already fully clean.', 'success')
            return
        for target in targets:
            shutil.rmtree(target)
            say(f'Removed: {target.relative_to(project.root)}')
        for target in firmware:
            target.unlink()
            say(f'Removed: {target.relative_to(project.root)}')
        if reset_receipt:
            state = project.read_state()
            state['stages'].pop('install-media', None)
            save_json(project.work / 'state.json', state)
    if all_files:
        say('Full clean complete, including IPSW archives and boot resources. Add the two IPSWs and run ./run.sh start to begin again.', 'success')
    elif install_only:
        say('Install resources reset. IPSW files and SSHRD progress were retained. Next: ./run.sh prepare-install', 'success')
    else:
        say('Clean complete. Existing boot bundles and their required state were retained. You can still run ./run.sh boot ios16 if its preparation was completed.', 'success')
