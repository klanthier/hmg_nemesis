#!/usr/bin/env python3
"""Host-only tamper tests; fixtures do not use the update ZIP generator."""
from __future__ import annotations

import hashlib
import io
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path

from check_built_update import CA_NAMES, PAYLOAD_PATHS, VerificationError, verify_built_update


class BuiltUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="nemesis built update ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "out").mkdir()
        self.archive = self.root / "out/nemesis-update-1.16.9.zip"
        self.external = self.root / "out/NEMESIS.data"
        self.files = {}
        for name, relative in PAYLOAD_PATHS.items():
            data = f"fixture for {name}\n".encode()
            if name == "core/nemesis":
                data = b"\x7fELF" + bytes(range(256))
            elif name == "core/NEMESIS.apk":
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w") as apk:
                    apk.writestr("classes.dex", b"dex\n035\0synthetic test DEX")
                data = buffer.getvalue()
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            self.files[name] = data
        (self.root / "native/nemesis.h").write_text('#define NEMESIS_VERSION "1.16.9"\n')
        (self.root / "boot/cacerts/README").write_text("not a payload\n")
        self.files["NEMESIS.data"] = (
            b"[nemesis]\nversion=1.1\nid=nemesis.core\nname=NEMESIS\ntype=update\n"
            b'package-version=1.16.9\nshort-desc="NEMESIS 1.16.9 core update"\nos="any"\nmodels="any"\n')
        self.external.write_bytes(b"[nemesis]\nversion=1.1\ntype=update\npath=nemesis-update-1.16.9.zip\n")
        self.write_archive()

    @staticmethod
    def manifest(files: dict[str, bytes]) -> bytes:
        return "".join(f"{hashlib.md5(data).hexdigest()}  {name}\n"
                       for name, data in sorted(files.items()) if name != "MD5SUMS").encode()

    def write_archive(self, files: dict[str, bytes] | None = None, *,
                      extra: tuple[str, bytes] | None = None,
                      mode: tuple[str, int] | None = None) -> None:
        entries = dict(self.files if files is None else files)
        entries.setdefault("MD5SUMS", self.manifest(entries))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(self.archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name, data in entries.items():
                    if mode and name == mode[0]:
                        info = zipfile.ZipInfo(name)
                        info.create_system = 3
                        info.external_attr = mode[1] << 16
                        archive.writestr(info, data)
                    else:
                        archive.writestr(name, data)
                if extra:
                    archive.writestr(*extra)

    def verify(self) -> dict[str, int | str]:
        return verify_built_update(self.archive, self.external, self.root)

    def rejects(self, expression: str) -> None:
        with self.assertRaisesRegex(VerificationError, expression):
            self.verify()

    def test_valid_update_and_cli_with_spaces_in_source_path(self) -> None:
        result = self.verify()
        self.assertEqual(result["version"], "1.16.9")
        self.assertEqual(result["entries"], 29)
        self.assertEqual(result["ca_files"], 23)
        checker = Path(__file__).with_name("check_built_update.py")
        process = subprocess.run([sys.executable, str(checker), "--source-root", str(self.root)],
                                 capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("OK: update 1.16.9", process.stdout)

    def test_every_payload_must_match_even_with_recomputed_md5(self) -> None:
        for name in PAYLOAD_PATHS:
            with self.subTest(name=name):
                files = dict(self.files)
                files[name] = files[name][:-1] + bytes([files[name][-1] ^ 1])
                self.write_archive(files)
                self.rejects("differs from current build input")

    def test_changed_source_outputs_are_rejected(self) -> None:
        for name in ("core/nemesis", "core/NEMESIS.apk", "core/qb_hook.sh"):
            with self.subTest(name=name):
                path = self.root / PAYLOAD_PATHS[name]
                original = path.read_bytes()
                path.write_bytes(original + b"new build")
                self.rejects("differs from current build input")
                path.write_bytes(original)

    def test_missing_or_added_ca_requires_inventory_review(self) -> None:
        path = self.root / "boot/cacerts" / sorted(CA_NAMES)[0]
        original = path.read_bytes()
        path.unlink()
        self.rejects("source CA inventory")
        path.write_bytes(original)
        (path.parent / "12345678.0").write_bytes(b"extra CA")
        self.rejects("source CA inventory")

    def test_symlink_source_input_is_rejected(self) -> None:
        path = self.root / "boot/qb_hook.sh"
        target = self.root / "elsewhere"
        target.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(target)
        self.rejects("not a regular file")

    def test_invalid_elf_and_apk_inputs(self) -> None:
        for name, message in (("core/nemesis", "not an ELF"), ("core/NEMESIS.apk", "not an APK")):
            with self.subTest(name=name):
                path = self.root / PAYLOAD_PATHS[name]
                original = path.read_bytes()
                path.write_bytes(b"bad" + original[3:])
                self.rejects(message)
                path.write_bytes(original)

    def test_missing_and_extra_entries(self) -> None:
        files = dict(self.files)
        del files["core/qb_hook.sh"]
        self.write_archive(files)
        self.rejects("exactly the expected entries")
        self.write_archive(extra=("scripts/migrate.sh", b"unexpected"))
        self.rejects("exactly the expected entries")
        files["scripts/migrate.sh"] = b"replacement keeps entry count"
        self.write_archive(files)
        self.rejects("whitelist mismatch")

    def test_duplicate_zip_entry(self) -> None:
        files = dict(self.files)
        del files["core/qb_hook.sh"]
        self.write_archive(files, extra=("core/nemesis", self.files["core/nemesis"]))
        self.rejects("duplicate ZIP entry")

    def test_path_aliases(self) -> None:
        for alias in ("./core/nemesis", "../core/nemesis", "/core/nemesis", "core//nemesis",
                      "core/../core/nemesis", "core\\nemesis", "Core/nemesis"):
            with self.subTest(alias=alias):
                files = dict(self.files)
                files[alias] = files.pop("core/nemesis")
                self.write_archive(files)
                self.rejects("whitelist mismatch")

    def test_nul_alias_rejected_before_zip_name_truncation(self) -> None:
        files = dict(self.files)
        files["core/nemesisX"] = files.pop("core/nemesis")
        self.write_archive(files)
        self.archive.write_bytes(self.archive.read_bytes().replace(b"core/nemesisX", b"core/nemesis\0"))
        self.rejects("NUL/path alias")

    def test_nonregular_zip_entries(self) -> None:
        for kind in (stat.S_IFLNK, stat.S_IFDIR, stat.S_IFIFO, stat.S_IFCHR):
            with self.subTest(kind=kind):
                self.write_archive(mode=("core/qb_hook.sh", kind | 0o755))
                self.rejects("must be a regular file")

    def test_embedded_descriptor_policy_and_source_version(self) -> None:
        original = self.files["NEMESIS.data"]
        for before, after in ((b"type=update", b"type=install"), (b"version=1.1", b"version=1.0"),
                              (b"package-version=1.16.9", b"package-version=1.16.8"),
                              (b"id=nemesis.core", b"id=other"), (b'os="any"', b'os="linux"')):
            with self.subTest(field=before):
                files = dict(self.files)
                files["NEMESIS.data"] = original.replace(before, after)
                self.write_archive(files)
                self.rejects("descriptor fields differ")
        self.write_archive()
        (self.root / "native/nemesis.h").write_text('#define NEMESIS_VERSION "1.16.10"\n')
        self.rejects("filename does not match source version")

    def test_external_descriptor_path_and_type(self) -> None:
        original = self.external.read_bytes()
        for before, after in ((b"type=update", b"type=execute"), (b"version=1.1", b"version=1.0"),
                              (b"path=nemesis", b"path=../nemesis"),
                              (b"1.16.9.zip", b"1.16.8.zip")):
            with self.subTest(field=before):
                self.external.write_bytes(original.replace(before, after))
                self.rejects("external NEMESIS.data: descriptor fields differ")

    def test_duplicate_unknown_and_malformed_descriptor_fields(self) -> None:
        for suffix in (b"type=update\n", b"command=unexpected\n", b"[other]\n", b"\0\n"):
            with self.subTest(suffix=suffix):
                files = dict(self.files)
                files["NEMESIS.data"] += suffix
                self.write_archive(files)
                self.rejects("descriptor")

    def test_md5_integrity_coverage_duplicates_and_aliases(self) -> None:
        manifest = self.manifest(self.files)
        lines = manifest.splitlines(keepends=True)
        for damaged in (b"0" * 32 + manifest[32:], b"".join(lines[1:]), manifest + lines[0],
                        manifest.replace(b"  core/nemesis", b"  ./core/nemesis"),
                        manifest + b"0" * 32 + b"  MD5SUMS\n", b"not a manifest\n"):
            with self.subTest(manifest=damaged[:60]):
                self.write_archive({**self.files, "MD5SUMS": damaged})
                self.rejects("MD5SUMS")

    def test_crc_corruption(self) -> None:
        self.write_archive(mode=("core/qb_hook.sh", stat.S_IFREG | 0o644))  # Stored payload.
        raw = self.archive.read_bytes()
        original = self.files["core/qb_hook.sh"]
        self.archive.write_bytes(raw.replace(original, b"X" + original[1:], 1))
        self.rejects("invalid ZIP")

    def test_invalid_deflate_stream_reports_verification_error(self) -> None:
        raw = bytearray(self.archive.read_bytes())
        name_length, extra_length = struct.unpack_from("<HH", raw, 26)
        offset = 30 + name_length + extra_length
        raw[offset] = (raw[offset] & 0xf8) | 7  # Reserved DEFLATE block type.
        self.archive.write_bytes(raw)
        self.rejects("invalid ZIP")

    def test_hidden_prefix_tail_and_truncation(self) -> None:
        original = self.archive.read_bytes()
        for damaged in (b"hidden" + original, original + b"hidden", original[:-1], original[:10]):
            with self.subTest(length=len(damaged)):
                self.archive.write_bytes(damaged)
                self.rejects("ZIP")

    def test_hidden_local_entry_not_listed_in_directory(self) -> None:
        raw = self.archive.read_bytes()
        footer = bytearray(raw[-22:])
        start = struct.unpack_from("<L", footer, 16)[0]
        hidden = b"PK\x03\x04" + b"hidden local record"
        struct.pack_into("<L", footer, 16, start + len(hidden))
        self.archive.write_bytes(raw[:start] + hidden + raw[start:-22] + footer)
        self.rejects("hidden entries or data")

    def test_cli_missing_file_returns_failure_without_traceback(self) -> None:
        self.archive.unlink()
        checker = Path(__file__).with_name("check_built_update.py")
        result = subprocess.run([sys.executable, str(checker), "--source-root", str(self.root)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("FAIL:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
