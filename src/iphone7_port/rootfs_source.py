"""Reconstruct the working rootfs fixes from firmware and captured stock files."""

import base64
import binascii
import bz2
import json
import shutil
import tarfile
import tempfile
from collections import defaultdict
from pathlib import Path, PurePosixPath

from .assets import asset
from .console import say
from .core import PortError, digest_file, load_json, publish_directory, require
from .firmware import resource
from .rootfs_patches import import_patches, verify_patches
from .sshrd import attached
from .stock_resources import stock_folder

IMAGES = {
    'ipad_target-root': ('ipad_target', 'OS'),
    'ipad_target-system': ('ipad_target', 'Cryptex1,SystemOS'),
    'iphone8_donor-root': ('iphone8_donor', 'OS'),
}


def relative_path(value):
    path = PurePosixPath(value)
    require(bool(value) and not path.is_absolute() and '..' not in path.parts and str(path) == value,
            f'Invalid rootfs recipe path: {value}')
    return path


def checked_file(root, relative, size, sha256):
    relative_path(relative)
    path = root / relative
    require(path.is_file() and path.resolve().is_relative_to(root.resolve()), f'Missing source file: {relative}')
    require(path.stat().st_size == size and digest_file(path, ('sha256',))['sha256'] == sha256,
            f'Source file does not match the pinned recipe: {relative}')
    return path


def recipes(project):
    data = load_json(project.root / 'profiles/rootfs-recipes.json')
    lock = load_json(project.root / 'profiles/rootfs-reference.json')
    require(data.get('schema') == 1 and data.get('build') == '20B82' and data.get('stock_build') == '19H422',
            'Unexpected rootfs recipe version.')
    expected = {row['path']: row for row in lock['files']}
    require(len(data['files']) == len(expected) == len({row['path'] for row in data['files']}), 'Duplicate or missing rootfs recipes.')
    for row in data['files']:
        relative_path(row['path'])
        require(row['path'] in expected and all(row[key] == expected[row['path']][key] for key in ('size', 'mode', 'sha256')),
                f'Rootfs recipe differs from the working reference: {row["path"]}')
        require(row['method'] in ('copy', 'delta', 'project'), 'Unsupported rootfs recipe method.')
        if row['method'] == 'project':
            relative_path(row['resource'])
            require(row['resource'].startswith('resources/rootfs/files/'), 'Invalid project resource location.')
        else:
            require(row['origin'] in {*IMAGES, 'stock-d10', 'ssh-archive'}, 'Unsupported firmware origin.')
            relative_path(row['relative'])
        if row['method'] == 'delta':
            relative_path(row['delta'])
            require(row['delta'].startswith('resources/rootfs/deltas/'), 'Invalid delta location.')
    return data['files']


def delta_writes(data, row):
    require(data.get('schema') == 1 and all(data.get(key) == row[key] for key in ('source_sha256', 'source_size'))
            and data.get('target_sha256') == row['sha256'] and data.get('target_size') == row['size'],
            'Delta metadata does not match its recipe.')
    end = 0
    writes = []
    for item in data['writes']:
        require(isinstance(item, list) and len(item) == 2 and type(item[0]) is int, 'Invalid delta write.')
        offset, encoded = item
        try:
            value = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError, binascii.Error) as exc:
            raise PortError('Invalid delta byte encoding.') from exc
        require(bool(value) and offset >= end and offset + len(value) <= row['size'], 'Overlapping or out-of-bounds delta write.')
        writes.append((offset, value))
        end = offset + len(value)
    return writes


def apply_delta(project, source, target, row):
    delta = project.root / row['delta']
    require(delta.is_file() and delta.resolve().is_relative_to(project.root.resolve())
            and digest_file(delta, ('sha256',))['sha256'] == row['delta_sha256'], 'Rootfs delta changed.')
    data = json.loads(bz2.decompress(delta.read_bytes()))
    writes = delta_writes(data, row)
    shutil.copyfile(source, target)
    with target.open('r+b') as stream:
        stream.truncate(row['size'])
        for offset, value in writes:
            stream.seek(offset)
            stream.write(value)


def cache_sources(project, rows, cache):
    grouped = defaultdict(dict)
    for row in rows:
        if row['method'] != 'project':
            previous = grouped[row['origin']].setdefault(row['relative'], row)
            require(all(previous[key] == row[key] for key in ('source_size', 'source_sha256')), 'Conflicting source recipes.')
    stock = stock_folder(project) if 'stock-d10' in grouped else None
    for origin, items in grouped.items():
        missing = []
        for relative, row in items.items():
            try:
                checked_file(cache / origin, relative, row['source_size'], row['source_sha256'])
            except PortError:
                missing.append(row)
        if not missing:
            continue
        say(f'Preparing {len(missing)} original files from {origin}.')

        def copy_from(root):
            for row in missing:
                source = checked_file(root, row['relative'], row['source_size'], row['source_sha256'])
                target = cache / origin / row['relative']
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)

        if origin in IMAGES:
            role, name = IMAGES[origin]
            with attached(project, resource(project, role, name), project.work / 'rootfs-source' / ('mount-' + origin), readonly=True) as mount:
                copy_from(mount)
        elif origin == 'stock-d10':
            copy_from(stock)
        else:
            wanted = {row['relative']: row for row in missing}
            with tarfile.open(asset(project, 'ssh.tar.gz'), 'r:gz') as archive:
                for member in archive:
                    name = member.name.removeprefix('./')
                    if name not in wanted:
                        continue
                    row = wanted.pop(name)
                    require(member.isfile(), f'SSH resource is not an ordinary file: {name}')
                    target = cache / origin / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.extractfile(member) as source, target.open('wb') as output:
                        shutil.copyfileobj(source, output)
                    checked_file(cache / origin, name, row['source_size'], row['source_sha256'])
            require(not wanted, 'The bundled SSH archive is missing required files.')


def reconstruct(project):
    rows = recipes(project)
    base = project.work / 'rootfs-source'
    base.mkdir(parents=True, exist_ok=True)
    cache_sources(project, rows, base / 'inputs')
    tree = base / 'tree'
    if tree.exists():
        for row in rows:
            checked_file(tree, row['path'], row['size'], row['sha256'])
        return tree
    staging = Path(tempfile.mkdtemp(prefix='.tree-', dir=base))
    try:
        for row in rows:
            target = staging / row['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            if row['method'] == 'project':
                source = checked_file(project.root, row['resource'], row['size'], row['sha256'])
                shutil.copyfile(source, target)
            else:
                source = checked_file(base / 'inputs' / row['origin'], row['relative'], row['source_size'], row['source_sha256'])
                if row['method'] == 'delta':
                    apply_delta(project, source, target, row)
                else:
                    shutil.copyfile(source, target)
            target.chmod(row['mode'])
            checked_file(staging, row['path'], row['size'], row['sha256'])
        publish_directory(staging, tree)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    say(f'Reconstructed all {len(rows)} rootfs files; every result matches the working reference.', 'success')
    return tree


def prepare_patches(project):
    if (project.work / 'install-patches/patches.json').is_file():
        result = verify_patches(project)
        say('Prepared rootfs patches are already current.', 'success')
        return result
    return import_patches(project, reconstruct(project))
