#!/usr/bin/env python3
"""Verify the full USB output without extracting TARs or executing payloads.

The opaque stock files are compared to the supplied template, not certified as
safe. Expected stock order, duplicate names and symlinks are retained. A separate
canonical TAR is constructed from that inventory and the current build inputs;
whole-file equality checks every header, payload, padding byte and archive tail.
Only control-script assembly is shared with the reviewed builder. Run after a
clean build; this check alone cannot establish that build inputs are fresh.
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
USB_ROOT = ROOT.parent / "USB package path"
PREFIX = "./usb_news/../../.."
BRANDS = ("HMC", "KMC", "HMCSE", "KMCSE", "ECOHMC", "ECOHMCSE", "ECOKMC", "ECOKMCSE", "GENESIS")
REGIONS = ("USA", "CAN", "KOR", "MES", "BRA", "IDN", "IND", "JPN")
TAR_NAMES = frozenset(f"new_system_package_{brand}.{region}.{variant}.V099.999.999999.tar"
                      for brand in BRANDS for region in REGIONS for variant in ("0000", "1000"))
EXTRA_NAMES = frozenset(("NEW_TarList.txt_encrypted", "NEW_TarList.txt_encrypted.rsa"))
STOCK_FIELDS = ("size", "mode", "mtime", "uid", "gid", "uname", "gname", "type", "linkname")


class VerificationError(ValueError):
    """The USB output differs from the expected release inputs."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def regular_file(path: Path) -> bytes:
    require(path.is_file() and not path.is_symlink(), f"not a regular file: {path}")
    return path.read_bytes()


def load_control_script(source_root: Path) -> bytes:
    # Import assembles text only; the module's CLI main() and generated shell
    # are never executed. Payload, matrix and stock-copy helpers are not used.
    spec = importlib.util.spec_from_file_location("nemesis_usb_builder", USB_ROOT / "make_nemesis_installer.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.RECOVERY_PATH = source_root / "boot/install-recovery.sh"
    module.QB_HOOK_PATH = source_root / "boot/qb_hook.sh"
    module.CACERTS_DIR = source_root / "boot/cacerts"
    return module.build_control_script()


def expected_tar(template: Path, source_root: Path, usb_root: Path) -> tuple[bytes, int]:
    native = regular_file(source_root / "native/nemesis")
    manager = regular_file(source_root / "manager/NEMESIS.apk")
    installer = regular_file(usb_root / "installer/NEMESIS-Installer.apk")
    require(native.startswith(b"\x7fELF"), "native build input is not an ELF")
    require(manager.startswith(b"PK\x03\x04") and installer.startswith(b"PK\x03\x04"),
            "Manager/Installer build input is not an APK/ZIP")
    payloads = (
        (PREFIX + "/data/local/tmp/nemesis/nemesis.bin", native, 0o755),
        (PREFIX + "/data/local/tmp/nemesis/NEMESIS.apk", manager, 0o644),
        (PREFIX + "/data/app/NEMESIS-Installer.apk", installer, 0o644),
        (PREFIX + "/data/local/tmp/nemesis/nemesis", load_control_script(source_root), 0o755),
    )
    result = io.BytesIO()
    stock_count = 0
    with tarfile.open(template, "r:") as stock, tarfile.open(fileobj=result, mode="w", format=tarfile.GNU_FORMAT) as expected:
        for member in stock:
            # These are precisely the documented replacements, not a general
            # traversal sanitizer: the retained stock contains intentional links.
            if "/data/property/" in member.name or member.name == "troubleShooter" or member.name.startswith(PREFIX):
                continue
            copied = tarfile.TarInfo(member.name)
            for field in STOCK_FIELDS:
                setattr(copied, field, getattr(member, field))
            data = stock.extractfile(member) if member.isreg() else None
            expected.addfile(copied, data)
            stock_count += 1
        for name in ("./usb_news", PREFIX + "/data/local/tmp/nemesis"):
            directory = tarfile.TarInfo(name)
            directory.type, directory.mode = tarfile.DIRTYPE, 0o755
            directory.uid = directory.gid = 1000
            directory.uname = directory.gname = "system"
            expected.addfile(directory)
        for name, data, mode in payloads:
            member = tarfile.TarInfo(name)
            member.size, member.mode = len(data), mode
            member.uid = member.gid = 1000
            member.uname = member.gname = "system"
            expected.addfile(member, io.BytesIO(data))
    return result.getvalue(), stock_count


def verify_built_usb(template: Path, output: Path, source_root: Path = ROOT,
                     usb_root: Path = USB_ROOT) -> dict[str, int]:
    actual = {path.name for path in output.iterdir()}
    require(actual == TAR_NAMES | EXTRA_NAMES,
            "USB output inventory differs: missing or unexpected variant/extra file")
    extras = usb_root / "installer/stick_extras"
    require({p.name for p in extras.iterdir()} == EXTRA_NAMES, "tracked stick-extra inventory differs")
    for name in sorted(EXTRA_NAMES):
        require(regular_file(output / name) == regular_file(extras / name), f"stick extra differs: {name}")
    canonical, stock_count = expected_tar(template, source_root, usb_root)
    for name in sorted(TAR_NAMES):
        require(regular_file(output / name) == canonical,
                f"TAR differs from template/build inputs or expected headers/padding: {name}")
    return {"variants": len(TAR_NAMES), "extras": len(EXTRA_NAMES),
            "stock_members": stock_count, "tar_bytes": len(canonical)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=USB_ROOT / "out")
    args = parser.parse_args()
    try:
        result = verify_built_usb(args.template, args.out)
    except (OSError, ValueError, tarfile.TarError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"OK: {result['variants']} exact USB TAR variants and {result['extras']} stick extras; "
          f"{result['stock_members']} stock members per TAR match template; "
          "ELF, both APKs, control script, metadata and padding match build inputs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
