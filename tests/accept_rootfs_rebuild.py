"""Host acceptance: rebuild all rootfs fixes in a relocated, isolated checkout.

Requires prepared IPSW components and an original stock-resource fixture (either
captured from a supported phone or extracted from the verified stock IPSW).
Never contacts or modifies a phone. The fixture is not a device-capture test.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def child(root, forbidden):
    sys.path.insert(0, str(root / 'src'))

    def audit(event, arguments):
        if event == 'open' and isinstance(arguments[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(arguments[0])).absolute()
            if path.is_relative_to(forbidden):
                raise RuntimeError(f'External research/project read attempted: {path}')

    sys.addaudithook(audit)
    from iphone7_port.core import Project
    from iphone7_port.rootfs_source import prepare_patches
    from iphone7_port.rootfs_patches import verify_patches
    from iphone7_port.accessibility import Lockdown
    from iphone7_port.assets import ASSETS, asset, bootstrap_ticket
    project = Project(root)
    for name in ASSETS:
        asset(project, name)
    assert len(bootstrap_ticket(project)) > 0
    project.record('stock-rootfs-resources', {'folder': 'work/stock-fixture', 'build': '19H422',
                                           'source': 'host-acceptance-fixture-not-device-capture'})
    result = prepare_patches(project)
    assert len(result['variants']['with-ssh']['files']) == 667
    verify_patches(project)
    prepare_patches(project)  # Idempotent reuse, no private research importer.
    api = Lockdown(project)  # API loading only; never enumerate/connect a phone.
    assert str(root / 'Darwin') in api.mobile._name
    assert subprocess.run([project.linker(), '--version'], check=True, capture_output=True).stdout
    print('PASS: 667 exact rootfs outputs, both signed patch archives, bundled assets/libraries/linker; external project reads blocked.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--stock-fixture', type=Path)
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--forbidden', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        return child(args.project, args.forbidden)
    source = args.project.resolve()
    fixture = args.stock_fixture
    if fixture is None:
        sys.path.insert(0, str(source / 'src'))
        from iphone7_port.core import Project
        from iphone7_port.stock_resources import stock_folder
        fixture = stock_folder(Project(source))
    with tempfile.TemporaryDirectory(prefix='iphone7-standalone-') as directory:
        root = Path(directory).resolve() / 'checkout'
        root.mkdir()
        for name in ('src', 'profiles', 'resources', 'Darwin'):
            shutil.copytree(source / name, root / name, symlinks=True,
                            ignore=shutil.ignore_patterns('__pycache__', 'libLLVM.23.1.dylib'))
        (root / 'local.json').write_text('legacy configuration intentionally invalid and ignored')
        shutil.copytree(fixture, root / 'work/stock-fixture')
        for role, components in {'ipad_target': ('OS', 'Cryptex1,SystemOS'), 'iphone8_donor': ('OS',)}.items():
            extracted = source / 'work/extracted' / role
            receipt = json.loads((extracted / 'resources.json').read_text())
            target = root / 'work/extracted' / role
            target.mkdir(parents=True)
            shutil.copyfile(extracted / 'resources.json', target / 'resources.json')
            for component in components:
                relative = receipt['components'][component]
                (target / relative).parent.mkdir(parents=True, exist_ok=True)
                # APFS clone avoids another full image allocation on macOS.
                subprocess.run(['/bin/cp', '-c', str(extracted / relative), str(target / relative)], check=True)
        script = root / 'accept_rootfs_rebuild.py'
        shutil.copyfile(__file__, script)
        subprocess.run([sys.executable, str(script), '--child', '--project', str(root), '--forbidden', str(source.parent)],
                       check=True, cwd=root, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': str(root / 'src')})


if __name__ == '__main__':
    main()
