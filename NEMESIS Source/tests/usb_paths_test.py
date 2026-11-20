#!/usr/bin/env python3
"""Run the USB-only input boundary test on host files, without Android or device code."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="nemesis-usb-paths-") as temp:
        base = Path(temp)
        for name in ("usb/packages", "cache", "usb-sibling", "classes"):
            (base / name).mkdir(parents=True)
        for name in ("usb/package.zip", "usb/packages/dependency.zip", "cache/nemesis-update.zip",
                     "usb-sibling/package.zip"):
            (base / name).write_bytes(b"host fixture, not an executable package")
        (base / "usb/inside-link.zip").symlink_to(base / "usb/packages/dependency.zip")
        (base / "usb/outside-link.zip").symlink_to(base / "cache/nemesis-update.zip")
        subprocess.run([
            "javac", "-source", "1.7", "-target", "1.7", "-d", str(base / "classes"),
            str(ROOT / "manager/src/com/nemesis/manager/UsbPaths.java"),
            str(ROOT / "tests/src/com/nemesis/manager/UsbPathsRun.java"),
        ], check=True)
        subprocess.run([
            "java", "-cp", str(base / "classes"), "com.nemesis.manager.UsbPathsRun", str(base),
        ], check=True)


if __name__ == "__main__":
    main()
