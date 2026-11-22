import contextlib
import io
import os
import sqlite3
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mac_text_replacements_to_gboard as tool  # noqa: E402

HEADER_LINES = [
    "# Gboard Dictionary version:2",
    "# Gboard Dictionary format:shortcut\tword\tlanguage_tag\tpos_tag",
]

SCHEMA = (
    "CREATE TABLE ZTEXTREPLACEMENTENTRY ("
    "Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZNEEDSSAVETOCLOUD INTEGER, "
    "ZWASDELETED INTEGER, ZTIMESTAMP TIMESTAMP, ZPHRASE VARCHAR, ZSHORTCUT VARCHAR, "
    "ZUNIQUENAME VARCHAR, ZREMOTERECORDINFO BLOB)"
)


def make_db(path, rows):
    """rowsは（読み, 語, 消した印）の並び。消した印はNone・0・1。"""
    con = sqlite3.connect(path)
    con.execute(SCHEMA)
    con.executemany(
        "INSERT INTO ZTEXTREPLACEMENTENTRY (ZSHORTCUT, ZPHRASE, ZWASDELETED) VALUES (?, ?, ?)",
        rows,
    )
    con.commit()
    con.close()


class ToolTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db = self.root / "TextReplacements.db"
        self.out = self.root / "out"
        self.out.mkdir()
        self.config = self.root / "repo" / "config"
        self.config.parent.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def run_tool(self, *args, config_path=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = tool.main(list(args), config_path=config_path or self.config)
        return code, stdout.getvalue(), stderr.getvalue()

    def run_to_out(self, *args):
        return self.run_tool("--db", str(self.db), "--out", str(self.out), *args)

    def output_lines(self):
        return (self.out / "dictionary.txt").read_text(encoding="utf-8").split("\n")


class FormatTest(ToolTestCase):
    def test_writes_gboard_v2_format(self):
        make_db(self.db, [("あ", "語A", None), ("い", "語B", 0), ("う", "消した語", 1)])
        code, stdout, _ = self.run_to_out()
        self.assertEqual(code, 0)
        self.assertIn("2件を書き出しました", stdout)
        raw = (self.out / "dictionary.txt").read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), "BOMを付けない")
        self.assertNotIn(b"\r", raw)
        self.assertTrue(raw.endswith(b"\n"))
        lines = self.output_lines()
        self.assertEqual(lines[:2], HEADER_LINES)
        self.assertEqual(lines[2:], ["あ\t語A\tja-JP\t", "い\t語B\tja-JP\t", ""])

    def test_merges_duplicates_and_sorts(self):
        make_db(self.db, [("さ", "語2", 0), ("か", "語1", 0), ("さ", "語2", None), ("か", "語0", 0)])
        self.assertEqual(self.run_to_out()[0], 0)
        self.assertEqual(
            self.output_lines()[2:],
            ["か\t語0\tja-JP\t", "か\t語1\tja-JP\t", "さ\t語2\tja-JP\t", ""],
        )

    def test_keeps_entries_whose_reading_equals_word(self):
        make_db(self.db, [("ほげ", "ほげ", 0)])
        self.assertEqual(self.run_to_out()[0], 0)
        self.assertEqual(self.output_lines()[2], "ほげ\tほげ\tja-JP\t")

    def test_overwrites_existing_file(self):
        (self.out / "dictionary.txt").write_text("old", encoding="utf-8")
        make_db(self.db, [("あ", "語", 0)])
        self.assertEqual(self.run_to_out()[0], 0)
        self.assertEqual(self.output_lines()[:2], HEADER_LINES)

    def test_file_mode_follows_umask(self):
        make_db(self.db, [("あ", "語", 0)])
        old = os.umask(0o022)
        try:
            self.assertEqual(self.run_to_out()[0], 0)
        finally:
            os.umask(old)
        mode = stat.S_IMODE((self.out / "dictionary.txt").stat().st_mode)
        self.assertEqual(mode, 0o644)


class ValidationTest(ToolTestCase):
    def assert_stops_without_writing(self, rows, message):
        (self.out / "dictionary.txt").write_text("old", encoding="utf-8")
        make_db(self.db, rows)
        code, stdout, stderr = self.run_to_out()
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn(message, stderr)
        self.assertEqual((self.out / "dictionary.txt").read_text(encoding="utf-8"), "old")
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), ["dictionary.txt"])

    def test_tab_in_word(self):
        self.assert_stops_without_writing([("あ", "語\tX", 0), ("い", "語", 0)], "入れられない語が1件")

    def test_newline_and_cr(self):
        self.assert_stops_without_writing([("あ\n", "語", 0), ("い", "語\r", 0)], "入れられない語が2件")

    def test_empty_and_null(self):
        self.assert_stops_without_writing([("", "語", 0), ("い", None, 0)], "入れられない語が2件")

    def test_no_entries(self):
        self.assert_stops_without_writing([("う", "消した語", 1)], "1件もありません")


class OutputDirTest(ToolTestCase):
    def test_missing_output_dir_is_not_created(self):
        make_db(self.db, [("あ", "語", 0)])
        missing = self.root / "nas" / "gboard-import"
        code, _, stderr = self.run_tool("--db", str(self.db), "--out", str(missing))
        self.assertEqual(code, 1)
        self.assertIn("出力先のフォルダがありません", stderr)
        self.assertFalse(missing.exists())
        self.assertFalse(missing.parent.exists())

    def test_no_temp_file_left_when_replace_fails(self):
        make_db(self.db, [("あ", "語", 0)])
        (self.out / "dictionary.txt").write_text("old", encoding="utf-8")
        with mock.patch.object(tool.os, "replace", side_effect=OSError("replace failed")):
            code, _, stderr = self.run_to_out()
        self.assertEqual(code, 1)
        self.assertIn("replace failed", stderr)
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), ["dictionary.txt"])
        self.assertEqual((self.out / "dictionary.txt").read_text(encoding="utf-8"), "old")


class ConfigTest(ToolTestCase):
    def setUp(self):
        super().setUp()
        make_db(self.db, [("あ", "語", 0)])

    def test_reads_out_from_config(self):
        self.config.write_text(f"# コメント\n\nout={self.out}\n", encoding="utf-8")
        code, stdout, _ = self.run_tool("--db", str(self.db))
        self.assertEqual(code, 0)
        self.assertTrue((self.out / "dictionary.txt").is_file())

    def test_expands_home(self):
        home = self.root / "home"
        (home / "dict").mkdir(parents=True)
        self.config.write_text("out=~/dict\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            code, _, _ = self.run_tool("--db", str(self.db))
        self.assertEqual(code, 0)
        self.assertTrue((home / "dict" / "dictionary.txt").is_file())

    def test_out_option_overrides_config(self):
        other = self.root / "other"
        other.mkdir()
        self.config.write_text(f"out={self.out}\n", encoding="utf-8")
        self.assertEqual(self.run_tool("--db", str(self.db), "--out", str(other))[0], 0)
        self.assertTrue((other / "dictionary.txt").is_file())
        self.assertFalse((self.out / "dictionary.txt").exists())

    def test_no_config_and_no_out(self):
        code, _, stderr = self.run_tool("--db", str(self.db))
        self.assertEqual(code, 1)
        self.assertIn("config.example", stderr)

    def test_unknown_key(self):
        self.config.write_text(f"out={self.out}\noutput=/tmp\n", encoding="utf-8")
        code, _, stderr = self.run_tool("--db", str(self.db))
        self.assertEqual(code, 1)
        self.assertIn("2行目のキー「output」", stderr)

    def test_line_without_equals(self):
        self.config.write_text(f"{self.out}\n", encoding="utf-8")
        code, _, stderr = self.run_tool("--db", str(self.db))
        self.assertEqual(code, 1)
        self.assertIn("キー=値", stderr)

    def test_relative_out_in_config(self):
        self.config.write_text("out=out\n", encoding="utf-8")
        code, _, stderr = self.run_tool("--db", str(self.db))
        self.assertEqual(code, 1)
        self.assertIn("絶対パス", stderr)


class DatabaseTest(ToolTestCase):
    def test_missing_db(self):
        code, _, stderr = self.run_tool("--db", str(self.root / "none.db"), "--out", str(self.out))
        self.assertEqual(code, 1)
        self.assertIn("辞書のファイルがありません", stderr)

    def test_db_without_table(self):
        sqlite3.connect(self.db).close()
        code, _, stderr = self.run_to_out()
        self.assertEqual(code, 1)
        self.assertIn("辞書を読めません", stderr)

    def test_db_path_with_uri_special_chars(self):
        folder = self.root / "a?b#c%d e"
        folder.mkdir()
        db = folder / "TextReplacements.db"
        make_db(db, [("あ", "語", 0)])
        code, _, stderr = self.run_tool("--db", str(db), "--out", str(self.out))
        self.assertEqual(code, 0, stderr)
        self.assertEqual(self.output_lines()[2], "あ\t語\tja-JP\t")

    def test_reads_wal_without_changing_files(self):
        writer = sqlite3.connect(self.db)
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute(SCHEMA)
        writer.execute(
            "INSERT INTO ZTEXTREPLACEMENTENTRY (ZSHORTCUT, ZPHRASE, ZWASDELETED) VALUES ('あ', '語', 0)"
        )
        writer.commit()
        try:
            wal = Path(str(self.db) + "-wal")
            before = (self.db.read_bytes(), wal.read_bytes())
            code, _, stderr = self.run_to_out()
            self.assertEqual(code, 0, stderr)
            self.assertEqual(self.output_lines()[2], "あ\t語\tja-JP\t")
            self.assertEqual((self.db.read_bytes(), wal.read_bytes()), before)
        finally:
            writer.close()


if __name__ == "__main__":
    unittest.main()
