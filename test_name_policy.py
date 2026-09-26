#!/usr/bin/env python3

import os
import re
import tempfile
import unittest
import unicodedata
from pathlib import Path

from chomikuj.base_account_folder import BaseAccountFolder
from chomikuj.download_manager import DownloadManager
from chomikuj.name_policy import NAME_POLICY
from chomikuj.upload_manager import UploadManager


WINDOWS_FORBIDDEN_CHARS = '<>:"/\\|?*'


class NamePolicyTest(unittest.TestCase):
    def test_local_component_preserves_readable_unicode(self):
        names = [
            "Edyta Górniak.rar",
            "Maanam - Wyjątkowo Zimny Maj [VIDEO].zip",
            "Czesław Niemen - Sen o Warszawie.zip",
            "Zażółć gęślą jaźń.rar",
            "漢字-🎵.flac",
        ]

        for name in names:
            with self.subTest(name=name):
                self.assertEqual(NAME_POLICY.local_component_sanitize(name), name)

    def test_local_component_encodes_forbidden_characters(self):
        sanitized = NAME_POLICY.local_component_sanitize(f"a{WINDOWS_FORBIDDEN_CHARS}b")

        self.assertEqual(sanitized, "a~3c~3e~3a~22~2f~5c~7c~3f~2ab")
        for char in WINDOWS_FORBIDDEN_CHARS:
            with self.subTest(char=char):
                self.assertNotIn(char, sanitized)

    def test_local_component_encodes_edges_and_unprintable_characters(self):
        cases = {
            " file.txt": "~20file.txt",
            ".file.txt": "~2efile.txt",
            "file.txt ": "file.txt~20",
            "file.txt.": "file.txt~2e",
            "line\nbreak.txt": "line~0abreak.txt",
            "zero\u200bwidth.txt": "zero~e2~80~8bwidth.txt",
            "delete\x7f.txt": "delete~7f.txt",
        }

        for original, expected in cases.items():
            with self.subTest(original=original):
                self.assertEqual(NAME_POLICY.local_component_sanitize(original), expected)

    def test_local_component_encodes_reserved_windows_names(self):
        cases = {
            "CON": "~43ON",
            "con.txt": "~63on.txt",
            "CON.tar.gz": "~43ON.tar.gz",
            "AUX.backup.old": "~41UX.backup.old",
            "NUL.foo.bar": "~4eUL.foo.bar",
            "COM1.archive.zip": "~43OM1.archive.zip",
            "lpt9.foo.txt": "~6cpt9.foo.txt",
            "COM¹": "~43OM¹",
            "LPT³.rar": "~4cPT³.rar",
        }

        for original, expected in cases.items():
            with self.subTest(original=original):
                self.assertEqual(NAME_POLICY.local_component_sanitize(original), expected)

    def test_local_component_escapes_marker_without_collisions(self):
        self.assertEqual(NAME_POLICY.local_component_sanitize("a~3cb.txt"), "a~7e3cb.txt")
        self.assertEqual(NAME_POLICY.local_component_sanitize("a<b.txt"), "a~3cb.txt")

    def test_local_component_can_be_created_on_filesystem(self):
        names = [
            "Edyta Górniak.rar",
            f"a{WINDOWS_FORBIDDEN_CHARS}b.zip",
            "CON.tar.gz",
            " file .txt",
        ]

        with tempfile.TemporaryDirectory() as directory:
            for name in names:
                with self.subTest(name=name):
                    path = Path(directory) / NAME_POLICY.local_component_sanitize(name)
                    path.touch()
                    self.assertTrue(path.exists())

    def test_url_component_supports_chomikuj_and_percent_escapes(self):
        original = "PŁYTY DLA/NAJMŁODSZYCH"
        encoded = "P*c5*81YTY+DLA*2fNAJM*c5*81ODSZYCH"

        self.assertEqual(NAME_POLICY.url_component_encode(original), encoded)
        self.assertEqual(NAME_POLICY.url_component_decode(encoded), original)
        self.assertEqual(NAME_POLICY.url_component_decode("P%c5%81YTY+DLA"), "PŁYTY DLA")

    def test_remote_name_key_does_not_decode_api_names_as_urls(self):
        self.assertNotEqual(NAME_POLICY.remote_name_key("C++"), NAME_POLICY.remote_name_key("C  "))
        self.assertNotEqual(NAME_POLICY.remote_name_key("file*2a"), NAME_POLICY.remote_name_key("file*"))
        self.assertEqual(NAME_POLICY.remote_name_key("ŁÓDŹ"), NAME_POLICY.remote_name_key("łódź"))

        decomposed = unicodedata.normalize("NFD", "Górniak")
        self.assertEqual(NAME_POLICY.remote_name_key("Górniak"), NAME_POLICY.remote_name_key(decomposed))

    def test_local_path_key_detects_portable_collisions(self):
        with tempfile.TemporaryDirectory() as directory:
            upper = os.path.join(directory, "FILE.txt")
            lower = os.path.join(directory, "file.txt")
            decomposed = os.path.join(directory, unicodedata.normalize("NFD", "Górniak.txt"))
            composed = os.path.join(directory, "Górniak.txt")

            self.assertEqual(NAME_POLICY.local_path_key(upper), NAME_POLICY.local_path_key(lower))
            self.assertEqual(NAME_POLICY.local_path_key(decomposed), NAME_POLICY.local_path_key(composed))

    def test_local_path_disambiguation_is_stable_and_preserves_extension(self):
        first = list(NAME_POLICY.local_path_candidates("/tmp/file.tar.gz", "folder\0FILE.tar.gz"))
        second = list(NAME_POLICY.local_path_candidates("/tmp/file.tar.gz", "folder\0FILE.tar.gz"))

        self.assertEqual(first, second)
        self.assertEqual(first[0], "/tmp/file.tar.gz")
        self.assertRegex(first[1], r"/tmp/file\.tar~[0-9a-f]{12}\.gz$")
        self.assertRegex(first[2], r"/tmp/file\.tar~[0-9a-f]{64}\.gz$")

    def test_download_path_reservation_handles_sanitized_collisions(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = DownloadManager.__new__(DownloadManager)
            manager.output_dir = directory
            manager.keep_original_names = False
            manager.queued = {}

            upper = manager._local_path_reserve("FILE.txt", "")
            upper_duplicate = manager._local_path_reserve("FILE.txt", "")
            lower = manager._local_path_reserve("file.txt", "")
            lower_duplicate = manager._local_path_reserve("file.txt", "")

            self.assertEqual(upper, os.path.join(directory, "FILE.txt"))
            self.assertIsNone(upper_duplicate)
            self.assertRegex(lower, rf"^{re.escape(directory)}/file~[0-9a-f]{{12}}\.txt$")
            self.assertIsNone(lower_duplicate)

    def test_multipart_filename_removes_header_unsafe_characters(self):
        escaped = NAME_POLICY.multipart_filename_escape('evil\r\nname"\\?.txt')

        self.assertEqual(escaped, "evil__name___.txt")
        self.assertNotIn("\r", escaped)
        self.assertNotIn("\n", escaped)

    def test_account_folder_decodes_only_url_components(self):
        account_folder = BaseAccountFolder.__new__(BaseAccountFolder)

        owner, segments = account_folder.split_url("https://chomikuj.pl/C%2B%2B/Folder+Name/file*2aname")

        self.assertEqual(owner, "C++")
        self.assertEqual(segments, ["Folder Name", "file*name"])
        self.assertFalse(account_folder.same_name("C++", "C  "))
        self.assertFalse(account_folder.same_name("file*2a", "file*"))

    def test_plain_upload_folder_keeps_literal_url_characters(self):
        manager = UploadManager.__new__(UploadManager)

        self.assertEqual(manager._split_remote_folder("C++/file*2a"), ["C++", "file*2a"])

    def test_upload_existing_keys_keep_literal_api_names(self):
        manager = UploadManager.__new__(UploadManager)
        manager.list_folder = lambda owner, folder_id: {
            "Files": [
                {"FileName": "C++", "FileType": "txt"},
                {"FileName": "file*2a", "FileType": ""},
            ]
        }

        keys = manager._remote_file_keys({"id": "1"}, "2")

        self.assertIn(NAME_POLICY.remote_name_key("C++.txt"), keys)
        self.assertIn(NAME_POLICY.remote_name_key("file*2a"), keys)
        self.assertNotIn(NAME_POLICY.remote_name_key("C  .txt"), keys)
        self.assertNotIn(NAME_POLICY.remote_name_key("file*"), keys)


if __name__ == "__main__":
    unittest.main()
