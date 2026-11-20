#!/usr/bin/env python3
"""Verify and stream the pinned upstream USB template; never unpack its tar."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE_SHA256 = "aeccf9050f36817592cc91b20e6e946f462cf2faf99d2cc35c2666fe655d5f54"
TEMPLATE_SHA256 = "c39a62d61bc74c11f850ed2763a74a355608914c69e90ff691a99ac4fa22ee17"
TEMPLATE_MEMBER = "new_system_package_HMC.CAN.0000.V099.999.999999.tar"
BRANDS = ("HMC", "KMC", "HMCSE", "KMCSE", "ECOHMC", "ECOHMCSE", "ECOKMC", "ECOKMCSE", "GENESIS")
REGIONS = ("USA", "CAN", "KOR", "MES", "BRA", "IDN", "IND", "JPN")
EXTRAS = ("NEW_TarList.txt_encrypted", "NEW_TarList.txt_encrypted.rsa")
EXPECTED_MEMBERS = {
    f"new_system_package_{brand}.{region}.{variant}.V099.999.999999.tar"
    for brand in BRANDS for region in REGIONS for variant in ("0000", "1000")
} | set(EXTRAS)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(args: list[str]) -> bytes:
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise ValueError(f"{Path(args[0]).name} failed: " + result.stderr.decode("utf-8", "replace").strip())
    return result.stdout


class ArchiveReader:
    def __init__(self, archive: Path, allow_bsdtar: bool):
        self.archive = str(archive.resolve())
        self.tool = shutil.which("7z") or shutil.which("7zz")
        self.bsdtar = False
        if not self.tool and allow_bsdtar:
            self.tool = shutil.which("bsdtar")
            self.bsdtar = True
        if not self.tool:
            raise ValueError("7z is required (p7zip-full on Ubuntu); --allow-bsdtar enables a local validation fallback")

    def members(self) -> list[str]:
        if self.bsdtar:
            return run([self.tool, "-tf", self.archive]).decode("utf-8").splitlines()
        listing = run([self.tool, "l", "-slt", "-ba", "--", self.archive]).decode("utf-8")
        return [line[len("Path = "):] for line in listing.splitlines() if line.startswith("Path = ")]

    def read(self, member: str) -> bytes:
        if member not in EXPECTED_MEMBERS:
            raise ValueError(f"member is not allowlisted: {member}")
        if self.bsdtar:
            return run([self.tool, "-xOf", self.archive, member])
        return run([self.tool, "e", "-so", "--", self.archive, member])


def inventory(template: bytes) -> tuple[list[dict], list[dict]]:
    """Mirror stock_members' retention rule without importing/executing the builder."""
    preserved, opaque = [], []
    targets = {}
    with tarfile.open(fileobj=io.BytesIO(template), mode="r:") as archive:
        for index, member in enumerate(archive):
            name = member.name
            if "/data/property/" in name or name == "troubleShooter" or name.startswith("./usb_news/../../.."):
                continue
            kind = "regular" if member.isreg() else "symlink" if member.issym() else "directory" if member.isdir() else "other"
            item = {
                "index": index, "name": name, "type": kind, "size": member.size,
                "mode": oct(member.mode), "uid": member.uid, "gid": member.gid,
                "link_target": member.linkname,
            }
            if member.issym() or member.islnk():
                targets[name] = member.linkname
            if member.isreg():
                data = archive.extractfile(member).read()
                item["sha256"] = sha256(data)
                item["resolved_target"] = targets.get(name, name)
                if len(data) < 256:
                    item["text"] = data.decode("utf-8", "replace")
                if item["resolved_target"].endswith(".so"):
                    item["format"] = "ELF" if data.startswith(b"\x7fELF") else "opaque binary"
                    opaque.append(dict(item))
            preserved.append(item)
    return preserved, opaque


def prepare(archive: Path, output_dir: Path, allow_bsdtar: bool = False) -> dict:
    archive_hash = sha256(archive.read_bytes())
    if archive_hash != ARCHIVE_SHA256:
        raise ValueError(f"upstream archive SHA-256 mismatch: {archive_hash}")
    reader = ArchiveReader(archive, allow_bsdtar)
    members = reader.members()
    if len(members) != len(set(members)) or set(members) != EXPECTED_MEMBERS:
        raise ValueError("archive inventory differs from the required 144 tar files and 2 extras")
    template = reader.read(TEMPLATE_MEMBER)
    if sha256(template) != TEMPLATE_SHA256:
        raise ValueError("selected template SHA-256 mismatch")
    extras = {}
    for name in EXTRAS:
        tracked = Path("USB package path/installer/stick_extras") / name
        data = reader.read(name)
        if data != (ROOT / tracked).read_bytes():
            raise ValueError(f"release extra differs from tracked source input: {name}")
        extras[name] = {"sha256": sha256(data), "tracked_path": tracked.as_posix(), "match": True}
    preserved, opaque = inventory(template)
    info = {
        "schema_version": 1,
        "upstream_release": "https://github.com/xwtk/hmg_nemesis/releases/tag/v1.16.9",
        "archive": {"name": "nemesis-usb-update-package.7z", "sha256": archive_hash,
                    "url": "https://github.com/xwtk/hmg_nemesis/releases/download/v1.16.9/nemesis-usb-update-package.7z"},
        "template": {"file": "template.tar", "archive_member": TEMPLATE_MEMBER, "sha256": TEMPLATE_SHA256},
        "archive_members": sorted(members),
        "extras": extras,
        "preserved_stock_members": preserved,
        "opaque_payloads": opaque,
        "trust_notice": (
            "Pinned upstream release input, not wholly rebuilt from source. Retained navigation "
            "libraries and signed/encrypted TarList files are upstream binary inputs. Hash checks "
            "establish exact input identity, not independent publisher authenticity or safety. "
            "The TarList RSA signature is not verified here. No inner tar was extracted or executed. "
            "splash.png is absent from this pinned release and is not synthesized."
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "template.tar").write_bytes(template)
    (output_dir / "usb-template-info.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    return info


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--allow-bsdtar", action="store_true", help="allow read-only bsdtar fallback for local validation")
    args = parser.parse_args()
    try:
        info = prepare(args.archive, args.output_dir, args.allow_bsdtar)
    except (OSError, ValueError, tarfile.TarError) as error:
        raise SystemExit(str(error)) from error
    print(f"Verified {len(info['archive_members'])} release members; prepared {args.output_dir / 'template.tar'}")


if __name__ == "__main__":
    main()
