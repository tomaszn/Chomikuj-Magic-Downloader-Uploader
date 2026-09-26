#!/usr/bin/env python3

import hashlib
import os
import re
import unicodedata
from urllib.parse import quote_plus, unquote_plus


class NamePolicy:
    """Separates Chomikuj URL names, API names, local paths and upload headers."""

    LOCAL_COMPONENT_ESCAPE = "~"
    LOCAL_COMPONENT_FORBIDDEN_CHARS = set('<>:"/\\|?*')
    LOCAL_COMPONENT_RESERVED_NAMES = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
        "COM¹",
        "COM²",
        "COM³",
        "LPT¹",
        "LPT²",
        "LPT³",
    }
    MULTIPART_FILENAME_FORBIDDEN_CHARS = set('?*:<>/"\\')
    URL_ESCAPE_RE = re.compile(r"%([0-9A-Fa-f]{2})")
    URL_CHOMIK_ESCAPE_RE = re.compile(r"\*([0-9A-Fa-f]{2})")

    def url_component_decode(self, value):
        encoded = self.URL_CHOMIK_ESCAPE_RE.sub(r"%\1", str(value or ""))
        return unquote_plus(encoded)

    def url_component_encode(self, value):
        encoded = quote_plus(str(value or ""), safe="()")
        return self.URL_ESCAPE_RE.sub(lambda match: f"*{match.group(1).lower()}", encoded)

    def local_component_sanitize(self, value):
        text = str(value or "")
        sanitized = []
        last_index = len(text) - 1
        for index, char in enumerate(text):
            if self._local_char_safe(char, index, last_index):
                sanitized.append(char)
            else:
                sanitized.append(self._local_char_encode(char))
        result = "".join(sanitized) or "_"

        if self._local_name_reserved(result):
            result = self._local_char_encode(result[0]) + result[1:]
        return result

    def local_path_key(self, path):
        normalized = os.path.abspath(os.path.normpath(path))
        return unicodedata.normalize("NFC", normalized).casefold()

    def local_path_candidates(self, path, identity):
        yield path
        for digest_length in (12, 64):
            yield self._local_path_disambiguate(path, identity, digest_length)

    def _local_path_disambiguate(self, path, identity, digest_length):
        directory, filename = os.path.split(path)
        stem, extension = os.path.splitext(filename)
        digest = hashlib.sha256(str(identity).encode("utf-8", errors="surrogatepass")).hexdigest()[:digest_length]
        return os.path.join(directory, f"{stem}~{digest}{extension}")

    def remote_name_key(self, value):
        return unicodedata.normalize("NFC", str(value or "")).casefold()

    def multipart_filename_escape(self, value):
        return "".join(
            "_" if char in self.MULTIPART_FILENAME_FORBIDDEN_CHARS or not char.isprintable() else char
            for char in str(value or "")
        )

    def _local_char_safe(self, char, index, last_index):
        if char == self.LOCAL_COMPONENT_ESCAPE or char in self.LOCAL_COMPONENT_FORBIDDEN_CHARS:
            return False
        if not char.isprintable():
            return False
        return char not in " ." or 0 < index < last_index

    def _local_char_encode(self, char):
        return "".join(
            f"{self.LOCAL_COMPONENT_ESCAPE}{byte:02x}"
            for byte in char.encode("utf-8", errors="surrogatepass")
        )

    def _local_name_reserved(self, value):
        stem = value.split(".", 1)[0]
        return stem.upper() in self.LOCAL_COMPONENT_RESERVED_NAMES


NAME_POLICY = NamePolicy()
