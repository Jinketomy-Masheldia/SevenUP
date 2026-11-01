"""Host-only regressions for fixed firmware recipes and delta reconstruction."""

import base64
import bz2
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from iphone7_port.core import PortError, Project
from iphone7_port.rootfs_source import apply_delta, checked_file, delta_writes, recipes

ROOT = Path(__file__).resolve().parents[1]


class RecipeTests(unittest.TestCase):
    def test_all_recipe_outputs_match_the_working_reference(self):
        rows = recipes(Project(ROOT))
        self.assertEqual(len(rows), 667)
        self.assertEqual(sum(row['method'] == 'delta' for row in rows), 17)
        for row in rows:
            if row['method'] == 'delta':
                path = ROOT / row['delta']
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), row['delta_sha256'])
                delta_writes(json.loads(bz2.decompress(path.read_bytes())), row)
            elif row['method'] == 'project':
                checked_file(ROOT, row['resource'], row['size'], row['sha256'])

    def test_delta_reconstructs_extension_and_checks_metadata_and_bounds(self):
        original, result = b'original', b'oriNEWal\x00!'
        sha = lambda value: hashlib.sha256(value).hexdigest()
        data = {'schema': 1, 'source_sha256': sha(original), 'source_size': len(original),
                'target_sha256': sha(result), 'target_size': len(result),
                'writes': [[3, base64.b64encode(b'NEW').decode()], [9, base64.b64encode(b'!').decode()]]}
        row = {'source_sha256': sha(original), 'source_size': len(original), 'sha256': sha(result), 'size': len(result), 'delta': 'edit.bz2'}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, target = root / 'source', root / 'target'
            source.write_bytes(original)
            delta = bz2.compress(json.dumps(data).encode())
            (root / row['delta']).write_bytes(delta)
            row['delta_sha256'] = sha(delta)
            from types import SimpleNamespace
            apply_delta(SimpleNamespace(root=root), source, target, row)
            self.assertEqual(target.read_bytes(), result)
            for writes in ([[[-1, 'YQ==']]], [[[9, 'YWI=']]], [[[2, 'YWI='], [3, 'YQ==']]]):
                with self.assertRaises(PortError):
                    delta_writes({**data, 'writes': writes[0]}, row)
            with self.assertRaises(PortError):
                delta_writes({**data, 'source_sha256': 'wrong'}, row)
            (root / row['delta']).write_bytes(b'changed')
            with self.assertRaises(PortError):
                apply_delta(SimpleNamespace(root=root), source, target, row)

    def test_sources_cannot_escape_their_image_or_use_wrong_content(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'image'
            root.mkdir()
            other = Path(temp) / 'outside'
            other.write_bytes(b'expected')
            (root / 'link').symlink_to(other)
            with self.assertRaises(PortError):
                checked_file(root, 'link', 8, hashlib.sha256(b'expected').hexdigest())
            (root / 'file').write_bytes(b'unexpected')
            with self.assertRaises(PortError):
                checked_file(root, 'file', 8, hashlib.sha256(b'expected').hexdigest())


if __name__ == '__main__':
    unittest.main()
