#!/usr/bin/env python3
"""Verify the built installer contains the current ELF and APK, without running it.

This deliberately does not import the installer builder. It checks the plain,
single-member TAR layout and the self-extractor's byte ranges independently.
Run after a clean build; byte equality alone cannot establish build freshness.
"""
from __future__ import annotations

import argparse
import re
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLOCK_SIZE = 512
RECORD_SIZE = 10240
PAYLOAD_ALIGNMENT = 4096
MARKER = b"\n# NEMESIS_PAYLOAD\n"
FIELDS = (b"ELF_SKIP", b"ELF_LEN", b"APK_SKIP", b"APK_LEN")


class VerificationError(ValueError):
    """The archive does not have the expected built-installer layout."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def rounded_up(value: int, unit: int) -> int:
    return ((value + unit - 1) // unit) * unit


def installer_member(archive: bytes) -> bytes:
    """Read one ordinary TAR member, rejecting extra members and hidden tails."""
    require(len(archive) >= BLOCK_SIZE, "truncated TAR header")
    try:
        member = tarfile.TarInfo.frombuf(archive[:BLOCK_SIZE], "utf-8", "strict")
    except (tarfile.HeaderError, UnicodeError, ValueError) as exc:
        raise VerificationError(f"invalid TAR header: {exc}") from exc
    require(member.name == "troubleShooter", "TAR must contain only troubleShooter")
    require(member.type in (tarfile.REGTYPE, tarfile.AREGTYPE),
            "troubleShooter must be an ordinary regular file")
    require(not member.linkname, "regular member must not have a link target")
    require(member.mode == 0o755, "troubleShooter must have mode 0755")
    require(member.uid == 0 and member.gid == 0, "troubleShooter must be owned by root")
    require(member.size > 0, "troubleShooter is empty")
    end = BLOCK_SIZE + member.size
    padded_end = rounded_up(end, BLOCK_SIZE)
    # Python tarfile's writer pads each archive to a 10 KiB record after its
    # two zero end blocks. Check the full file, including bytes TAR readers ignore.
    expected_size = rounded_up(padded_end + 2 * BLOCK_SIZE, RECORD_SIZE)
    require(len(archive) == expected_size, "TAR size is truncated or has an appended tail")
    require(end <= len(archive), "member extends past the TAR")
    require(not any(archive[end:]), "TAR has extra members or nonzero padding/trailing data")
    return archive[BLOCK_SIZE:end]


def payload_ranges(member: bytes) -> dict[bytes, int]:
    require(member.startswith(b"#!/system/bin/sh\n"), "unexpected installer shebang")
    marker = member.find(MARKER)
    require(marker >= 0, "missing payload marker")
    header_end = marker + len(MARKER)
    header = member[:header_end]
    require(b"\x00" not in header, "NUL byte in shell header")
    values: dict[bytes, int] = {}
    assignments = re.findall(rb"^(ELF_SKIP|ELF_LEN|APK_SKIP|APK_LEN)=([^\n]*)$",
                             header, re.MULTILINE)
    for key, raw in assignments:
        require(key not in values, f"duplicate {key.decode()} assignment")
        require(re.fullmatch(rb"[0-9]{1,20}", raw) is not None,
                f"invalid {key.decode()} assignment")
        values[key] = int(raw)
    require(all(key in values for key in FIELDS), "missing payload offset/length assignment")
    elf_start, elf_size = values[b"ELF_SKIP"], values[b"ELF_LEN"]
    apk_start, apk_size = values[b"APK_SKIP"], values[b"APK_LEN"]
    require(elf_size > 0 and apk_size > 0, "payload lengths must be positive")
    require(elf_start == rounded_up(header_end, PAYLOAD_ALIGNMENT),
            "ELF offset does not match the aligned shell header")
    require(header_end <= elf_start <= len(member), "ELF offset is out of bounds")
    require(member[header_end:elf_start] == b"\n" * (elf_start - header_end),
            "unexpected data between payload marker and ELF")
    require(apk_start == elf_start + elf_size, "ELF and APK ranges are not contiguous")
    require(apk_start <= len(member) and apk_start + apk_size == len(member),
            "payload lengths exceed the member or leave a hidden tail")
    return values


def verify_built_tar(archive_path: Path, alias_path: Path,
                     elf_path: Path, apk_path: Path) -> dict[str, int]:
    archive = archive_path.read_bytes()
    require(alias_path.read_bytes() == archive, "ota_package.tar alias differs from installer TAR")
    member = installer_member(archive)
    offsets = payload_ranges(member)
    elf_start, elf_size = offsets[b"ELF_SKIP"], offsets[b"ELF_LEN"]
    apk_start, apk_size = offsets[b"APK_SKIP"], offsets[b"APK_LEN"]
    elf, apk = elf_path.read_bytes(), apk_path.read_bytes()
    require(elf.startswith(b"\x7fELF"), "native build output is not an ELF")
    require(apk.startswith(b"PK\x03\x04"), "Manager build output is not an APK/ZIP")
    require(member[elf_start:elf_start + elf_size] == elf,
            "embedded ELF differs from current native/nemesis")
    require(member[apk_start:apk_start + apk_size] == apk,
            "embedded APK differs from current manager/NEMESIS.apk")
    return {"tar_bytes": len(archive), "header_bytes": elf_start,
            "elf_bytes": elf_size, "apk_bytes": apk_size}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tar", type=Path,
                        default=ROOT / "usb_bundle" / "ota_package_troubleshooter.tar")
    parser.add_argument("--alias", type=Path, default=ROOT / "usb_bundle" / "ota_package.tar")
    parser.add_argument("--elf", type=Path, default=ROOT / "native" / "nemesis")
    parser.add_argument("--apk", type=Path, default=ROOT / "manager" / "NEMESIS.apk")
    args = parser.parse_args()
    try:
        sizes = verify_built_tar(args.tar, args.alias, args.elf, args.apk)
    except (OSError, VerificationError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("OK: single troubleShooter member; embedded ELF/APK match build outputs; "
          "offsets, padding and alias verified "
          f"({sizes['elf_bytes']} ELF bytes, {sizes['apk_bytes']} APK bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
