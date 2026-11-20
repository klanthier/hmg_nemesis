#!/usr/bin/env python3
"""Independently verify a core update ZIP against the current build outputs.

This checks the deliberately narrow CI release format, not every package the
updater accepts. It does not import the packager or execute Android code. Run
after a clean build: byte equality cannot itself establish build freshness.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import stat
import struct
import sys
import zipfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# An intentional CA inventory change requires reviewing this release whitelist.
CA_NAMES = frozenset("""
01419da9.0 04f60c28.0 1e8e7201.0 252252d2.0 2add47b6.0 35105088.0
3afde786.0 5acf816d.0 6187b673.0 6b03dec0.0 7a7c655d.0 8794b4e3.0
9591a472.0 985c1f52.0 c44cc0c0.0 c90bc37d.0 cb1c3204.0 d41b5e2a.0
e071171e.0 ed39abd0.0 f013ecaf.0 fb5fa911.0 fd08c599.0
""".split())
PAYLOAD_PATHS = {
    "core/nemesis": "native/nemesis",
    "core/NEMESIS.apk": "manager/NEMESIS.apk",
    "core/install-recovery.sh": "boot/install-recovery.sh",
    "core/qb_hook.sh": "boot/qb_hook.sh",
    **{f"core/cacerts/{name}": f"boot/cacerts/{name}" for name in CA_NAMES},
}
MEMBERS = frozenset(PAYLOAD_PATHS) | {"NEMESIS.data", "MD5SUMS"}


class VerificationError(ValueError):
    """The update does not have the expected contents or structure."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def source_version(source_root: Path) -> str:
    header = (source_root / "native/nemesis.h").read_text(encoding="utf-8")
    versions = re.findall(r'^#define NEMESIS_VERSION "([0-9]+(?:\.[0-9]+)*)"$',
                          header, re.MULTILINE)
    require(len(versions) == 1, "expected one numeric NEMESIS_VERSION in native/nemesis.h")
    return versions[0]


def descriptor(data: bytes, expected: dict[str, str], label: str) -> None:
    """Accept the simple generated INI subset, rejecting ambiguous duplicate keys."""
    try:
        lines = data.decode("ascii").splitlines()
    except UnicodeError as exc:
        raise VerificationError(f"{label}: descriptor is not ASCII") from exc
    require(lines and lines[0] == "[nemesis]", f"{label}: missing [nemesis] section")
    values: dict[str, str] = {}
    for line in lines[1:]:
        match = re.fullmatch(r'([a-z][a-z-]*)=("[^"\\\x00-\x1f]*"|[^"\\\x00-\x20]*)', line)
        require(match is not None, f"{label}: invalid descriptor line")
        key, value = match.groups()
        require(key not in values, f"{label}: duplicate descriptor key {key}")
        values[key] = value[1:-1] if value.startswith('"') else value
    require(values == expected, f"{label}: descriptor fields differ from expected release/source version")


def regular_source(path: Path) -> bytes:
    require(not path.is_symlink() and path.is_file(), f"build input is not a regular file: {path}")
    return path.read_bytes()


def archive_members(archive_path: Path, sizes: dict[str, int]) -> dict[str, bytes]:
    """Reject alternate paths, links, hidden local entries and ZIP prefix/tails."""
    raw = archive_path.read_bytes()
    require(len(raw) >= 22, "truncated ZIP")
    end = struct.unpack("<4s4H2LH", raw[-22:])
    signature, disk, cd_disk, disk_count, count, cd_size, cd_start, comment = end
    require(signature == b"PK\x05\x06" and comment == 0,
            "ZIP has a comment, appended tail or invalid end record")
    require(disk == cd_disk == 0 and disk_count == count == len(MEMBERS),
            "ZIP must contain exactly the expected entries on one disk")
    require(cd_start + cd_size == len(raw) - 22, "ZIP has hidden data or an invalid directory range")
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            require(len(names) == len(set(names)), "duplicate ZIP entry")
            require(set(names) == MEMBERS and len(names) == count,
                    "ZIP whitelist mismatch (missing or unexpected entries/path aliases)")
            cursor = 0
            for info in sorted(infos, key=lambda item: item.header_offset):
                require(info.orig_filename == info.filename, "NUL/path alias in ZIP entry")
                mode = info.external_attr >> 16
                require(stat.S_IFMT(mode) in (0, stat.S_IFREG)
                        and not info.is_dir() and not (info.external_attr & 0x10),
                        f"ZIP entry must be a regular file: {info.filename}")
                require(info.flag_bits in (0, 0x800), "unsupported ZIP flags/encryption/data descriptor")
                require(info.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED),
                        "unsupported ZIP compression")
                require(not info.extra and not info.comment, "unexpected ZIP entry metadata")
                limit = sizes.get(info.filename, 16384)
                require(info.file_size <= limit, f"unexpected entry size: {info.filename}")
                require(info.header_offset == cursor and cursor + 30 <= cd_start,
                        "ZIP has hidden entries, a prefix or overlapping local records")
                fields = struct.unpack_from("<4s5H3L2H", raw, cursor)
                sig, _version, flags, method, _time, _date, crc, packed, size, nlen, xlen = fields
                require(sig == b"PK\x03\x04" and flags == info.flag_bits
                        and method == info.compress_type and crc == info.CRC
                        and packed == info.compress_size and size == info.file_size,
                        "ZIP local/central record mismatch")
                require(xlen == 0 and raw[cursor + 30:cursor + 30 + nlen] == info.filename.encode("ascii"),
                        "ZIP local name/metadata mismatch")
                cursor += 30 + nlen + packed
                require(cursor <= cd_start, "ZIP entry extends past payload area")
            require(cursor == cd_start, "ZIP has hidden entries or data before its directory")
            return {info.filename: archive.read(info) for info in infos}
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, UnicodeError, zlib.error) as exc:
        raise VerificationError(f"invalid ZIP: {exc}") from exc


def verify_built_update(archive_path: Path, descriptor_path: Path,
                        source_root: Path = ROOT) -> dict[str, int | str]:
    version = source_version(source_root)
    require(archive_path.name == f"nemesis-update-{version}.zip",
            "ZIP filename does not match source version")
    ca_dir = source_root / "boot/cacerts"
    actual_ca = {p.name for p in ca_dir.iterdir() if re.fullmatch(r"[0-9a-f]{8}\.\d+", p.name)}
    require(actual_ca == CA_NAMES, "source CA inventory differs from the 23 expected certificates")
    payloads = {name: regular_source(source_root / path) for name, path in PAYLOAD_PATHS.items()}
    require(payloads["core/nemesis"].startswith(b"\x7fELF"), "native build output is not an ELF")
    require(payloads["core/NEMESIS.apk"].startswith(b"PK\x03\x04"), "Manager build output is not an APK/ZIP")
    files = archive_members(archive_path, {name: len(data) for name, data in payloads.items()})
    for name, expected in payloads.items():
        require(files[name] == expected, f"embedded {name} differs from current build input")
    descriptor(files["NEMESIS.data"], {
        "version": "1.1", "id": "nemesis.core", "name": "NEMESIS", "type": "update",
        "package-version": version, "short-desc": f"NEMESIS {version} core update",
        "os": "any", "models": "any",
    }, "embedded NEMESIS.data")
    descriptor(regular_source(descriptor_path), {
        "version": "1.1", "type": "update", "path": archive_path.name,
    }, "external NEMESIS.data")
    try:
        lines = files["MD5SUMS"].decode("ascii").splitlines()
    except UnicodeError as exc:
        raise VerificationError("MD5SUMS is not ASCII") from exc
    seen: set[str] = set()
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{32})  ([A-Za-z0-9_./-]+)", line)
        require(match is not None, "invalid MD5SUMS line")
        digest, name = match.groups()
        require(name in MEMBERS - {"MD5SUMS"}, "MD5SUMS has an unexpected path/alias")
        require(name not in seen, "duplicate MD5SUMS path")
        seen.add(name)
        require(hashlib.md5(files[name]).hexdigest() == digest, f"MD5SUMS mismatch for {name}")
    require(seen == MEMBERS - {"MD5SUMS"}, "MD5SUMS does not cover every payload and descriptor")
    return {"version": version, "entries": len(files), "ca_files": len(CA_NAMES),
            "elf_bytes": len(payloads["core/nemesis"]), "apk_bytes": len(payloads["core/NEMESIS.apk"])}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--zip", type=Path, dest="archive")
    parser.add_argument("--descriptor", type=Path)
    args = parser.parse_args()
    try:
        archive = args.archive or args.source_root / "out" / f"nemesis-update-{source_version(args.source_root)}.zip"
        external = args.descriptor or archive.with_name("NEMESIS.data")
        result = verify_built_update(archive, external, args.source_root)
    except (OSError, UnicodeError, VerificationError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"OK: update {result['version']}; {result['entries']} exact ZIP entries; "
          f"ELF/APK/scripts/{result['ca_files']} CA files match build inputs; descriptors and MD5SUMS verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
