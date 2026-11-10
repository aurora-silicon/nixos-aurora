import importlib.util
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_pnpm_store", ROOT / "docs/check-pnpm-store.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class DocumentationDependencyTests(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(temporary)
        self.expected = self.root / "packages.json"
        self.index = self.root / "index.sql"
        self.expected.write_text(json.dumps(["required@1", "optional-other-platform@2"]))
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.execute("CREATE TABLE package_index (key TEXT PRIMARY KEY, data BLOB)")
            connection.execute("INSERT INTO package_index VALUES (?, ?)", ("sha512-required\trequired@1", b"payload"))
            self.index.write_text("\n".join(connection.iterdump()))

    def test_missing_optional_package_fails_even_when_not_needed_on_host(self):
        with self.assertRaisesRegex(ValueError, "optional-other-platform@2"):
            checker.check(self.expected, self.index)

    def test_complete_store_passes_without_changing_dump(self):
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.executescript(self.index.read_text())
            connection.execute("INSERT INTO package_index VALUES (?, ?)",
                               ("sha512-optional\toptional-other-platform@2", b"payload"))
            self.index.write_text("\n".join(connection.iterdump()))
        before = self.index.read_bytes()
        checker.check(self.expected, self.index)
        self.assertEqual(self.index.read_bytes(), before)

    def test_missing_index_is_not_created_as_an_empty_store(self):
        self.index.unlink()
        with self.assertRaises(FileNotFoundError):
            checker.check(self.expected, self.index)
        self.assertFalse(self.index.exists())
