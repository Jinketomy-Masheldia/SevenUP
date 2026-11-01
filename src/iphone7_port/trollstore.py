"""Install only the upstream embedded persistence helper into Data's Tips app."""

import re
import shlex
import uuid
from pathlib import Path

from .console import say
from .core import require
from .install import mounts, verify_ramdisk

URL = 'https://github.com/opa334/TrollStore/releases/download/2.1.1/PersistenceHelper_Embedded'
BASE = '/mnt2/containers/Bundle/Application'
TIPS = re.compile(re.escape(BASE) + r'/[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}/Tips\.app/Tips')


def download_helper(project):
    folder = project.work / 'downloads/trollstore-2.1.1'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / 'PersistenceHelper_Embedded'
    require(not target.is_symlink(), 'Refusing a symbolic persistence-helper download path.')
    if not target.is_file():
        partial = folder / ('download-' + uuid.uuid4().hex + '.part')
        say('Downloading TrollStore 2.1.1 embedded persistence helper.')
        try:
            project.run(['curl', '-fL', '--retry', '2', '--connect-timeout', '15', '--max-time', '180',
                         URL, '-o', partial], timeout=240, live=True)
            with partial.open('rb') as stream:
                magic = stream.read(4)
            require(magic in (b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe',
                              b'\xbe\xba\xfe\xca', b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca'),
                    'The downloaded persistence helper is not a Mach-O binary.')
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)
    return target


def tips_search_script(base=BASE):
    parents = [str(parent) for parent in reversed(Path(base).parents) if str(parent) != '/'] + [base]
    return f'''for parent in {' '.join(map(shlex.quote, parents))}; do
    if [ -L "$parent" ]; then echo 'Refusing a symbolic Tips container path.' >&2; exit 20; fi
done
for container in {shlex.quote(base)}/*; do
    app="$container/Tips.app"
    if [ ! -d "$app" ] && [ ! -L "$app" ]; then continue; fi
    if [ -L "$container" ] || [ -L "$app" ] || [ -L "$app/Tips" ]; then
        echo 'Refusing a symbolic Tips application path.' >&2; exit 20
    fi
    if [ -d "$app" ] && [ -f "$app/Tips" ]; then printf '%s\\n' "$app/Tips"; fi
done
'''


def replacement_script(executable, staged):
    original, new, backup = map(shlex.quote, (executable, staged, executable + '.bak'))
    return f'''[ -f {original} ] && [ ! -L {original} ]
if [ -e {backup} ] || [ -L {backup} ]; then
    echo 'Tips.bak already exists; the existing backup will not be overwritten.' >&2; exit 21
fi
[ -f {new} ] && [ ! -L {new} ]
chmod 0755 {new}
chown 33:33 {new}
mv {original} {backup}
if ! mv {new} {original}; then
    mv {backup} {original}
    echo 'Could not replace Tips; the original executable was restored.' >&2; exit 22
fi
sync
'''


def install_trollstore(project, ssh):
    verify_ramdisk(project, ssh)
    rows = mounts(ssh.run('/sbin/mount'))
    require(not any(path == '/mnt2' and device not in ('/dev/disk1s2', '/dev/disk0s1s2')
                    for device, path in rows), '/mnt2 is occupied by another filesystem.')
    if not any(path == '/mnt2' and device in ('/dev/disk1s2', '/dev/disk0s1s2') for device, path in rows):
        say('Data is not mounted at /mnt2. Mount it in SSHRD, then rerun install trollstore. No files were changed.', 'warning')
        return False
    say('Searching /mnt2/containers/Bundle/Application/*/Tips.app/Tips.')
    paths = [line.strip() for line in ssh.script(tips_search_script()).splitlines() if line.strip()]
    if not paths:
        say('Tips was not found. Boot iOS, install Tips from the App Store, then return to SSHRD and rerun install trollstore.', 'warning')
        return False
    require(len(paths) == 1 and TIPS.fullmatch(paths[0]) is not None,
            'Cannot uniquely identify a real Tips executable in the Data app containers.')
    executable = paths[0]
    backup = shlex.quote(executable + '.bak')
    ssh.script(f'''if [ -e {backup} ] || [ -L {backup} ]; then
    echo 'Tips.bak already exists; refusing to overwrite it.' >&2; exit 21
fi
''')
    helper = download_helper(project)
    staged = str(Path(executable).parent / ('.iphone7-ios16-helper-' + uuid.uuid4().hex))
    say('Uploading the embedded persistence helper into the discovered Tips bundle.')
    ssh.transfer(helper, 'root@127.0.0.1:' + shlex.quote(staged))
    ssh.script(replacement_script(executable, staged), label='ssh: preserve Tips as Tips.bak; install embedded persistence helper')
    project.record('install-trollstore', {'version': '2.1.1', 'source': URL, 'executable': executable,
                                        'backup': executable + '.bak', 'persistence_helper_only': True})
    say('Embedded persistence helper installed. After booting iOS, open Tips to install TrollStore.', 'success')
    return True
