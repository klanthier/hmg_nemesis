#!/usr/bin/env python3
"""Tamper checks for compiled offline APK permissions and network references."""
from __future__ import annotations

import hashlib
import io
import struct
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path

from check_offline_build import VerificationError, check_dex, check_manifest, verify_apk

NS = "http://schemas.android.com/apk/res/android"


def dex_fixture(*, owner: str = "Lcom/nemesis/manager/MainActivity;", method: str = "onCreate",
                literal: str = "USB packages") -> bytes:
    # A small DEX table fixture, sufficient for inventory parsing. No guest code.
    strings = [owner, method, literal]
    string_offset = 112
    type_offset = string_offset + 4 * len(strings)
    method_offset = type_offset + 4
    data_offset = method_offset + 8
    data = bytearray(data_offset)
    data[:8] = b"dex\n035\0"
    struct.pack_into("<II", data, 36, 112, 0x12345678)
    struct.pack_into("<II", data, 56, len(strings), string_offset)
    struct.pack_into("<II", data, 64, 1, type_offset)
    struct.pack_into("<II", data, 88, 1, method_offset)
    struct.pack_into("<I", data, type_offset, 0)
    struct.pack_into("<HHI", data, method_offset, 0, 0, 1)
    for i, text in enumerate(strings):
        struct.pack_into("<I", data, string_offset + i * 4, len(data))
        raw = text.encode("utf-8")
        assert len(raw) < 128 and text.isascii()
        data.extend(bytes([len(text)]) + raw + b"\0")
    struct.pack_into("<I", data, 32, len(data))
    struct.pack_into("<II", data, 104, len(data) - data_offset, data_offset)
    data[12:32] = hashlib.sha1(data[32:]).digest()
    struct.pack_into("<I", data, 8, zlib.adler32(data[12:]) & 0xFFFFFFFF)
    return bytes(data)


def manifest_fixture(permission: str = "android.permission.WRITE_EXTERNAL_STORAGE", *,
                     permission_tag: str = "uses-permission", shared_uid: bool = False,
                     utf8: bool = True, typed_only: bool = False) -> bytes:
    strings = ["manifest", permission_tag, NS, "name", permission,
               "sharedUserId", "android.uid.system"]
    encoded = []
    for text in strings:
        if utf8:
            raw = text.encode("utf-8")
            assert len(raw) < 128
            encoded.append(bytes([len(text), len(raw)]) + raw + b"\0")
        else:
            encoded.append(struct.pack("<H", len(text)) + text.encode("utf-16le") + b"\0\0")
    start = 28 + 4 * len(strings)
    offsets = []
    blob = bytearray()
    for value in encoded:
        offsets.append(len(blob))
        blob.extend(value)
    while (start + len(blob)) % 4:
        blob.append(0)
    pool = (struct.pack("<HHIIIIII", 1, 28, start + len(blob), len(strings), 0,
                        256 if utf8 else 0, start, 0)
            + b"".join(struct.pack("<I", value) for value in offsets) + blob)

    def node(name: int, attrs: list[tuple[int, int]]) -> bytes:
        body = struct.pack("<IIHHHHHH", 0xFFFFFFFF, name, 20, 20, len(attrs), 0, 0, 0)
        for key, value in attrs:
            body += struct.pack("<IIIHBBI", 2, key, 0xFFFFFFFF if typed_only else value, 8, 0, 3, value)
        return struct.pack("<HHIII", 0x102, 16, 16 + len(body), 1, 0xFFFFFFFF) + body

    def end(name: int) -> bytes:
        return struct.pack("<HHIIIII", 0x103, 16, 24, 1, 0xFFFFFFFF, 0xFFFFFFFF, name)

    body = pool + node(0, [(5, 6)] if shared_uid else []) + node(1, [(3, 4)]) + end(1) + end(0)
    return struct.pack("<HHI", 3, 8, 8 + len(body)) + body


class OfflineBuildTests(unittest.TestCase):
    def assert_rejected(self, expression: str, fn, *args) -> None:
        with self.assertRaisesRegex(VerificationError, expression):
            fn(*args)

    def test_offline_manifest_both_string_encodings_and_typed_attributes(self) -> None:
        for utf8 in (True, False):
            for typed in (True, False):
                with self.subTest(utf8=utf8, typed_only=typed):
                    self.assertEqual(check_manifest(manifest_fixture(utf8=utf8, typed_only=typed)),
                                     ["android.permission.WRITE_EXTERNAL_STORAGE"])

    def test_internet_permission_rejected_in_all_supported_permission_elements(self) -> None:
        for tag in ("uses-permission", "uses-permission-sdk-23", "uses-permission-sdk-m"):
            with self.subTest(tag=tag):
                self.assert_rejected("requests INTERNET", check_manifest,
                                     manifest_fixture("android.permission.INTERNET", permission_tag=tag))

    def test_shared_uid_rejected_even_without_internet_permission(self) -> None:
        self.assert_rejected("sharedUserId", check_manifest, manifest_fixture(shared_uid=True))

    def test_malformed_manifest_cannot_silently_skip_permission_check(self) -> None:
        good = manifest_fixture()
        for bad in (b"", good[:-1], good[:8], good.replace(b"\x02\x01\x10\x00", b"\x02\x01\x00\x00", 1)):
            with self.subTest(data=bad[:8]):
                self.assert_rejected("manifest|Manifest|chunk", check_manifest, bad)

    def test_offline_dex_has_inspected_type_and_method_tables(self) -> None:
        self.assertEqual(check_dex(dex_fixture()), {"strings": 3, "types": 1, "methods": 1})

    def test_network_classes_rejected_without_literal_url(self) -> None:
        for owner in ("Ljava/net/URL;", "Ljava/net/Socket;", "Ljavax/net/ssl/SSLSocket;",
                      "Landroid/net/ConnectivityManager;", "Landroid/net/Network;",
                      "Landroid/webkit/WebView;", "Lokhttp3/OkHttpClient;",
                      "[Ljava/net/URL;", "Ldalvik/system/DexClassLoader;"):
            with self.subTest(owner=owner):
                self.assert_rejected("network/dynamic-code type", check_dex, dex_fixture(owner=owner))

    def test_endpoint_and_reflective_network_names_rejected_without_type_reference(self) -> None:
        for literal in ("https://portal.xwtk.cloud/nemesis/v1", "PORTAL.XWTK.CLOUD",
                        "http://example.com/upload", "java.net.URL", "javax.net.ssl.SSLSocket"):
            with self.subTest(literal=literal):
                self.assert_rejected("endpoint|class name", check_dex, dex_fixture(literal=literal))

    def test_portal_class_rejected_even_if_methods_or_urls_removed(self) -> None:
        self.assert_rejected("Portal client", check_dex, dex_fixture(owner="Lcom/nemesis/manager/Portal;"))

    def test_native_loader_method_rejected(self) -> None:
        self.assert_rejected("native-code loader", check_dex,
                             dex_fixture(owner="Ljava/lang/System;", method="loadLibrary"))

    def test_corrupt_dex_rejected(self) -> None:
        data = dex_fixture()
        self.assert_rejected("SHA-1 mismatch", check_dex, data[:-1] + b"x")
        self.assert_rejected("DEX 035", check_dex, b"dex\n039\0" + data[8:])

    def test_apk_checks_actual_manifest_and_dex_and_rejects_hidden_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            apk = Path(temporary) / "Manager.apk"

            def write(extra: tuple[str, bytes] | None = None, *, online: bool = False) -> None:
                with zipfile.ZipFile(apk, "w") as out:
                    out.writestr("AndroidManifest.xml", manifest_fixture(
                        "android.permission.INTERNET" if online else "android.permission.WRITE_EXTERNAL_STORAGE"))
                    out.writestr("classes.dex", dex_fixture())
                    if extra:
                        out.writestr(*extra)

            write()
            self.assertEqual(verify_apk(apk)["types"], 1)
            write(online=True)
            self.assert_rejected("requests INTERNET", verify_apk, apk)
            for extra, expression in ((('classes2.dex', dex_fixture()), 'exactly classes.dex'),
                                      (('lib/armeabi-v7a/client.so', b'\x7fELF'), 'native code'),
                                      (('assets/config.bin', b'\x7fELFhidden'), 'executable/archive'),
                                      (('assets/hidden.bin', b'PK\x03\x04hidden'), 'executable/archive')):
                with self.subTest(extra=extra[0]):
                    write(extra)
                    self.assert_rejected(expression, verify_apk, apk)


if __name__ == "__main__":
    unittest.main()
