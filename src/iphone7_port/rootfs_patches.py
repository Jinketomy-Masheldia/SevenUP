"""Hash-pinned rootfs payload packaging and backup-preserving install."""

import hashlib
import plistlib
import shlex
import shutil
import tarfile
from pathlib import Path, PurePosixPath

from .console import say
from .core import Project, digest_file, load_json, require, save_json
from .install import TARGET, verify_target
from .install_media import archive_entries
from .signing import verify_detached

PATCHES = 'work/install-patches'
CACHE = 'System/Library/xpc/launchd.plist'


def import_patches(project: Project, source_tree: Path):
    """Package the reconstructed tree after verifying the working file hashes."""
    lock = load_json(project.root / 'profiles/rootfs-reference.json')
    root = source_tree.expanduser().resolve()
    require(lock.get('schema') == 1 and lock.get('build') == '20B82', 'Invalid rootfs reference profile.')
    folder = project.root / PATCHES
    require(not folder.exists(), 'Rootfs patches are already staged. Preserve or explicitly move them aside before importing again.')
    # Check every source before staging any output.
    for record in lock['files']:
        source = root / record['source']
        require(source.is_file() and source.resolve().is_relative_to(root), f'Missing reference source: {record["source"]}')
        require(digest_file(source, ('sha256',))['sha256'] == record['sha256'], f'Reference artifact changed: {record["source"]}')
    folder.mkdir(parents=True, mode=0o700)
    variants = {}
    for ssh in (False, True):
        name = 'with-ssh' if ssh else 'without-ssh'
        stage = folder / name
        stage.mkdir()
        records = []
        for record in lock['files']:
            if record.get('ssh_only') and not ssh:
                continue
            target = stage / record['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / record['source'], target)
            target.chmod(record['mode'])
            records.append({key: record[key] for key in ('path', 'mode', 'sha256', 'size', 'component')})
        # Rebuild only the no-SSH cache. The SSH variant retains the exact final
        # known-working CM1 cache and its matching detached signature.
        if not ssh:
            cache = stage / CACHE
            parsed = plistlib.loads(cache.read_bytes())
            removed = [key for key in parsed['LaunchDaemons'] if key.startswith('/System/Library/LaunchDaemons/com.jmx.ios16.ssh')]
            require(len(removed) == 3, 'Expected the three known SSH2 services in the reference cache.')
            for key in removed:
                parsed['LaunchDaemons'].pop(key)
            cache.write_bytes(plistlib.dumps(parsed, fmt=plistlib.FMT_BINARY, sort_keys=False))
            signature = stage / (CACHE + '.sig')
            signature.unlink()
            project.run(['/usr/bin/codesign', '--force', '--sign', '-', '--identifier',
                         'org.iphone7-ios16.launchdcache', '--pagesize', '4096', '--detached', signature, cache])
            for record in records:
                if record['path'] in (CACHE, CACHE + '.sig'):
                    path = stage / record['path']
                    record.update(size=path.stat().st_size, **digest_file(path, ('sha256',)))
        cache_data = (stage / CACHE).read_bytes()
        cache = plistlib.loads(cache_data)
        jobs = cache['LaunchDaemons']
        require(len(jobs) == (506 if ssh else 503), 'Unexpected final launchd service count.')
        for row in records:
            if row['path'].startswith('System/Library/LaunchDaemons/'):
                require(jobs['/' + row['path']] == plistlib.loads((stage / row['path']).read_bytes()),
                        f'On-disk job differs from the final launchd cache: {row["path"]}')
        signature = verify_detached((stage / (CACHE + '.sig')).read_bytes(), cache_data)
        archive_path = folder / (name + '.tar.gz')
        # Only ordinary files go in this archive. A2 is a separately checked
        # symlink operation, so archive extraction cannot follow it accidentally.
        with tarfile.open(archive_path, 'w:gz', format=tarfile.PAX_FORMAT) as archive:
            for record in records:
                path = stage / record['path']
                member = tarfile.TarInfo(record['path'])
                member.size, member.mode = path.stat().st_size, record['mode']
                member.uid = member.gid = 0
                member.uname, member.gname = 'root', 'wheel'
                with path.open('rb') as stream:
                    archive.addfile(member, stream)
        archive_entries(archive_path)
        variants[name] = {'filename': archive_path.name, 'files': records, 'launchd_signature': signature,
                          **digest_file(archive_path, ('sha256',)), 'size': archive_path.stat().st_size}
        shutil.rmtree(stage)
    record = {'schema': 1, 'build': '20B82', 'kind': 'firmware-derived',
              'source_lock_sha256': digest_file(project.root / 'profiles/rootfs-reference.json', ('sha256',))['sha256'],
              'variants': variants,
              'components': lock['components'], 'links': [{'path': 'usr/sbin/fairplayd.A2', 'target': 'fairplayd.H2'}]}
    save_json(folder / 'patches.json', record)
    say('Both rootfs patch variants prepared. Generated Apple payloads remain under ignored work/.', 'success')
    return record


def verify_patches(project):
    folder = project.root / PATCHES
    require((folder / 'patches.json').is_file(), 'Rootfs patches are not prepared. Run ./run.sh prepare-rootfs-patches first.')
    record = load_json(folder / 'patches.json')
    require(record.get('schema') == 1 and record.get('build') == '20B82', 'Unexpected rootfs patch profile.')
    require(record.get('source_lock_sha256') == digest_file(project.root / 'profiles/rootfs-reference.json', ('sha256',))['sha256'],
            'Staged patches belong to another rootfs reference profile.')
    for name in ('with-ssh', 'without-ssh'):
        item = record['variants'][name]
        require(item['filename'] == name + '.tar.gz', 'Unexpected patch archive path.')
        archive = folder / item['filename']
        require(archive.stat().st_size == item['size'] and digest_file(archive, ('sha256',))['sha256'] == item['sha256'], 'Rootfs patch archive changed.')
        entries = archive_entries(archive)
        require({entry['path'] for entry in entries} == {entry['path'] for entry in item['files']}, 'Patch archive members differ from the manifest.')
        by_path = {row['path']: row for row in item['files']}
        small = {}
        with tarfile.open(archive, 'r|gz') as stream:
            for member in stream:
                row = by_path[member.name]
                require(member.isfile() and member.mode == row['mode'] and member.size == row['size'], 'Patch file metadata differs from its manifest.')
                source = stream.extractfile(member)
                require(source is not None, 'Missing patch file.')
                hasher = hashlib.sha256()
                keep = member.name in (CACHE, CACHE + '.sig') or member.name.startswith('System/Library/LaunchDaemons/')
                content = []
                require(not keep or member.size <= 2 * 1024**2, 'Unexpected launchd metadata size.')
                with source:
                    while chunk := source.read(8 * 1024**2):
                        hasher.update(chunk)
                        if keep:
                            content.append(chunk)
                require(hasher.hexdigest() == row['sha256'], 'A patch file differs from its manifest.')
                if keep:
                    small[member.name] = b''.join(content)
        verify_detached(small[CACHE + '.sig'], small[CACHE])
        jobs = plistlib.loads(small[CACHE])['LaunchDaemons']
        require(len(jobs) == (506 if name == 'with-ssh' else 503), 'Unexpected final launchd service count.')
        for path, data in small.items():
            if path.startswith('System/Library/LaunchDaemons/'):
                require(jobs['/' + path] == plistlib.loads(data), 'A staged launchd job differs from its signed cache.')
    return record


def patch_script(record, variant, staging):
    rows = record['variants'][variant]['files']
    checks, actions = [], []
    for row in rows:
        relative = row['path']
        require(not PurePosixPath(relative).is_absolute() and '..' not in PurePosixPath(relative).parts, 'Unsafe patch destination.')
        source = staging + '/' + relative
        target = TARGET + '/' + relative
        # Extra .bak files inside a signed DriverKit bundle invalidate its
        # resource seal. Retain these originals outside the bundle instead.
        backup = (TARGET + '/usr/local/share/iphone7-ios16-backups/' + relative + '.bak'
                  if relative.startswith('System/Library/DriverExtensions/') else target + '.bak')
        parents = [str(parent) for parent in PurePosixPath(target).parents if str(parent).startswith(TARGET)]
        for parent in parents + [str(parent) for parent in PurePosixPath(backup).parents if str(parent).startswith(TARGET)]:
            checks.append('[ ! -L ' + shlex.quote(parent) + ' ]')
        checks += [f'[ ! -e {shlex.quote(backup)} ] && [ ! -L {shlex.quote(backup)} ]',
                   f'[ ! -d {shlex.quote(target)} ]']
        actions += [f'mkdir -p {shlex.quote(str(PurePosixPath(target).parent))}',
                    f'mkdir -p {shlex.quote(str(PurePosixPath(backup).parent))}',
                    f'if [ -e {shlex.quote(target)} ] || [ -L {shlex.quote(target)} ]; then mv {shlex.quote(target)} {shlex.quote(backup)}; fi',
                    f'cp {shlex.quote(source)} {shlex.quote(target)}',
                    f'chown -h 0:0 {shlex.quote(target)}', f'chmod {row["mode"]:o} {shlex.quote(target)}']
    a2 = TARGET + '/usr/sbin/fairplayd.A2'
    checks += [f'[ ! -L {TARGET}/usr/sbin ]', f'[ ! -e {a2}.bak ] && [ ! -L {a2}.bak ]', f'[ ! -d {a2} ]']
    actions += [f'if [ -e {a2} ] || [ -L {a2} ]; then mv {a2} {a2}.bak; fi',
                f'ln -s fairplayd.H2 {a2}', f'chown -h 0:0 {a2}']
    if variant == 'with-ssh':
        keys = TARGET + '/usr/local/etc/ssh1'
        checks += [f'[ ! -L {TARGET}/usr/local/etc ]', f'[ ! -L {keys} ]',
                   f'[ ! -e {keys}/dropbear_ecdsa_host_key ] && [ ! -L {keys}/dropbear_ecdsa_host_key ]',
                   '[ -x /usr/local/bin/dropbearkey ]']
        actions += [f'mkdir -p {keys}', f'/usr/local/bin/dropbearkey -t ecdsa -f {keys}/dropbear_ecdsa_host_key >/dev/null',
                    f'chown 0:0 {keys}/dropbear_ecdsa_host_key', f'chmod 600 {keys}/dropbear_ecdsa_host_key']
    return '\n'.join(checks + actions + ['sync', 'echo ROOTFS_PATCHES_INSTALLED']) + '\n'


def install_patches(project, ssh, record, with_ssh=True):
    stage = verify_target(project, ssh)
    require(project.stage('install-cryptex')['installation_id'] == stage['installation_id'], 'Install Cryptex files before rootfs patches.')
    require(project.read_state()['stages'].get('install-patches', {}).get('installation_id') != stage['installation_id'], 'Rootfs patches are already installed for this target.')
    variant = 'with-ssh' if with_ssh else 'without-ssh'
    item = record['variants'][variant]
    base = TARGET + '/.iphone7-ios16-patches'
    remote_archive = base + '/payload.tar.gz'
    ssh.script(f'[ ! -e {base} ] && [ ! -L {base} ]\nmkdir -m 700 {base}\n')
    ssh.upload(project.root / PATCHES / item['filename'], remote_archive)
    ssh.script(f'mkdir {base}/payload\ntar -zxpf {remote_archive} -C {base}/payload\n', timeout=1200)
    ssh.script(patch_script(record, variant, base + '/payload'), timeout=1800,
               label=f'ssh: install {len(item["files"])} rootfs patch files; preserve .bak; set ownership and modes', live=True)
    ssh.script(f'rm -r {base}\nsync\n')
    project.record('install-patches', {'installation_id': stage['installation_id'], 'ssh': with_ssh,
                                      'archive_sha256': item['sha256'], 'components': record['components']})
    say('Rootfs patches installed. Original files retained as .bak; SSH host key generated on-device only.' if with_ssh
        else 'Rootfs patches installed without SSH. Original files retained as .bak.', 'success')
