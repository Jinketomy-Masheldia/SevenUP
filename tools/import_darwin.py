#!/usr/bin/env python3
"""Import a local macOS tool set and a relocatable linker into this project.

This host-only development utility never queries or operates an iPhone.
This maintenance tool does not replace release licensing/source review.
"""

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

TOOLS = ['img4', 'img4tool', 'irecovery', 'gaster', 'iBoot64Patcher', 'KPlooshFinder',
         'Kernel64Patcher3', 'kerneldiff', 'gtar', 'iproxy', 'sshpass', 'pzb']


def run(*args):
    return subprocess.check_output([str(a) for a in args], text=True, stderr=subprocess.STDOUT)


def dependencies(path):
    return [line.strip().split(' (compatibility', 1)[0] for line in run('otool', '-L', path).splitlines()
            if line.startswith(('\t', ' ')) and ' (compatibility' in line]


def rpaths(path):
    result, wanted = [], False
    for line in run('otool', '-l', path).splitlines():
        if line.strip() == 'cmd LC_RPATH':
            wanted = True
        elif wanted and line.strip().startswith('path '):
            result.append(line.strip()[5:].split(' (offset', 1)[0])
            wanted = False
    return result


def system(path):
    return path.startswith(('/usr/lib/', '/System/Library/'))


def resolve(reference, image, executable):
    if reference.startswith('/'):
        candidate = Path(reference)
        if candidate.is_file():
            return candidate.resolve()
    expansions = {'@loader_path': image.parent, '@executable_path': executable.parent}
    for prefix, base in expansions.items():
        if reference.startswith(prefix + '/'):
            candidate = base / reference[len(prefix)+1:]
            if candidate.is_file():
                return candidate.resolve()
    if reference.startswith('@rpath/'):
        for prefix in rpaths(image) + rpaths(executable):
            expanded = prefix
            for name, base in expansions.items():
                expanded = expanded.replace(name, str(base))
            candidate = Path(expanded) / reference[len('@rpath/'):]
            if candidate.is_file():
                return candidate.resolve()
    raise RuntimeError(f'Cannot resolve {reference} needed by {image.name}')


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def import_tools(source, linker, destination):
    if platform.system() != 'Darwin':
        raise RuntimeError('Tool import requires macOS.')
    if destination.exists():
        raise RuntimeError(f'Preserve the existing tool directory before importing: {destination}')
    required = {name: source / name for name in TOOLS}
    for name, path in required.items():
        if not path.is_file():
            raise RuntimeError(f'Missing source tool: {name}')
        if any(not system(dep) for dep in dependencies(path)):
            raise RuntimeError(f'{name} needs an additional dependency review before import.')
    executable = linker.resolve()
    graph, queue = {}, [executable]
    while queue:
        image = queue.pop()
        if image in graph:
            continue
        edges = {}
        for reference in dependencies(image):
            if system(reference):
                continue
            dep = resolve(reference, image, executable)
            if dep != image:
                edges[reference] = dep
                queue.append(dep)
        graph[image] = edges
    names = [p.name for p in graph if p != executable]
    if len(set(names)) != len(names):
        raise RuntimeError('Conflicting dylib basenames require a separate packaging layout.')
    staging = Path(tempfile.mkdtemp(prefix='.Darwin-import-', dir=destination.parent))
    records = {}
    try:
        for name, path in required.items():
            target = staging / name
            shutil.copy2(path, target)
            target.chmod(0o755)
            records[name] = {'source_sha256': sha(path), 'sha256': sha(target), 'dependency_layout_modified': False}
        library = staging / 'lib'
        library.mkdir()
        for image in graph:
            target = staging / 'ld64.lld' if image == executable else library / image.name
            shutil.copy2(image, target)
            target.chmod(0o755)
        for image, edges in graph.items():
            target = staging / 'ld64.lld' if image == executable else library / image.name
            args = ['install_name_tool']
            if image != executable:
                args += ['-id', '@rpath/' + image.name]
            for old, dep in edges.items():
                new = '@loader_path/' + ('lib/' if image == executable else '') + dep.name
                args += ['-change', old, new]
            for path in rpaths(image):
                args += ['-delete_rpath', path]
            if len(args) > 1:
                run(*args, target)
            run('codesign', '--force', '--sign', '-', '--timestamp=none', target)
            relative = str(target.relative_to(staging))
            records[relative] = {'source_sha256': sha(image), 'sha256': sha(target), 'dependency_layout_modified': True}
        # Verify relocation before accepting the bundle.
        for path in [staging / 'ld64.lld', *library.iterdir()]:
            for reference in dependencies(path):
                if not system(reference) and not reference.startswith(('@loader_path/', '@rpath/')):
                    raise RuntimeError(f'Nonportable dependency remains in {path.name}: {reference}')
        run(staging / 'ld64.lld', '--version')
        manifest = {'schema': 1, 'host_architecture': platform.machine(), 'files': records,
                    'purpose': 'Local development bundle; public release license/source review remains required.'}
        (staging / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        # Preserve license notices available in the installed linker packages.
        license_dir = staging / 'licenses'
        license_dir.mkdir()
        for package in sorted({p.parent.parent for p in graph}):
            candidates = list(package.glob('LICENSE*')) + list(package.glob('COPYING*')) + list(package.glob('share/doc/*/LICENSE*'))
            for notice in candidates:
                if notice.is_file():
                    prefix = package.parent.name + '-'
                    shutil.copy2(notice, license_dir / (prefix + notice.name))
        staging.rename(destination)
        print(f'Imported {len(TOOLS) + 1} executables and {len(graph) - 1} linker libraries into {destination}')
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--linker', type=Path, default=shutil.which('ld64.lld'))
    args = parser.parse_args()
    if not args.linker:
        parser.error('Provide --linker or install ld64.lld in PATH.')
    root = Path(__file__).resolve().parents[1]
    import_tools(args.source.expanduser().resolve(), Path(args.linker).expanduser(), root / 'Darwin')
