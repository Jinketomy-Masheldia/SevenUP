"""Prepare an APFS container and portable Cryptex archives on the Mac."""

import os
import plistlib
import shutil
import struct
import tarfile
from pathlib import Path, PurePosixPath

from .console import say
from .core import Project, digest_file, load_json, require, save_json
from .firmware import resource
from .sshrd import attached

MEDIA = 'work/install-media'


def apfs_size(path):
    with Path(path).open('rb') as stream:
        header = stream.read(4096)
    require(len(header) == 4096 and header[32:36] == b'NXSB',
            'root.dmg must begin with a raw APFS container, not UDIF, GPT, or an individual APFS volume.')
    block, count = struct.unpack_from('<IQ', header, 36)
    require(block == 4096 and count > 0, 'Unsupported APFS container geometry.')
    require(Path(path).stat().st_size == block * count, 'Raw APFS container length does not match its superblock.')
    return block * count


def archive_entries(path):
    """Validate names and extraction topology without extracting on the host."""
    entries, names, links = [], set(), set()
    with tarfile.open(path, 'r:gz') as archive:
        for member in archive:
            name = str(PurePosixPath(member.name))
            if name == '.' and member.isdir():
                continue
            parts = PurePosixPath(name).parts
            require(parts and not member.name.startswith('/') and '..' not in parts and '\\' not in name,
                    f'Unsafe archive path: {member.name!r}')
            require(not any(ord(char) < 32 for char in name) and name not in names,
                    f'Duplicate or invalid archive member: {name!r}')
            require(member.isfile() or member.isdir() or member.issym(), f'Unsupported archive member: {name}')
            require(parts[0] in {'System', 'usr', 'Library', 'Applications', 'bin', 'sbin', 'private'},
                    f'Unexpected archive root: {name}')
            if member.issym():
                require(member.linkname and not member.linkname.startswith('/') and
                        not any(ord(char) < 32 for char in member.linkname), f'Unsafe symlink: {name}')
                normalized = os.path.normpath(str(PurePosixPath(name).parent / member.linkname))
                require(normalized != '..' and not normalized.startswith('../'), f'Symlink escapes archive: {name}')
                links.add(name)
            names.add(name)
            entries.append({'path': name, 'size': member.size, 'kind': 'link' if member.issym() else 'dir' if member.isdir() else 'file',
                            'mode': member.mode & 0o7777, **({'target': member.linkname} if member.issym() else {})})
    require(entries, f'Empty archive: {path}')
    for entry in entries:
        require(not any(str(parent) in links for parent in PurePosixPath(entry['path']).parents),
                f'Archive member traverses a symlink: {entry["path"]}')
    return entries


def raw_container(project: Project, source: Path, target: Path):
    with source.open('rb') as stream:
        is_raw = stream.read(36)[32:36] == b'NXSB'
    if is_raw:
        shutil.copyfile(source, target)
    else:
        result = project.run(['hdiutil', 'imageinfo', '-plist', source], timeout=180)
        info = plistlib.loads(result.stdout.encode())
        layout = info['partitions']
        candidates = [item for item in layout['partitions'] if item.get('partition-hint') == 'Apple_APFS']
        require(len(candidates) == 1, 'Expected one APFS container partition in the OS image.')
        block = layout['block-size']
        offset = candidates[0]['partition-start'] * block
        size = candidates[0]['partition-length'] * block
        require(block == 512 and offset >= 0 and size > 0, 'Unsupported image partition geometry.')
        require(shutil.disk_usage(project.root).free >= size * 2 + 2 * 1024**3,
                'Insufficient host space for the temporary UDRW image, raw container, and Cryptex archives.')
        # Convert to an ordinary file, then copy ONLY its APFS partition. This
        # avoids privileged /dev/rdisk reads and excludes GPT/MBR from root.dmg.
        temporary = target.parent / 'root-outer.udrw.dmg'
        require(not temporary.exists(), 'Temporary UDRW image already exists.')
        try:
            project.run(['hdiutil', 'convert', source, '-format', 'UDRW', '-o', temporary], timeout=1800)
            require(temporary.stat().st_size >= offset + size, 'Converted outer disk image is truncated.')
            say('Extracting the raw APFS container partition to root.dmg.')
            with temporary.open('rb') as src, target.open('xb') as dst:
                src.seek(offset)
                remaining = size
                while remaining:
                    chunk = src.read(min(8 * 1024**2, remaining))
                    require(chunk, 'Unexpected end of converted disk image.')
                    dst.write(chunk)
                    remaining -= len(chunk)
        finally:
            temporary.unlink(missing_ok=True)
    target.chmod(0o600)
    apfs_size(target)


def prepare_install(project: Project):
    project.initialize()
    folder = project.root / MEDIA
    receipt = folder / 'media.json'
    if receipt.exists():
        record = verify_media(project)
        say('Using verified install media. No device action was performed.', 'success')
        return record
    require(not folder.exists(), f'Incomplete preparation at {folder}. Move it aside or run clean before preparing again.')
    # Verify all source components before creating output.
    sources = {name: resource(project, 'ipad_target', component) for name, component in (
        ('root', 'OS'), ('system', 'Cryptex1,SystemOS'), ('app', 'Cryptex1,AppOS'))}
    require(shutil.disk_usage(project.root).free >= 8 * 1024**3, 'At least 8 GiB of free host space is required to prepare install media.')
    folder.mkdir(mode=0o700)
    artifacts = {}
    try:
        target = folder / 'root.dmg'
        raw_container(project, sources['root'], target)
        artifacts['root'] = {'filename': target.name, 'size': target.stat().st_size,
                             **digest_file(target, ('sha256',))}
        env = os.environ.copy()
        env['COPYFILE_DISABLE'] = '1'
        for name in ('system', 'app'):
            target = folder / f'cryptex-{name}.tar.gz'
            with attached(project, sources[name], folder / f'mount-{name}', readonly=True) as mount:
                require((mount / 'System').is_dir() or (mount / 'usr').is_dir(), 'Unexpected Cryptex image layout.')
                roots = sorted(item.name for item in mount.iterdir() if item.name in {'System', 'usr', 'Library', 'Applications'})
                project.run([project.tool('gtar'), '--format=posix', '--no-xattrs', '--no-acls',
                             '--hard-dereference',
                             '--owner=0', '--group=0', '--numeric-owner', '-czf', target,
                             '-C', mount, *roots], timeout=1800, env=env)
            entries = archive_entries(target)
            target.chmod(0o600)
            artifacts[name] = {'filename': target.name, 'size': target.stat().st_size,
                               **digest_file(target, ('sha256',)), 'entries': entries}
        record = {'schema': 1, 'version': '16.1', 'build': '20B82', 'role': 'ipad_target',
                  'sources': {key: digest_file(value, ('sha256',))['sha256'] for key, value in sources.items()},
                  'artifacts': artifacts}
        save_json(receipt, record)
        project.record('install-media', {'folder': str(folder), 'build': '20B82'})
        say('Raw root.dmg and both Cryptex archives are ready. No phone action was performed.', 'success')
        return record
    except BaseException:
        say('Preparation stopped. Incomplete files are retained for diagnosis; no complete receipt was published.', 'warning')
        raise


def read_media_receipt(project: Project):
    folder = project.root / MEDIA
    require((folder / 'media.json').is_file(), "Run './run.sh prepare-install' first.")
    record = load_json(folder / 'media.json')
    require(record.get('schema') == 1 and record.get('build') == '20B82' and record.get('role') == 'ipad_target',
            'Wrong installation media profile.')
    require(record['artifacts']['root']['filename'] == 'root.dmg' and (folder / 'root.dmg').is_file(),
            'root.dmg is missing. Run prepare-install first.')
    return record


def verify_media(project: Project):
    folder = project.root / MEDIA
    record = read_media_receipt(project)
    for key, filename in [('root', 'root.dmg'), ('system', 'cryptex-system.tar.gz'), ('app', 'cryptex-app.tar.gz')]:
        item = record['artifacts'][key]
        path = folder / filename
        require(item['filename'] == filename and path.is_file() and path.stat().st_size == item['size'],
                f'Missing or truncated install artifact: {filename}')
        require(digest_file(path, ('sha256',))['sha256'] == item['sha256'], f'Install artifact changed: {filename}')
        if key != 'root':
            require(archive_entries(path) == item['entries'], f'Cryptex archive manifest changed: {filename}')
    apfs_size(folder / 'root.dmg')
    return record
