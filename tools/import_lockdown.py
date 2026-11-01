#!/usr/bin/env python3
"""Reproduce the relative-load-path modifications for the lockdown libraries.

Maintenance utility, not needed for ordinary installation. Supply locally built
libimobiledevice/libplist libraries and their build dependencies. Never contacts
an iPhone. Keep the original source package recipes and licenses with the bundle.
"""

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from import_darwin import dependencies, resolve, rpaths, run, sha, system


def bundle(starts, destination, notices):
    if destination.exists():
        raise RuntimeError(f'Preserve the existing library bundle first: {destination}')
    graph, queue = {}, list(starts)
    while queue:
        image = queue.pop()
        if image in graph:
            continue
        edges = {}
        for reference in dependencies(image):
            if system(reference):
                continue
            dep = resolve(reference, image, image)
            if dep != image:
                edges[reference] = dep
                queue.append(dep)
        graph[image] = edges
    if len({image.name for image in graph}) != len(graph):
        raise RuntimeError('Duplicate library basenames need a separate layout review.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.lockdown-', dir=destination.parent))
    records = {}
    try:
        for image in graph:
            target = staging / image.name
            shutil.copy2(image, target)
            target.chmod(0o755)
        for image, edges in graph.items():
            target = staging / image.name
            args = ['install_name_tool', '-id', '@rpath/' + image.name]
            for reference, dep in edges.items():
                args += ['-change', reference, '@loader_path/' + dep.name]
            for old in rpaths(image):
                args += ['-delete_rpath', old]
            run(*args, target)
            run('codesign', '--force', '--sign', '-', '--timestamp=none', target)
            if any(not system(ref) and not ref.startswith(('@loader_path/', '@rpath/')) for ref in dependencies(target)):
                raise RuntimeError('A nonportable library dependency remains.')
            records[image.name] = {'source_sha256': sha(image), 'sha256': sha(target)}
        for alias, source in zip(('libimobiledevice-1.0.dylib', 'libplist-2.0.dylib'), starts):
            (staging / alias).symlink_to(source.name)
        notices.mkdir(parents=True, exist_ok=True)
        for package in {image.parent.parent for image in graph}:
            for pattern in ('LICENSE*', 'COPYING*', 'share/doc/*/LICENSE*', 'share/doc/*/COPYING*'):
                for notice in package.glob(pattern):
                    if notice.is_file():
                        shutil.copy2(notice, notices / (package.parent.name + '-' + notice.name))
        (staging / 'manifest.json').write_text(json.dumps({'schema': 1, 'libraries': records,
            'source': 'Local source package builds; relative load paths and ad-hoc signatures applied.'}, indent=2) + '\n')
        staging.rename(destination)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--libimobiledevice', type=Path, required=True)
    parser.add_argument('--libplist', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    bundle([args.libimobiledevice.resolve(), args.libplist.resolve()],
           root / 'Darwin/lib/lockdown', root / 'Darwin/licenses/lockdown')
