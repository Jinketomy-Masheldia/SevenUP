"""Pinned dependency downloads: never execute or install an unverified file."""

import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock

from iphone7_port.core import PortError, Project
from iphone7_port.dependencies import dependency

ROOT = Path(__file__).resolve().parents[1]


class DownloadTests(unittest.TestCase):
    def fixture(self, directory):
        root = Path(directory)
        (root / 'profiles').mkdir()
        for name in ('d10-20b82.json', 'sources.lock.json'):
            (root / 'profiles' / name).write_bytes((ROOT / 'profiles' / name).read_bytes())
        body = b'known exact upstream bytes'
        row = {'url': 'https://raw.githubusercontent.com/example/upstream/' + 'a' * 40 + '/tool',
               'repository': 'https://github.com/example/upstream', 'revision': 'a' * 40,
               'sha256': hashlib.sha256(body).hexdigest(), 'size': len(body), 'mode': 0o755}
        (root / 'profiles/dependencies.lock.json').write_text(json.dumps({'schema': 1, 'files': {'Darwin/tool': row}}))
        project = Project(root)
        return project, body

    def test_exact_download_is_atomic_executable_and_reused_without_network(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            project, body = self.fixture(temp)
            def download(command, **kwargs):
                Path(command[-1]).write_bytes(body)
            project.run = Mock(side_effect=download)
            path = dependency(project, 'Darwin/tool')
            self.assertEqual(path.read_bytes(), body)
            self.assertEqual(path.stat().st_mode & 0o777, 0o755)
            self.assertEqual(project.tool('tool'), str(path))
            project.run.assert_called_once()
            self.assertFalse(list(path.parent.glob('.download-*')))

    def test_wrong_download_never_becomes_a_tool_or_falls_back_to_path(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            project, body = self.fixture(temp)
            project.run = Mock(side_effect=lambda command, **kwargs: Path(command[-1]).write_bytes(b'wrong'))
            with self.assertRaisesRegex(PortError, 'checksum/size mismatch'):
                project.tool('tool')
            self.assertFalse((project.root / 'Darwin/tool').exists())
            self.assertFalse(list((project.root / 'Darwin').glob('.download-*')))

    def test_changed_cache_is_preserved_and_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            project, body = self.fixture(temp)
            target = project.root / 'Darwin/tool'
            target.parent.mkdir()
            target.write_bytes(b'changed')
            project.run = Mock()
            with self.assertRaisesRegex(PortError, 'Cached dependency changed'):
                dependency(project, 'Darwin/tool')
            self.assertEqual(target.read_bytes(), b'changed')
            project.run.assert_not_called()

    def test_release_lock_uses_immutable_urls_and_excludes_every_download(self):
        data = json.loads((ROOT / 'profiles/dependencies.lock.json').read_text())
        self.assertEqual(len(data['files']), 6)
        for name, row in data['files'].items():
            self.assertEqual(len(row['revision']), 40)
            self.assertIn('/' + row['revision'] + '/', row['url'])
            self.assertEqual(len(row['sha256']), 64)
            # Isolated ignore checks are part of the release audit; no source
            # repository or Git executable is required for this unit test.
            self.assertIn(name, (ROOT / '.gitignore').read_text())


if __name__ == '__main__':
    unittest.main()
