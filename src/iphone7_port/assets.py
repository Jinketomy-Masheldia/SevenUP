"""Fixed project-relative bootstrap inputs; no user configuration file."""

import plistlib

from .core import digest_file, require

ASSETS = {
    'ssh.tar.gz': 'ddfa230acd2789c7e61ddb0d2ec3df9a6c741f2ddcab58fc1a826d278be1d74d',
    '0x8010.shsh': '44063c69e41a463d573fe9f524fe615e467fe245d8967c1d2951d724e1baac7d',
}


def asset(project, name):
    require(name in ASSETS, 'Unknown bundled SSHRD resource.')
    from .dependencies import dependency
    path = dependency(project, 'resources/sshrd/' + name)
    require(path is not None and path.is_file() and not path.is_symlink(), f'Missing fixed SSHRD resource: resources/sshrd/{name}. Restore profiles/dependencies.lock.json.')
    require(digest_file(path, ('sha256',))['sha256'] == ASSETS[name], f'Fixed resource changed: {name}')
    return path


def bootstrap_ticket(project):
    ticket = plistlib.loads(asset(project, '0x8010.shsh').read_bytes()).get('ApImg4Ticket')
    require(isinstance(ticket, bytes), 'Bundled bootstrap preset does not contain ApImg4Ticket.')
    return ticket
