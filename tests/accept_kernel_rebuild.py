"""Opt-in host integration acceptance: fresh build with legacy inputs denied.

Run from the project root: PYTHONPATH=src python3 tests/accept_kernel_rebuild.py
Requires verified IPSW components and the configured local compiler/tool suite.
This does not connect to a phone.
"""

import json
import sys
from pathlib import Path

from iphone7_port.core import Project, digest_file, save_json
from iphone7_port.kernel_chain import rebuild


root = Path(__file__).resolve().parents[1]
project = Project(root)
legacy = root.parent
forbidden = [legacy / name for name in ['mywork', 'bootchain', 'bootchain.old', 'ipad', 'iphone', 'test16', 'sshramdisk', 'sshramdisk.bak']]
blocked = []


def reject(path):
    if not isinstance(path, (str, bytes)):
        return
    if isinstance(path, bytes):
        path = path.decode(errors='replace')
    candidate = Path(path).resolve()
    if any(candidate == prefix or prefix in candidate.parents for prefix in forbidden):
        blocked.append(str(candidate))
        raise RuntimeError(f'Fresh reconstruction attempted to read a forbidden legacy input: {candidate}')


def audit(event, args):
    if event == 'open':
        reject(args[0])
    elif event == 'subprocess.Popen':
        command = args[1]
        for argument in command if isinstance(command, (list, tuple)) else [command]:
            if isinstance(argument, str) and argument.startswith('/'):
                reject(argument)


sys.addaudithook(audit)
raw = rebuild(project, fresh=True)
stage = project.stage('kernel')
record = {'fresh_build_passed': True, 'legacy_inputs_denied': [p.name for p in forbidden],
          'forbidden_access_attempts': blocked, 'raw_sha256': digest_file(raw, ('sha256',))['sha256'],
          'im4p_sha256': stage['im4p_sha256'], 'image_sha256': stage['image_hashes']['sha256'],
          'clean_workspace': project.stage('kernel-clean-validation')['workspace'],
          'all_28_checkpoints_passed': True, 'phone_operations_performed': False}
save_json(project.work / 'kernel-fresh-acceptance.json', record)
print(json.dumps(record, indent=2))
