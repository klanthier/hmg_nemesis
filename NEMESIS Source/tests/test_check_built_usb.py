#!/usr/bin/env python3
"""Focused full-USB tamper tests with synthetic stock and build inputs."""
from __future__ import annotations

import io
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from check_built_usb import EXTRA_NAMES, PREFIX, TAR_NAMES, VerificationError, verify_built_usb


class BuiltUsbTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="nemesis usb test ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source, self.usb, self.output = (self.root / name for name in ("source", "usb", "output"))
        self.output.mkdir()
        self.template = self.root / "template.tar"
        self.native, self.manager, self.installer = b"\x7fELFfresh native", b"PK\x03\x04fresh manager", b"PK\x03\x04fresh installer"
        self.control = b"#!/system/bin/sh\n# synthetic control script\n"
        for path, data in ((self.source / "native/nemesis", self.native),
                           (self.source / "manager/NEMESIS.apk", self.manager),
                           (self.usb / "installer/NEMESIS-Installer.apk", self.installer)):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        extras = self.usb / "installer/stick_extras"
        extras.mkdir()
        for name in EXTRA_NAMES:
            data = ("tracked extra " + name).encode()
            (extras / name).write_bytes(data)
            (self.output / name).write_bytes(data)
        self.stock = []
        for kind, name, data in ((tarfile.SYMTYPE, "NEgl1.txt", b""),
                                 (tarfile.REGTYPE, "NEgl1.txt", b"opaque stock payload"),
                                 (tarfile.DIRTYPE, "./usb_news", b"")):
            member = tarfile.TarInfo(name)
            member.type, member.mode, member.mtime = kind, 0o755, 123456789
            member.uid = member.gid = 1000
            member.uname = member.gname = "system"
            if kind == tarfile.SYMTYPE:
                member.linkname = "//..//..//navi/navi_backup/BIN/G40/Navi_Version.txt"
            member.size = len(data)
            self.stock.append((member, data))
        with tarfile.open(self.template, "w", format=tarfile.GNU_FORMAT) as archive:
            for member, data in self.stock:
                archive.addfile(member, io.BytesIO(data) if member.isreg() else None)
            # All three replacement rules must apply to reused templates.
            for name in ("./usb_news/../../../data/property/persist.sys.usb.config",
                         "troubleShooter", PREFIX + "/old-payload"):
                member = tarfile.TarInfo(name)
                member.size = 5
                archive.addfile(member, io.BytesIO(b"stale"))
        self.valid = self.fixture_tar()
        for name in TAR_NAMES:
            (self.output / name).write_bytes(self.valid)
        self.changed = self.output / sorted(TAR_NAMES)[-1]
        mock = patch("check_built_usb.load_control_script", return_value=self.control)
        mock.start()
        self.addCleanup(mock.stop)

    def fixture_tar(self, *, native: bytes | None = None, stock_data: bytes | None = None,
                    mode: int = 0o755, control: bytes | None = None) -> bytes:
        result = io.BytesIO()
        with tarfile.open(fileobj=result, mode="w", format=tarfile.GNU_FORMAT) as archive:
            for member, data in self.stock:
                if member.isreg() and stock_data is not None:
                    member = tarfile.TarInfo.frombuf(member.tobuf(), "utf-8", "strict")
                    data, member.size = stock_data, len(stock_data)
                archive.addfile(member, io.BytesIO(data) if member.isreg() else None)
            for name in ("./usb_news", PREFIX + "/data/local/tmp/nemesis"):
                member = tarfile.TarInfo(name)
                member.type, member.mode = tarfile.DIRTYPE, 0o755
                member.uid = member.gid = 1000
                member.uname = member.gname = "system"
                archive.addfile(member)
            for name, data, file_mode in (
                (PREFIX + "/data/local/tmp/nemesis/nemesis.bin", self.native if native is None else native, mode),
                (PREFIX + "/data/local/tmp/nemesis/NEMESIS.apk", self.manager, 0o644),
                (PREFIX + "/data/app/NEMESIS-Installer.apk", self.installer, 0o644),
                (PREFIX + "/data/local/tmp/nemesis/nemesis", self.control if control is None else control, 0o755),
            ):
                member = tarfile.TarInfo(name)
                member.size, member.mode = len(data), file_mode
                member.uid = member.gid = 1000
                member.uname = member.gname = "system"
                archive.addfile(member, io.BytesIO(data))
        return result.getvalue()

    def verify(self) -> dict[str, int]:
        return verify_built_usb(self.template, self.output, self.source, self.usb)

    def rejects(self, message: str) -> None:
        with self.assertRaisesRegex(VerificationError, message):
            self.verify()

    def test_valid_matrix_retains_stock_symlink_duplicate_order_and_data(self) -> None:
        self.assertEqual(self.verify(), {"variants": 144, "extras": 2, "stock_members": 3,
                                         "tar_bytes": len(self.valid)})

    def test_swapped_native_or_changed_stock_is_rejected(self) -> None:
        for damaged in (self.fixture_tar(native=b"\x7fELFold native"),
                        self.fixture_tar(stock_data=b"different opaque bytes"),
                        self.fixture_tar(control=b"different control script"), self.fixture_tar(mode=0o777)):
            self.changed.write_bytes(damaged)
            self.rejects("TAR differs")

    def test_both_apks_must_match_fresh_inputs(self) -> None:
        for path in (self.source / "manager/NEMESIS.apk", self.usb / "installer/NEMESIS-Installer.apk"):
            original = path.read_bytes()
            path.write_bytes(original + b"changed")
            self.rejects("TAR differs")
            path.write_bytes(original)

    def test_missing_extra_or_misnamed_variant(self) -> None:
        self.changed.unlink()
        self.rejects("inventory differs")
        wrong = self.output / "new_system_package_UNKNOWN.tar"
        wrong.write_bytes(self.valid)
        self.rejects("inventory differs")
        self.changed.write_bytes(self.valid)
        self.rejects("inventory differs")

    def test_changed_and_missing_stick_extra(self) -> None:
        extra = self.output / sorted(EXTRA_NAMES)[0]
        extra.write_bytes(b"changed")
        self.rejects("stick extra differs")
        extra.unlink()
        self.rejects("inventory differs")

    def test_output_symlink_rejected(self) -> None:
        self.changed.unlink()
        self.changed.symlink_to(self.output / sorted(TAR_NAMES)[0])
        self.rejects("not a regular file")

    def test_header_padding_hidden_tail_and_truncation(self) -> None:
        nonzero_padding = bytearray(self.valid)
        nonzero_padding[-1] = 1
        for damaged in (bytes(nonzero_padding), self.valid + b"hidden", self.valid[:-512],
                        self.valid.replace(b"NEgl1.txt", b"NEgl2.txt", 1)):
            self.changed.write_bytes(damaged)
            self.rejects("TAR differs")

    def test_cli_accepts_out_and_reports_missing_files(self) -> None:
        script = Path(__file__).with_name("check_built_usb.py")
        result = subprocess.run([sys.executable, str(script), "--template", str(self.template),
                                 "--out", str(self.root / "absent")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("FAIL:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
