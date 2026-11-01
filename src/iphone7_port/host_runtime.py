"""Unpack the large, project-local linker dependency on first use."""

import lzma
import os
import shutil
import tempfile
from pathlib import Path

from .console import say
from .core import digest_file, load_json, require


def prepare_linker(project):
    bundle = project.root / 'Darwin'
    manifest = bundle / 'manifest.json'
    # Tiny fixture linkers and externally installed linkers need no expansion.
    if not manifest.is_file():
        return
    entries = load_json(manifest)['files']
    for relative, row in entries.items():
        packed = row.get('compressed')
        if not packed:
            continue
        target = bundle / relative
        require(target.resolve().is_relative_to(bundle.resolve()), 'Invalid bundled library location.')
        if target.is_file() and digest_file(target, ('sha256',))['sha256'] == row['sha256']:
            continue
        source = bundle / packed['filename']
        require(source.is_file() and source.resolve().is_relative_to(bundle.resolve())
                and digest_file(source, ('sha256',))['sha256'] == packed['sha256'], 'Bundled compressed linker library is missing or changed.')
        say(f'Unpacking bundled linker dependency: {target.name}')
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.unpack-', dir=target.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, 'wb') as output, lzma.open(source, 'rb') as content:
                shutil.copyfileobj(content, output)
            require(temporary.stat().st_size == packed['size']
                    and digest_file(temporary, ('sha256',))['sha256'] == row['sha256'], 'Expanded linker library differs from its manifest.')
            temporary.chmod(0o755)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
