"""Explicit SSHRD deployment to disk1s8; never invoke mount_filesystems."""

import json
import fcntl
import plistlib
import re
import shlex
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

from .confirm import confirm_action, require_confirmed
from .console import say
from .core import PortError, Project, require
from .device import SSH
from .install_media import MEDIA
from .registry import read_registry

TARGET = '/mnt8'
CONTAINER = '/dev/disk0s1'
VOLUME = '/dev/disk1s8'
MARKER = TARGET + '/.iphone7-ios16-install.json'
ENV = 'export PATH=/usr/local/bin:/usr/local/sbin:/usr/bin:/bin:/usr/sbin:/sbin\nset -eu\numask 022\n'


@contextmanager
def installation_lock(project):
    project.initialize()
    path = project.work / 'install.lock'
    require(not path.is_symlink(), 'Refusing a symbolic installation lock.')
    with path.open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PortError('Another installation or install-media preparation is active.') from exc
        yield


def walk(nodes):
    if isinstance(nodes, dict):
        yield nodes
        yield from walk(nodes.get('IORegistryEntryChildren', []))
    elif isinstance(nodes, list):
        for node in nodes:
            yield from walk(node)


def inventory(data):
    nodes = read_registry(data)
    physical = [node for node in walk(nodes) if node.get('BSD Name') == 'disk0s1']
    require(len(physical) == 1, 'Cannot uniquely locate the disk0s1 physical store.')
    media = [node for node in walk(physical[0]) if node.get('BSD Name') == 'disk1']
    require(len(media) == 1, 'disk1 is not the verified synthesized container of disk0s1.')
    containers = [node for node in walk(media[0]) if node.get('IOClass') == 'AppleAPFSContainer']
    require(len(containers) == 1 and containers[0].get('UUID'), 'Cannot uniquely identify the APFS container.')
    volumes = {}
    for node in walk(containers[0]):
        name = node.get('BSD Name', '')
        if re.fullmatch(r'disk1s[1-9][0-9]*', name):
            index = int(name[6:])
            require(index not in volumes and node.get('UUID'), 'Duplicate or unidentified APFS volume.')
            volumes[index] = {'device': '/dev/' + name, 'uuid': node['UUID'],
                              'name': node.get('FullName', node.get('IORegistryEntryName', name)),
                              'role': node.get('RoleValue')}
    require(set(range(1, 8)).issubset(volumes), 'Expected all seven stock volumes disk1s1 through disk1s7.')
    require([volumes[n]['role'] for n in range(1, 8)] == [1, 64, 256, 128, 320, 16, 192],
            'Stock APFS roles differ from the supported D10 layout. No volume will be changed.')
    return {'uuid': containers[0]['UUID'], 'volumes': volumes}


def mounts(text):
    result = []
    for line in text.splitlines():
        match = re.fullmatch(r'(\S+) on (.+?) \([^\n]*\)', line.strip())
        require(match is not None, f'Cannot parse mounted filesystem: {line!r}')
        result.append((match[1], match[2]))
    return result


def container_mounts(text):
    return [(device, path) for device, path in mounts(text)
            if re.fullmatch(r'/dev/disk1(?:s[0-9]+)*|/dev/disk0s1(?:s[0-9]+)*', device)]


def ramdisk_root(text):
    roots = [device for device, path in mounts(text) if path == '/']
    if len(roots) != 1:
        return False
    if re.fullmatch(r'/dev/md[0-9]+(?:s[0-9]+)*', roots[0]):
        return True
    # This generated SSHRD reports its HFS memory disk as root_device rather
    # than a BSD md node. The alias alone is insufficient: full iOS may also
    # use it, so require the HFS filesystem in this compatibility case.
    return roots[0] == 'root_device' and any(
        re.fullmatch(r'root_device on / \(hfs(?:, [^\n()]*)?\)', line.strip())
        for line in text.splitlines())


def deletion_plan(info):
    return [info['volumes'][index] for index in sorted(info['volumes'], reverse=True) if index >= 8]


class InstallSSH(SSH):
    def script(self, script, timeout=180, label=None, live=False):
        lines = [line.strip() for line in script.splitlines() if line.strip()]
        summary = label or ('ssh script: ' + '; '.join(lines[:2]) + (f' [{len(lines)} lines]' if len(lines) > 2 else ''))
        return self.execute([self.project.tool('sshpass'), '-e', 'ssh', *self.options(), '-p', str(self.port),
                                 'root@127.0.0.1', '/bin/sh -s'], input=ENV + script,
                                timeout=timeout, label=summary, live=live).stdout

    def upload(self, source, destination, timeout=3600):
        require(Path(source).is_file(), f'Missing upload source: {source}')
        require(destination.startswith('/mnt8/') and '\n' not in destination,
                'Unexpected installation upload path.')
        say(f'Uploading: {Path(source).name}')
        self.transfer(Path(source).absolute(), 'root@127.0.0.1:' + shlex.quote(destination), timeout=timeout)

    def target_version(self):
        with tempfile.TemporaryDirectory(prefix='install-version-', dir=self.project.work) as temp:
            path = Path(temp) / 'SystemVersion.plist'
            self.transfer('root@127.0.0.1:/mnt8/System/Library/CoreServices/SystemVersion.plist', path)
            return plistlib.loads(path.read_bytes())


def inspect(ssh):
    return inventory(ssh.run('/usr/sbin/ioreg -l -w 0', timeout=45))


def verify_ramdisk(project, ssh):
    require_confirmed(project)
    project.stage('boot-ios16-sshrd')
    identity = project.stage('device')['identity']
    output = ssh.run('/usr/bin/sw_vers')
    version = {}
    for line in output.splitlines():
        key, separator, value = line.partition(':')
        if separator:
            version[key.strip()] = value.strip()
    require(version.get('ProductVersion') == project.profile['target']['version'] and
            version.get('BuildVersion') == project.profile['target']['build'],
            'sw_vers must report iOS 16.1 / 20B82. Boot the prepared 16.1 SSHRD first.')
    say('SSHRD sw_vers verified: iOS 16.1 / 20B82.', 'success')
    require(ramdisk_root(ssh.run('/sbin/mount')),
            'The root filesystem is not a ramdisk. Never run the installer in full iOS.')
    say('Reading live device identity from the registry.')
    chosen = read_registry(ssh.run('/usr/sbin/ioreg -l -w 0 -p IODeviceTree -r -n chosen'))
    values = set()
    for node in walk(chosen):
        for key in ('unique-chip-id', 'ecid', 'ECID'):
            value = node.get(key)
            if isinstance(value, bytes) and len(value) == 8:
                values.update(int.from_bytes(value, order) for order in ('little', 'big'))
            elif isinstance(value, int):
                values.add(value)
    require(int(identity['ECID'], 16) in values, 'The SSH-connected phone ECID does not match this project.')
    require(ssh.run('/usr/sbin/sysctl -n hw.machine').strip() == 'iPhone9,1', 'Unsupported SSH-connected device model.')
    say('Checking the APFS container and volume layout.')
    return inspect(ssh)


def unmount_container(ssh):
    rows = container_mounts(ssh.run('/sbin/mount'))
    require(all(path != '/' for _, path in rows), 'Refusing to unmount a live system root.')
    for _, path in sorted(rows, key=lambda row: len(Path(row[1]).parts), reverse=True):
        say(f'Unmounting container volume: {path}')
        ssh.run('/sbin/umount ' + shlex.quote(path))
    require(not container_mounts(ssh.run('/sbin/mount')), 'An APFS container volume is still mounted; stopping before invert.')


def mount_target(ssh):
    rows = mounts(ssh.run('/sbin/mount'))
    require(not any(path == TARGET and device != VOLUME for device, path in rows), '/mnt8 is occupied by another filesystem.')
    if (VOLUME, TARGET) not in rows:
        require(not any(device == VOLUME for device, _ in rows), 'disk1s8 is already mounted elsewhere.')
        ssh.script('[ ! -L /mnt8 ]\nmkdir -p /mnt8\n/sbin/mount_apfs /dev/disk1s8 /mnt8\n')
    require((VOLUME, TARGET) in mounts(ssh.run('/sbin/mount')), 'disk1s8 did not mount on /mnt8.')


def delete_tool(ssh):
    candidates = ['/sbin/apfs_deletefs', '/usr/sbin/apfs_deletefs', '/usr/bin/apfs_deletefs',
                  '/sbin/apfs_delfs', '/usr/sbin/apfs_delfs', '/usr/bin/apfs_delfs']
    command = 'for p in ' + ' '.join(candidates) + '; do if [ -x "$p" ]; then printf "%s\\n" "$p"; break; fi; done\n'
    path = ssh.script(command).strip()
    require(path in candidates, 'No supported apfs_delfs/apfs_deletefs utility is installed in SSHRD.')
    return path


def install_rootfs(project, ssh, media):
    info = verify_ramdisk(project, ssh)
    old = deletion_plan(info)
    tool = delete_tool(ssh) if old else None
    ssh.script('[ -x /sbin/newfs_apfs ]\n[ -x /sbin/mount_apfs ]\n[ -x /System/Library/Filesystems/apfs.fs/apfs_invert ]\n')
    if old:
        for volume in old:
            say(f"DELETE: {volume['device']}  name={volume['name']}  role={volume['role']}  UUID={volume['uuid']}", 'warning')
        token = 'DELETE ' + ' '.join(volume['device'].removeprefix('/dev/') for volume in old)
        confirm_action('These existing additional volumes will be permanently removed before disk1s8 is recreated. Stock disk1s1 through disk1s7 are retained.', token)
    else:
        confirm_action('Create disk1s8 and install the iPad-based iOS16.1 root filesystem. Stock disk1s1 through disk1s7 are retained.', 'INSTALL DISK1S8')
    initial = inspect(ssh)
    require(initial == info, 'APFS layout changed during confirmation. Run the command again.')
    # Every stock and additional container volume must be unmounted, not just /mnt8.
    unmount_container(ssh)
    for volume in old:
        # Recheck identity/layout after each deletion, before addressing the next node.
        current = inspect(ssh)
        require(current['uuid'] == info['uuid'] and current['volumes'].get(int(volume['device'][11:])) == volume,
                'Deletion target changed; stopping.')
        require(not container_mounts(ssh.run('/sbin/mount')), 'A container volume was remounted before deletion.')
        ssh.run(tool + ' ' + shlex.quote(volume['device']), timeout=180)
        require(volume['device'] not in [v['device'] for v in inspect(ssh)['volumes'].values()], 'Volume deletion was not reflected in the registry.')
    current = inspect(ssh)
    require(current['uuid'] == info['uuid'] and set(current['volumes']) == set(range(1, 8)),
            'Expected exactly disk1s1 through disk1s7 before creation.')
    ssh.run('/sbin/newfs_apfs -A -D -o role=r -v Xystem /dev/disk0s1', timeout=180)
    created = inspect(ssh)
    require(created['uuid'] == info['uuid'] and set(created['volumes']) == set(range(1, 9)), 'Volume creation did not produce exactly disk1s8.')
    require(created['volumes'][8]['role'] == 4 and created['volumes'][8]['name'] == 'Xystem', 'New disk1s8 has an unexpected name or role.')
    mount_target(ssh)
    root = project.root / MEDIA / 'root.dmg'
    ssh.upload(root, TARGET + '/root.dmg')
    ssh.run('/bin/sync')
    unmount_container(ssh)
    require(inspect(ssh) == created, 'Container layout changed before invert.')
    require(not container_mounts(ssh.run('/sbin/mount')), 'All disk0s1 volumes must be unmounted before invert.')
    say('Running apfs_invert. All volumes in disk0s1 are unmounted.')
    ssh.run('/System/Library/Filesystems/apfs.fs/apfs_invert -d /dev/disk0s1 -s 8 -n root.dmg', timeout=3600)
    mount_target(ssh)
    final = inspect(ssh)
    require(final['uuid'] == info['uuid'] and set(final['volumes']) == set(range(1, 9)), 'Unexpected APFS layout after invert.')
    version = ssh.target_version()
    require(version.get('ProductVersion') == '16.1' and version.get('ProductBuildVersion') == '20B82', 'Inverted rootfs is not 16.1 / 20B82.')
    record = {'installation_id': uuid.uuid4().hex, 'ecid': project.stage('device')['identity']['ECID'],
              'container_uuid': final['uuid'], 'volume_uuid': final['volumes'][8]['uuid'],
              'root_sha256': media['artifacts']['root']['sha256'], 'volume': VOLUME, 'build': '20B82'}
    require(ssh.run(f'if [ -e {MARKER} ] || [ -L {MARKER} ]; then echo EXISTS; fi').strip() == '', 'Unexpected installation marker in the source rootfs.')
    ssh.script(f"printf '%s\\n' {shlex.quote(json.dumps(record))} > {MARKER}\nchmod 600 {MARKER}\nsync\n")
    project.record('install-rootfs', record)
    say('rootfs installed and mounted on /mnt8.', 'success')
    return record


def verify_target(project, ssh):
    info = verify_ramdisk(project, ssh)
    stage = project.stage('install-rootfs')
    require(info['uuid'] == stage['container_uuid'] and 8 in info['volumes'] and info['volumes'][8]['uuid'] == stage['volume_uuid'],
            'The installed target volume no longer matches the recorded installation.')
    mount_target(ssh)
    require(json.loads(ssh.run('/bin/cat ' + MARKER)) == {key: value for key, value in stage.items() if key != 'at'},
            'Installation marker mismatch; refusing to modify this rootfs.')
    return stage


def cryptex_extract_script(entries, archive, target=TARGET):
    directories = {str(parent) for entry in entries for parent in Path(entry['path']).parents if str(parent) != '.'}
    directories.update(entry['path'] for entry in entries if entry['kind'] == 'dir')
    commands = []
    for relative in sorted(directories, key=lambda name: (len(Path(name).parts), name)):
        path = shlex.quote(target + '/' + relative)
        backup = shlex.quote(target + '/' + relative + '.bak')
        commands.append(f'''if [ -L {path} ]; then
    if [ -e {backup} ] || [ -L {backup} ]; then
        echo {shlex.quote('Cannot preserve Cryptex directory link: backup already exists for ' + relative)} >&2; exit 22
    fi
    echo {shlex.quote('Preserving Cryptex directory link as .bak: ' + relative)}
    mv {path} {backup}
elif [ -e {path} ] && [ ! -d {path} ]; then
    echo {shlex.quote('Cryptex directory is occupied by a file: ' + relative)} >&2; exit 23
fi
mkdir -p {path}
''')
    commands.append('/usr/bin/tar -zxpf ' + shlex.quote(archive) + ' -C ' + shlex.quote(target))
    return '\n'.join(commands) + '\n'


def install_cryptex(project, ssh, media):
    stage = verify_target(project, ssh)
    previous = project.read_state()['stages'].get('install-cryptex', {})
    require(previous.get('installation_id') != stage['installation_id'], 'Both Cryptex archives are already installed for this target.')
    for key in ('system', 'app'):
        item = media['artifacts'][key]
        path = TARGET + '/' + item['filename']
        present = ssh.run(f'if [ -f {shlex.quote(path)} ] && [ ! -L {shlex.quote(path)} ]; then echo PRESENT; fi').strip()
        if present == 'PRESENT':
            say(f'Using the already uploaded archive: {path}')
        else:
            ssh.upload(project.root / MEDIA / item['filename'], path)
        say(f'Extracting {key} Cryptex files into /mnt8.')
        ssh.script(cryptex_extract_script(item['entries'], path), timeout=1800,
                   label=f'ssh: prepare Cryptex directories; tar -zxpf {path} -C /mnt8', live=True)
        ssh.run('/bin/rm ' + shlex.quote(path))
    ssh.script('/usr/sbin/chown -R -h root:wheel /mnt8/System /mnt8/usr\nsync\n', timeout=600)
    project.record('install-cryptex', {'installation_id': stage['installation_id'],
                                     'archives': {key: media['artifacts'][key]['sha256'] for key in ('system', 'app')}})
    say('Both Cryptex archives extracted; System and usr ownership repaired.', 'success')


def install_preboot(project, ssh):
    stage = verify_target(project, ssh)
    require(project.stage('install-cryptex')['installation_id'] == stage['installation_id'], 'Install both Cryptex archives before preparing Preboot.')
    capture = project.stage('capture')
    boot_hash = capture['preboot_hash']
    require(re.fullmatch(r'[0-9A-Fa-f]{96}', boot_hash) is not None, 'Invalid captured device boot hash.')
    rows = mounts(ssh.run('/sbin/mount'))
    require(not any(path == '/mnt6' and device != '/dev/disk1s6' for device, path in rows), '/mnt6 is occupied by another filesystem.')
    if ('/dev/disk1s6', '/mnt6') not in rows:
        require(not any(device == '/dev/disk1s6' for device, _ in rows), 'Preboot is already mounted elsewhere.')
        ssh.script('[ ! -L /mnt6 ]\nmkdir -p /mnt6\n/sbin/mount_apfs /dev/disk1s6 /mnt6\n')
    firmware = '/mnt6/' + boot_hash + '/usr/standalone/firmware'
    # Reuse the actual ticket-derived firmware directory; do not invent a hash
    # or replace the stock firmware directory with an empty substitute.
    present = ssh.run(f'if [ -d {firmware} ] && [ -f {firmware}/sep-firmware.img4 ]; then echo FOUND; fi').strip()
    require(present == 'FOUND', 'The ticket-matched stock firmware directory is missing from Preboot. Restore it before continuing; no empty replacement was created.')
    script = ''
    # Use subdirectories rather than linking all of /System: the latter would
    # recurse through /System/Cryptexes back into the same compatibility tree.
    paths = ('System/Library', 'System/DriverKit', 'usr/lib', 'usr/libexec', 'usr/bin', 'usr/sbin', 'usr/share')
    preflight = ''
    for kind in ('OS', 'App'):
        base = '/mnt6/Cryptexes/' + kind
        for parent in ('/mnt6/Cryptexes', base, base + '/System', base + '/usr'):
            preflight += f'[ ! -L {parent} ]\n'
            script += f'[ ! -L {parent} ]\nmkdir -p {parent}\n'
        for name in paths:
            dest, target = base + '/' + name, '/' + name
            preflight += f'''[ -d /mnt8/{name} ]
if [ -e {dest} ] && [ ! -L {dest} ]; then
    echo 'Conflicting Preboot Cryptex directory: {dest}' >&2; exit 21
fi
'''
            script += f'''if [ -e {dest} ] && [ ! -L {dest} ]; then
    echo 'Conflicting Preboot Cryptex directory: {dest}' >&2; exit 21
fi
ln -sfn {target} {dest}
'''
    # Preflight all conflicts before creating links.
    ssh.script(preflight)
    ssh.script(script + 'sync\n')
    project.record('install-preboot', {'installation_id': stage['installation_id'], 'preboot_hash': boot_hash})
    say('Preboot Cryptex compatibility paths prepared; stock firmware files retained.', 'success')


def kernelcache_backup_script(paths):
    """Preflight every stock copy before renaming any; never overwrite .bak."""
    script = 'found=0\n'
    for path in paths:
        original, backup = shlex.quote(path), shlex.quote(path + '.bak')
        for parent in reversed(Path(path).parents):
            script += f'[ ! -L {shlex.quote(str(parent))} ]\n'
        script += f'''if [ -L {original} ] || [ -L {backup} ]; then
    echo 'Refusing a symbolic stock kernelcache or backup.' >&2; exit 24
fi
if [ -e {original} ]; then
    [ -f {original} ] || {{ echo 'Stock kernelcache is not a regular file.' >&2; exit 24; }}
    if [ -e {backup} ]; then
        echo 'Stock kernelcache.bak already exists beside an active kernelcache; refusing to overwrite.' >&2; exit 24
    fi
    found=1
elif [ -e {backup} ]; then
    [ -f {backup} ] || {{ echo 'Stock kernelcache.bak is not a regular file.' >&2; exit 24; }}
    found=1
fi
'''
    script += '[ "$found" = 1 ] || { echo "No stock kernelcache or kernelcache.bak found in the supported System/Preboot paths." >&2; exit 25; }\n'
    for path in paths:
        original, backup = shlex.quote(path), shlex.quote(path + '.bak')
        script += f'''if [ -f {original} ]; then
    mv {original} {backup}
    printf 'RENAMED\\t%s\\n' {original}
elif [ -f {backup} ]; then
    printf 'ALREADY_BACKED_UP\\t%s\\n' {original}
fi
'''
    return script + 'sync\n'


def finalize_install(project, ssh):
    """Disable stock boot only after all deployment phases and boot preparation."""
    from .sshrd import check_images
    ready = check_images(Path(project.stage('build-ios16')['folder']))
    require(ready['stage'] == 'ios16' and ready['ecid'] == project.stage('device')['identity']['ECID'],
            'Build the full-iOS boot bundle for this phone before finalizing.')
    stage = verify_target(project, ssh)
    for name in ('install-cryptex', 'install-patches', 'install-preboot'):
        require(project.stage(name)['installation_id'] == stage['installation_id'],
                f'Complete {name} for the current installation before finalizing.')
    boot_hash = project.stage('install-preboot')['preboot_hash']
    require(re.fullmatch(r'[0-9A-Fa-f]{96}', boot_hash) is not None, 'Invalid Preboot hash.')
    rows = mounts(ssh.run('/sbin/mount'))
    # Preboot was mounted by its own step; never invoke mount_filesystems or
    # mount Data. A user who unmounted Preboot can rerun install preboot.
    require(('/dev/disk1s6', '/mnt6') in rows, 'Mount Preboot with install preboot before finalizing.')
    stock = [(device, path) for device, path in rows
             if device in ('/dev/disk1s1', '/dev/disk0s1s1')]
    require(not any(path == '/mnt1' and device not in ('/dev/disk1s1', '/dev/disk0s1s1')
                    for device, path in rows), '/mnt1 is occupied by another filesystem.')
    require(not stock or len(stock) == 1 and stock[0][1] == '/mnt1', 'Stock System is mounted elsewhere; refusing to guess a path.')
    mounted_here = not stock
    if mounted_here:
        ssh.script('[ ! -L /mnt1 ]\nmkdir -p /mnt1\n/sbin/mount_apfs -o rw /dev/disk1s1 /mnt1\n')
    paths = ['/mnt1/System/Library/Caches/com.apple.kernelcaches/kernelcache',
             '/mnt6/' + boot_hash + '/System/Library/Caches/com.apple.kernelcaches/kernelcache']
    say('Preserving stock iOS15 kernelcache copies as kernelcache.bak. Stock iOS15 must not boot after shared Data migration.', 'warning')
    try:
        output = ssh.script(kernelcache_backup_script(paths), label='ssh: rename stock iOS15 kernelcache to kernelcache.bak')
        changed = [line.split('\t', 1)[1] for line in output.splitlines()
                   if line.startswith(('RENAMED\t', 'ALREADY_BACKED_UP\t'))]
        require(changed and all(path in paths for path in changed), 'No stock kernelcache backup was reported.')
        project.record('install-finalize', {'installation_id': stage['installation_id'],
                                          'kernel_backups': [{'original': path, 'backup': path + '.bak'} for path in changed]})
    finally:
        if mounted_here:
            ssh.run('/sbin/umount /mnt1')
    say('Installation finalized. Original stock kernelcache files are retained as .bak.', 'success')
