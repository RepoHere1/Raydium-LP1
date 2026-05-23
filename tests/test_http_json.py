"""Tests for gzip-tolerant JSON HTTP body decoding."""

import gzip
import json
import unittest

from raydium_lp1.http_json import json_loads_from_http_body, load_json_from_urlopen_response


class HttpJsonTests(unittest.TestCase):
    def test_plain_utf8_json(self):
        raw = b'{"ok":true}'
        self.assertEqual(json_loads_from_http_body(raw), {"ok": True})

    def test_gzip_magic_decompressed(self):
        payload = {"jsonrpc": "2.0", "result": "ok"}
        gz = gzip.compress(json.dumps(payload).encode("utf-8"))
        self.assertTrue(gz.startswith(b"\x1f\x8b"))
        self.assertEqual(json_loads_from_http_body(gz), payload)

    def test_contentencoding_gzip_header(self):
        payload = {"x": 1}
        gz = gzip.compress(json.dumps(payload).encode("utf-8"))
        out = json_loads_from_http_body(gz, content_encoding="gzip")
        self.assertEqual(out, payload)


class FakeResp:
    def __init__(self, raw: bytes, encoding: str | None = None):
        self._raw = raw
        self.headers = {}
        if encoding:
            self.headers["Content-Encoding"] = encoding

    def read(self) -> bytes:
        return self._raw


class UrlopenWrapperTests(unittest.TestCase):
    def test_load_json_from_urlopen_response_gzip(self):
        inner = {"a": 2}
        gz = gzip.compress(json.dumps(inner).encode("utf-8"))
        r = FakeResp(gz)
        self.assertEqual(load_json_from_urlopen_response(r), inner)


if __name__ == "__main__":
    unittest.main()
