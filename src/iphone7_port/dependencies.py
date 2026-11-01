"""Fetch exact upstream-only inputs without redistributing them in the source tree."""

import os
import tempfile
from pathlib import Path, PurePosixPath

from .console import say
from .core import digest_file, load_json, require


def dependency(project, relative):
    lock = project.root / 'profiles/dependencies.lock.json'
    if not lock.is_file():
        return None
    profile = load_json(lock)
    require(profile.get('schema') == 1, 'Unexpected dependency lock version.')
    row = profile['files'].get(relative)
    if row is None:
        return None
    name = PurePosixPath(relative)
    require(not name.is_absolute() and '..' not in name.parts, 'Invalid dependency destination.')
    target = project.root / relative
    require(not target.is_symlink() and target.resolve().is_relative_to(project.root.resolve()),
            f'Refusing a redirected dependency path: {relative}')

    def matches(path):
        return path.is_file() and path.stat().st_size == row['size'] and digest_file(path, ('sha256',))['sha256'] == row['sha256']

    if target.exists():
        require(matches(target), f'Cached dependency changed: {relative}. Preserve or move it aside before retrying.')
        target.chmod(row['mode'])
        return target
    # These URLs refer to immutable upstream commits. Never resolve a moving
    # branch or accept another build of an executable with the same filename.
    prefix = row['repository'].replace('https://github.com/', 'https://raw.githubusercontent.com/')
    require(len(row['revision']) == 40 and row['url'].startswith(prefix + '/' + row['revision'] + '/'),
            'Dependency URL is not pinned to its recorded upstream revision.')
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.download-', dir=target.parent)
    os.close(fd)
    partial = Path(temporary)
    try:
        say(f'Downloading exact upstream dependency: {relative}')
        project.run(['curl', '-fL', '--proto', '=https', '--proto-redir', '=https',
                     '--retry', '2', '--retry-all-errors', '--connect-timeout', '15', '--max-time', '300',
                     row['url'], '-o', partial], timeout=1000, live=True)
        require(matches(partial), f'Upstream dependency checksum/size mismatch: {relative}. Nothing was installed.')
        partial.chmod(row['mode'])
        require(not target.exists() and not target.is_symlink(), f'Dependency appeared during download: {relative}. Retry after checking it.')
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    say(f'Verified pinned SHA256: {relative}', 'success')
    return target
