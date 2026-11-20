#!/usr/bin/env python3
"""Check the USB-only first-party source and APKs without running Android code.

This is a regression guard, not a proof about OEM firmware, the inherited Navi
libraries, root scripts, or packages that the user installs later.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import struct
import sys
import xml.etree.ElementTree as ET
import zipfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID_NS = "http://schemas.android.com/apk/res/android"
INTERNET = "android.permission.INTERNET"
NETWORK_TYPES = (
    "Ljava/net/", "Ljavax/net/", "Lorg/apache/http/", "Lokhttp3/",
    "Lcom/squareup/okhttp/", "Landroid/net/ConnectivityManager;",
    "Landroid/net/Network;", "Landroid/app/DownloadManager",
    "Landroid/webkit/WebView", "Ldalvik/system/DexClassLoader;",
    "Ldalvik/system/InMemoryDexClassLoader;",
)
ENDPOINT = re.compile(r"https?://|\bxwtk\.cloud\b", re.I)
JAVA_NETWORK = re.compile(
    r"\b(?:java\.net\.|javax\.net\.|org\.apache\.http\.|okhttp3\.|"
    r"com\.squareup\.okhttp\.|android\.net\.(?:ConnectivityManager|Network)\b|"
    r"android\.webkit\.WebView\b|android\.app\.DownloadManager\b)"
)
NATIVE_NETWORK = re.compile(
    r"\bAF_(?:INET6?|PACKET)\b|\b(?:getaddrinfo|gethostbyname|inet_pton|"
    r"curl|wget|netcat)\b|/dev/(?:tcp|udp)/"
)


class VerificationError(ValueError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise VerificationError(message)


def table(data: bytes, offset: int, count: int, width: int) -> None:
    require(0 <= offset <= len(data) and 0 <= count <= (len(data) - offset) // width,
            "truncated or invalid binary table")


def uleb(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    for shift in range(0, 35, 7):
        require(offset < len(data), "truncated DEX string length")
        b = data[offset]
        offset += 1
        value |= (b & 127) << shift
        if not b & 128:
            return value, offset
    raise VerificationError("invalid DEX string length")


def dex_string(data: bytes, offset: int) -> str:
    count, offset = uleb(data, offset)
    units = []
    while True:
        require(offset < len(data), "unterminated DEX string")
        b = data[offset]
        offset += 1
        if b == 0:
            break
        if b < 128:
            units.append(b)
        elif b & 0xE0 == 0xC0:
            require(offset < len(data) and data[offset] & 0xC0 == 0x80,
                    "invalid DEX MUTF-8")
            value = ((b & 31) << 6) | (data[offset] & 63)
            require(value == 0 or value >= 128, "overlong DEX MUTF-8")
            units.append(value)
            offset += 1
        elif b & 0xF0 == 0xE0:
            require(offset + 1 < len(data) and all(v & 0xC0 == 0x80 for v in data[offset:offset + 2]),
                    "invalid DEX MUTF-8")
            value = ((b & 15) << 12) | ((data[offset] & 63) << 6) | (data[offset + 1] & 63)
            require(value >= 2048, "overlong DEX MUTF-8")
            units.append(value)
            offset += 2
        else:
            raise VerificationError("invalid DEX MUTF-8")
    require(len(units) == count, "DEX string length mismatch")
    return b"".join(struct.pack("<H", v) for v in units).decode("utf-16le", "surrogatepass")


def dex_inventory(data: bytes) -> tuple[list[str], list[str], list[str]]:
    require(len(data) >= 112 and data[:8] == b"dex\n035\0", "expected KitKat DEX 035")
    require(struct.unpack_from("<III", data, 32) == (len(data), 112, 0x12345678),
            "invalid DEX header")
    require(hashlib.sha1(data[32:]).digest() == data[12:32], "DEX SHA-1 mismatch")
    require(zlib.adler32(data[12:]) & 0xFFFFFFFF == struct.unpack_from("<I", data, 8)[0],
            "DEX Adler-32 mismatch")
    string_count, string_offset = struct.unpack_from("<II", data, 56)
    table(data, string_offset, string_count, 4)
    strings = [dex_string(data, struct.unpack_from("<I", data, string_offset + i * 4)[0])
               for i in range(string_count)]
    type_count, type_offset = struct.unpack_from("<II", data, 64)
    table(data, type_offset, type_count, 4)
    types = []
    for i in range(type_count):
        index = struct.unpack_from("<I", data, type_offset + i * 4)[0]
        require(index < len(strings), "invalid DEX type string")
        types.append(strings[index])
    method_count, method_offset = struct.unpack_from("<II", data, 88)
    table(data, method_offset, method_count, 8)
    methods = []
    for i in range(method_count):
        owner, _, name = struct.unpack_from("<HHI", data, method_offset + i * 8)
        require(owner < len(types) and name < len(strings), "invalid DEX method reference")
        methods.append(types[owner] + "->" + strings[name])
    return strings, types, methods


def check_dex(data: bytes) -> dict[str, int]:
    strings, types, methods = dex_inventory(data)
    for name in types:
        require(not name.lstrip("[").startswith(NETWORK_TYPES), "network/dynamic-code type in DEX: " + name)
        require(name != "Lcom/nemesis/manager/Portal;", "Portal client remains in DEX")
    for value in strings:
        require(not ENDPOINT.search(value), "network endpoint in DEX: " + value[:150])
        require(not JAVA_NETWORK.search(value), "network class name in DEX string: " + value[:150])
    for method in methods:
        require(method not in ("Ljava/lang/System;->load", "Ljava/lang/System;->loadLibrary",
                               "Ljava/lang/Runtime;->load", "Ljava/lang/Runtime;->loadLibrary"),
                "native-code loader in DEX: " + method)
    return {"strings": len(strings), "types": len(types), "methods": len(methods)}


def pool_strings(chunk: bytes) -> list[str]:
    require(len(chunk) >= 28, "short Android string pool")
    count, _, flags, start, _ = struct.unpack_from("<IIIII", chunk, 8)
    header = struct.unpack_from("<H", chunk, 2)[0]
    table(chunk, header, count, 4)

    def length_at(offset: int, width: int) -> tuple[int, int]:
        table(chunk, offset, 1, width)
        value = int.from_bytes(chunk[offset:offset + width], "little")
        offset += width
        flag = 1 << (width * 8 - 1)
        if value & flag:
            table(chunk, offset, 1, width)
            value = ((value & (flag - 1)) << (width * 8)) | int.from_bytes(chunk[offset:offset + width], "little")
            offset += width
        return value, offset

    strings = []
    for i in range(count):
        offset = start + struct.unpack_from("<I", chunk, header + 4 * i)[0]
        utf16_count, offset = length_at(offset, 1 if flags & 256 else 2)
        if flags & 256:
            size, offset = length_at(offset, 1)
            table(chunk, offset, size + 1, 1)
            require(chunk[offset + size] == 0, "unterminated Android UTF-8 string")
            value = chunk[offset:offset + size].decode("utf-8")
        else:
            size = utf16_count * 2
            table(chunk, offset, size + 2, 1)
            require(chunk[offset + size:offset + size + 2] == b"\0\0", "unterminated Android UTF-16 string")
            value = chunk[offset:offset + size].decode("utf-16le")
        require(len(value.encode("utf-16le")) // 2 == utf16_count, "Android string length mismatch")
        strings.append(value)
    return strings


def check_manifest(data: bytes) -> list[str]:
    require(len(data) >= 8, "missing binary AndroidManifest")
    kind, header, total = struct.unpack_from("<HHI", data)
    require(kind == 3 and header == 8 and total == len(data), "invalid binary AndroidManifest header")
    offset = header
    strings = None
    permissions = []
    saw_manifest = False
    while offset < len(data):
        table(data, offset, 1, 8)
        kind, header, size = struct.unpack_from("<HHI", data, offset)
        require(8 <= header <= size <= len(data) - offset, "invalid AndroidManifest chunk")
        chunk = data[offset:offset + size]
        if kind == 1:
            require(strings is None, "duplicate AndroidManifest string pool")
            strings = pool_strings(chunk)
        elif kind == 0x102:
            require(strings is not None and header == 16 and size >= 36, "invalid AndroidManifest element")

            def text(index: int) -> str:
                require(index < len(strings), "invalid AndroidManifest string index")
                return strings[index]

            name = text(struct.unpack_from("<I", chunk, 20)[0])
            attr_start, attr_size, count = struct.unpack_from("<HHH", chunk, 24)
            require(attr_size >= 20, "invalid AndroidManifest attribute size")
            table(chunk, 16 + attr_start, count, attr_size)
            attrs = {}
            for i in range(count):
                a = 16 + attr_start + i * attr_size
                namespace, key, raw = struct.unpack_from("<III", chunk, a)
                typed_size, _, dtype, value = struct.unpack_from("<HBBI", chunk, a + 12)
                require(typed_size == 8, "invalid AndroidManifest typed value")
                attr_key = ("" if namespace == 0xFFFFFFFF else text(namespace), text(key))
                require(attr_key not in attrs, "duplicate AndroidManifest attribute")
                attrs[attr_key] = text(raw) if raw != 0xFFFFFFFF else text(value) if dtype == 3 else None
            if name == "manifest":
                saw_manifest = True
                require((ANDROID_NS, "sharedUserId") not in attrs, "sharedUserId bypasses APK permission isolation")
            if name.startswith("uses-permission"):
                permission = attrs.get((ANDROID_NS, "name"))
                require(permission is not None, "permission without a string name")
                permissions.append(permission)
        offset += size
    require(saw_manifest, "AndroidManifest has no manifest element")
    require(INTERNET not in permissions, "APK requests INTERNET")
    return permissions


def verify_apk(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), "duplicate APK entries")
        require(archive.testzip() is None, "bad APK ZIP CRC")
        require([n for n in names if n.endswith(".dex")] == ["classes.dex"], "expected exactly classes.dex")
        require(not any(n.startswith("lib/") for n in names), "unexpected native code in APK")
        for name in names:
            if name == "classes.dex" or name.endswith("/"):
                continue
            with archive.open(name) as payload:
                magic = payload.read(8)
            require(not magic.startswith((b"\x7fELF", b"dex\n", b"PK\x03\x04")),
                    "unexpected executable/archive APK payload: " + name)
        permissions = check_manifest(archive.read("AndroidManifest.xml"))
        inventory = check_dex(archive.read("classes.dex"))
    return {"apk": str(path), "permissions": permissions, **inventory}


def verify_source(root: Path) -> int:
    source = root / "NEMESIS Source"
    count = 0
    for manifest in (source / "manager/AndroidManifest.xml", root / "USB package path/installer/AndroidManifest.xml"):
        tree = ET.parse(manifest).getroot()
        require("{" + ANDROID_NS + "}sharedUserId" not in tree.attrib, "source manifest has sharedUserId")
        require(not any(e.attrib.get("{" + ANDROID_NS + "}name") == INTERNET
                        for e in tree.iter() if e.tag.startswith("uses-permission")),
                "source manifest requests INTERNET")
    roots = (source / "manager/src", root / "USB package path/installer/src", source / "native", source / "boot")
    files = [p for directory in roots for p in directory.rglob("*") if p.suffix in (".java", ".c", ".h", ".sh")]
    files += [root / "USB package path/make_nemesis_installer.py", root / "USB OTA troubleShooter path/make_troubleshooter_tar.py"]
    for path in files:
        text = path.read_text()
        require(path.name != "Portal.java", "Portal client source remains")
        require(not ENDPOINT.search(text), "network endpoint in runtime source: " + str(path.relative_to(root)))
        require(not JAVA_NETWORK.search(text), "network API in runtime source: " + str(path.relative_to(root)))
        if path.suffix != ".java":
            require(not NATIVE_NETWORK.search(text), "outbound network primitive in runtime source: " + str(path.relative_to(root)))
        count += 1
    require(count > 30, "runtime source inventory unexpectedly small")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--source-only", action="store_true")
    parser.add_argument("--manager-apk", type=Path)
    parser.add_argument("--installer-apk", type=Path)
    args = parser.parse_args()
    try:
        count = verify_source(args.source_root)
        if not args.source_only:
            for path in (args.manager_apk or args.source_root / "NEMESIS Source/manager/NEMESIS.apk",
                         args.installer_apk or args.source_root / "USB package path/installer/NEMESIS-Installer.apk"):
                info = verify_apk(path)
                print(f"OK: {path.name}: no INTERNET/shared UID, network client references, endpoints or extra executable APK payloads; {info['methods']} DEX method references inspected")
        print(f"OK: USB-only runtime source guard ({count} files); inherited Navi binaries, vehicle firmware and later mods are outside this check")
    except (VerificationError, OSError, UnicodeError, ET.ParseError, zipfile.BadZipFile, KeyError, struct.error) as error:
        parser.exit(1, f"FAIL: {error}\n")


if __name__ == "__main__":
    main()
