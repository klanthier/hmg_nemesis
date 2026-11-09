#!/usr/bin/env python3
"""Host-only regression tests for installer verification; no Android tools needed."""
from __future__ import annotations

import io
import re
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from check_built_tar import VerificationError, verify_built_tar


class BuiltTarTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="nemesis-built-tar-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / "ota_package_troubleshooter.tar"
        self.alias = self.root / "ota_package.tar"
        self.elf_path = self.root / "nemesis"
        self.apk_path = self.root / "NEMESIS.apk"
        self.elf = b"\x7fELF" + bytes(range(256))
        zip_data = io.BytesIO()
        with zipfile.ZipFile(zip_data, "w") as apk:
            apk.writestr("classes.dex", b"dex\n035\x00synthetic test data")
        self.apk = zip_data.getvalue()
        self.elf_path.write_bytes(self.elf)
        self.apk_path.write_bytes(self.apk)
        self.header = ("#!/system/bin/sh\n"
                       "ELF_SKIP=4096\n"
                       f"ELF_LEN={len(self.elf)}\n"
                       f"APK_SKIP={4096 + len(self.elf)}\n"
                       f"APK_LEN={len(self.apk)}\n"
                       "exit 0\n# NEMESIS_PAYLOAD\n").encode()
        self.member = self.header.ljust(4096, b"\n") + self.elf + self.apk
        self.write_archive(self.member)

    def write_archive(self, payload: bytes, *, extra: bool = False,
                      name: str = "troubleShooter", kind: bytes = tarfile.REGTYPE) -> bytes:
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode="w", format=tarfile.GNU_FORMAT) as out:
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            info.mode = 0o755
            info.uid = info.gid = 0
            info.type = kind
            if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                info.linkname = "elsewhere"
                info.size = 0
            out.addfile(info, io.BytesIO(payload))
            if extra:
                other = tarfile.TarInfo("extra")
                other.size = 6
                out.addfile(other, io.BytesIO(b"hidden"))
        blob = data.getvalue()
        self.write_bytes(blob)
        return blob

    def write_bytes(self, blob: bytes) -> None:
        self.archive.write_bytes(blob)
        self.alias.write_bytes(blob)

    def verify(self) -> dict[str, int]:
        return verify_built_tar(self.archive, self.alias, self.elf_path, self.apk_path)

    def rejects(self, message: str) -> None:
        with self.assertRaisesRegex(VerificationError, message):
            self.verify()

    def changed_assignment(self, key: str, value: str) -> bytes:
        header = re.sub(rb"^" + key.encode() + rb"=[^\n]*$",
                        key.encode() + b"=" + value.encode(), self.header, flags=re.MULTILINE)
        return header.ljust(4096, b"\n") + self.elf + self.apk

    def test_valid_archive(self) -> None:
        sizes = self.verify()
        self.assertEqual(sizes["header_bytes"], 4096)
        self.assertEqual(sizes["elf_bytes"], len(self.elf))
        self.assertEqual(sizes["apk_bytes"], len(self.apk))

    def test_embedded_payloads_must_equal_current_outputs(self) -> None:
        for index, message in ((4096 + 10, "embedded ELF"),
                               (4096 + len(self.elf) + 10, "embedded APK")):
            with self.subTest(payload=message):
                damaged = bytearray(self.member)
                damaged[index] ^= 1
                self.write_archive(bytes(damaged))
                self.rejects(message)

    def test_changed_build_output_is_rejected(self) -> None:
        for path, original, message in ((self.elf_path, self.elf, "embedded ELF"),
                                        (self.apk_path, self.apk, "embedded APK")):
            with self.subTest(path=path.name):
                path.write_bytes(original + b"new build")
                self.rejects(message)
                path.write_bytes(original)

    def test_offsets_and_lengths(self) -> None:
        cases = (("ELF_SKIP", "0"), ("ELF_SKIP", "4095"),
                 ("ELF_SKIP", "8192"), ("ELF_LEN", "0"),
                 ("ELF_LEN", "99999999999999999999"),
                 ("APK_SKIP", "4096"), ("APK_SKIP", "9999999"),
                 ("APK_LEN", "0"), ("APK_LEN", "9999999"),
                 ("APK_LEN", str(len(self.apk) - 1)),
                 ("APK_LEN", "-1"), ("APK_LEN", "garbage"))
        for key, value in cases:
            with self.subTest(key=key, value=value):
                self.write_archive(self.changed_assignment(key, value))
                self.rejects("offset|length|range|assignment|contiguous")

    def test_missing_or_duplicate_assignments(self) -> None:
        for key in (b"ELF_SKIP", b"ELF_LEN", b"APK_SKIP", b"APK_LEN"):
            for duplicate in (False, True):
                with self.subTest(key=key, duplicate=duplicate):
                    line = re.search(rb"^" + key + rb"=[^\n]*\n", self.header, re.MULTILINE).group()
                    changed = self.header.replace(line, line + line if duplicate else b"")
                    self.write_archive(changed.ljust(4096, b"\n") + self.elf + self.apk)
                    self.rejects("duplicate|missing")

    def test_missing_marker(self) -> None:
        self.write_archive(self.member.replace(b"# NEMESIS_PAYLOAD", b"# WRONG__PAYLOAD"))
        self.rejects("missing payload marker")

    def test_non_newline_header_padding(self) -> None:
        changed = bytearray(self.member)
        changed[len(self.header) + 1] = ord("X")
        self.write_archive(bytes(changed))
        self.rejects("between payload marker and ELF")

    def test_member_hidden_tail_and_truncation(self) -> None:
        for payload in (self.member + b"hidden", self.member[:-1]):
            with self.subTest(length=len(payload)):
                self.write_archive(payload)
                self.rejects("hidden tail")

    def test_extra_archive_member(self) -> None:
        self.write_archive(self.member, extra=True)
        self.rejects("extra members")

    def test_wrong_member_name_or_type(self) -> None:
        self.write_archive(self.member, name="other")
        self.rejects("only troubleShooter")
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.DIRTYPE):
            with self.subTest(kind=kind):
                self.write_archive(self.member, kind=kind)
                self.rejects("ordinary regular file")

    def test_corrupt_tar_checksum(self) -> None:
        archive = bytearray(self.archive.read_bytes())
        archive[100] ^= 1
        self.write_bytes(bytes(archive))
        self.rejects("invalid TAR header")

    def test_nonzero_tar_padding_or_trailing_data(self) -> None:
        for position in (512 + len(self.member), -1):
            with self.subTest(position=position):
                archive = bytearray(self.write_archive(self.member))
                archive[position] = ord("X")
                self.write_bytes(bytes(archive))
                self.rejects("nonzero padding/trailing data")

    def test_appended_archive_tail_or_truncation(self) -> None:
        original = self.archive.read_bytes()
        for changed in (original + b"hidden", original + b"\0" * 10240,
                        original[:-512], original[:511]):
            with self.subTest(length=len(changed)):
                self.write_bytes(changed)
                self.rejects("truncated|tail")

    def test_alias_must_be_identical(self) -> None:
        self.alias.write_bytes(self.alias.read_bytes() + b"different")
        self.rejects("alias differs")

    def test_invalid_build_output_signatures(self) -> None:
        for path, original, message in ((self.elf_path, self.elf, "not an ELF"),
                                        (self.apk_path, self.apk, "not an APK")):
            with self.subTest(path=path.name):
                path.write_bytes(b"bad" + original[3:])
                self.rejects(message)
                path.write_bytes(original)

    def test_cli_reports_missing_file_without_traceback(self) -> None:
        checker = Path(__file__).with_name("check_built_tar.py")
        result = subprocess.run([sys.executable, str(checker), "--tar", str(self.root / "absent")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("FAIL:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
