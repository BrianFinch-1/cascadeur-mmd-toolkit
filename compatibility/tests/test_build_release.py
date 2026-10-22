"""Check artifact integrity and builds with/without development bytecode."""
import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location("mmd_builder", Path(__file__).parents[1] / "build_release.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class BuildTests(unittest.TestCase):
    cache = None

    def test_corrupt_cache_rejected_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            (cache / "artifact.zip").write_bytes(b"corrupt")
            sha = hashlib.sha256(b"expected").hexdigest()
            with patch.object(builder, "SOURCES", [("artifact.zip", "https://example.invalid/artifact", sha)]):
                with patch.object(builder.urllib.request, "urlretrieve") as request:
                    with self.assertRaisesRegex(ValueError, "Cached artifact hash mismatch"):
                        builder.fetch(cache)
                    request.assert_not_called()

    def test_bytecode_does_not_change_package_and_all_hashes_match(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with contextlib.redirect_stdout(io.StringIO()):
                clean = builder.build(self.cache, output / "clean")
            cache_dir = builder.HERE / "overlay/payload/resources/scripts/python/scripts/vmd_bridge/__pycache__"
            existed = cache_dir.exists()
            cache_dir.mkdir(exist_ok=True)
            pollution = cache_dir / "review_only.cpython-311.pyc"
            self.assertFalse(pollution.exists())
            try:
                pollution.write_bytes(b"stale development bytecode")
                with contextlib.redirect_stdout(io.StringIO()):
                    rebuilt = builder.build(self.cache, output / "with-cache")
                self.assertEqual(clean.read_bytes(), rebuilt.read_bytes())
            finally:
                pollution.unlink(missing_ok=True)
                if not existed:
                    cache_dir.rmdir()
            with zipfile.ZipFile(clean) as archive:
                self.assertFalse(any("__pycache__" in name or name.endswith((".pyc", ".pyo")) for name in archive.namelist()))
                prefix = "cascadeur MMD toolkit 1.0/"
                manifest = json.loads(archive.read(prefix + "MANIFEST-SHA256.json").decode("utf-8-sig"))
                self.assertEqual(manifest["compatibility_revision"], 2)
                with zipfile.ZipFile(self.cache / builder.SOURCES[0][0]) as upstream:
                    dialogs = prefix + "payload/resources/scripts/python/scripts/vmd_bridge/dialogs.py"
                    self.assertEqual(upstream.read(dialogs), archive.read(dialogs.replace("/dialogs.py", "/_dialogs_modern.py")))
                for entry in manifest["files"] + [dict(file, source=file["path"]) for file in manifest["package_files"]]:
                    data = archive.read(prefix + entry["source"])
                    self.assertEqual(len(data), entry["size"])
                    self.assertEqual(hashlib.sha256(data).hexdigest().upper(), entry["sha256"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    BuildTests.cache = args.cache.resolve()
    unittest.main(argv=[__file__], verbosity=2)
