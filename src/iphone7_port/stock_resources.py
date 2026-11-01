"""Collect only fixed D10 hardware resources from the mounted stock System."""

import shutil
import tempfile
import shlex
from pathlib import Path, PurePosixPath

from .console import say
from .core import digest_file, load_json, publish_directory, require


def spec(project):
    data = load_json(project.root / 'profiles/stock-resources.json')
    require(data.get('schema') == 1 and data.get('build') == '19H422', 'Unexpected stock-resource profile.')
    for row in data['files']:
        path = PurePosixPath(row['path'])
        require(not path.is_absolute() and '..' not in path.parts, 'Invalid stock-resource path.')
    return data


def verify_stock(project, folder):
    data = spec(project)
    for row in data['files']:
        path = folder / row['path']
        require(path.is_file() and path.resolve().is_relative_to(folder.resolve()),
                f'Missing original D10 resource: {row["path"]}. Run capture in the 15.6 SSHRD.')
        require(path.stat().st_size == row['size'] and digest_file(path, ('sha256',))['sha256'] == row['sha256'],
                f'Original D10 resource differs from stock 15.8.8: {row["path"]}')
    return data


def stock_folder(project):
    require('stock-rootfs-resources' in project.read_state()['stages'],
            'Original D10 resources have not been collected. Run ./run.sh capture in the 15.6 SSHRD first.')
    stage = project.stage('stock-rootfs-resources')
    folder = project.root / stage['folder']
    require(folder.resolve().is_relative_to(project.work.resolve()), 'Stock-resource cache must remain inside this project.')
    identity = project.read_state()['stages'].get('device', {}).get('identity')
    if identity:
        require(stage.get('ecid') == identity['ECID'], 'Stock resources were captured for a different device.')
    require(stage.get('build') == '19H422', 'Stock resources are not from the supported 15.8.8 baseline.')
    verify_stock(project, folder)
    return folder


def capture_stock(project, ssh):
    identity = project.stage('device')['identity']
    folder = project.work / 'devices' / identity['ECID'] / 'stock-resources'
    if folder.exists():
        verify_stock(project, folder)
    else:
        folder.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix='.stock-resources-', dir=folder.parent))
        try:
            data = spec(project)
            say('Collecting original D10 audio, touch, camera and wireless resources from /mnt1.')
            for relative in data['capture_directories']:
                target = staging / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                ssh.transfer('root@127.0.0.1:' + shlex.quote('/mnt1/' + relative), target.parent, recursive=True)
            for relative in data['capture_files']:
                target = staging / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                ssh.transfer('root@127.0.0.1:' + shlex.quote('/mnt1/' + relative), target)
            verify_stock(project, staging)
            publish_directory(staging, folder)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    project.record('stock-rootfs-resources', {'folder': str(folder.relative_to(project.root)),
                                            'ecid': identity['ECID'], 'build': '19H422',
                                            'file_count': len(spec(project)['files'])})
    say('Original D10 hardware resources collected for standalone patch preparation.', 'success')
    return folder
