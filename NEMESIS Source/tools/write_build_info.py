#!/usr/bin/env python3
"""Record the current CI build, copying only the freshly generated installer."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def command(*args: str) -> str:
    return subprocess.check_output(
        args, cwd=ROOT, stderr=subprocess.STDOUT, text=True
    ).strip()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    source = ROOT / "NEMESIS Source"
    installer = ROOT / "USB OTA troubleShooter path/out/ota_package.tar"
    native = source / "native/nemesis"
    apk = source / "manager/NEMESIS.apk"
    version = re.search(r'#define NEMESIS_VERSION "([0-9.]+)"',
                        (source / "native/nemesis.h").read_text()).group(1)
    outputs = {
        "ota_package.tar": installer,
        "nemesis-usb-update-package.7z": source / "out/nemesis-usb-update-package.7z",
        "usb-template-info.json": Path(os.environ["NEMESIS_USB_INPUT_DIR"]) / "usb-template-info.json",
        f"nemesis-update-{version}.zip": source / f"out/nemesis-update-{version}.zip",
        "NEMESIS.data": source / "out/NEMESIS.data",
        "NEMESIS-Installer.apk": ROOT / "USB package path/installer/NEMESIS-Installer.apk",
    }
    commit = command("git", "rev-parse", "HEAD")
    if commit != os.environ["GITHUB_SHA"]:
        raise SystemExit("checkout commit differs from the workflow source commit")
    command("git", "diff", "--exit-code", "HEAD")
    ndk = Path(os.environ["NEMESIS_ANDROID_SDK"]) / "ndk" / os.environ["NDK_VERSION"]
    clang = ndk / "toolchains/llvm/prebuilt/linux-x86_64/bin/armv7a-linux-androideabi19-clang"
    repo = os.environ["GITHUB_REPOSITORY"]
    run_url = (
        f"{os.environ['GITHUB_SERVER_URL']}/{repo}/actions/runs/"
        f"{os.environ['GITHUB_RUN_ID']}"
    )
    info = {
        "source_repository": repo,
        "source_commit": commit,
        "source_tree": command("git", "rev-parse", "HEAD^{tree}"),
        "source_ref": os.environ["GITHUB_REF"],
        "event": os.environ["GITHUB_EVENT_NAME"],
        "workflow_ref": os.environ["GITHUB_WORKFLOW_REF"],
        "run_url": run_url,
        "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        "runner_image": os.environ.get("ImageOS", ""),
        "runner_image_version": os.environ.get("ImageVersion", ""),
        "version": version,
        "build_profile": "usb-only-minimal",
        "network_policy": "Manager has no INTERNET permission; Portal is an offline stub; automatic checks and online controls are disabled. USB installation logic is unchanged. This is not a vehicle-wide network firewall.",
        "upstream_commit": "357a1440df3bd35f06393b96280a725f3efac226",
        "build_targets": ["USB OTA troubleShooter path", "USB package path", "core update ZIP"],
        "complete_usb_entrypoint_built": True,
        "usb_template": json.loads(outputs["usb-template-info.json"].read_text()),
        "build_input_policy": "Native NEMESIS, Manager and Installer APKs compiled from source; navigation template binaries and signed TarList inputs preserved from checksum-pinned upstream release.",
        "toolchain": {
            "java_requested": os.environ["JAVA_VERSION"],
            "java": command("java", "-version"),
            "android_platform": os.environ["ANDROID_PLATFORM"],
            "sdk_tools_build": os.environ["SDK_TOOLS_BUILD"],
            "sdk_tools_sha256": os.environ["SDK_TOOLS_SHA256"],
            "android_build_tools": os.environ["BUILD_TOOLS_VERSION"],
            "ndk": os.environ["NDK_VERSION"],
            "clang": command(str(clang), "--version"),
            "aapt": command("aapt", "version"),
            "d8": command("d8", "--version"),
            "python": command("python3", "--version"),
            "make": command("make", "--version"),
            "seven_zip": "\n".join(command("7z", "i").splitlines()[:4]),
        },
        "sha256": {
            **{name: digest(path) for name, path in outputs.items()},
            "embedded_native_nemesis": digest(native),
            "embedded_manager_apk": digest(apk),
        },
        "validation": {
            "embedded_payloads_match_fresh_build": True,
            "tracked_source_unchanged": True,
            "vehicle_tested": False,
        },
        "signing": "Fresh per-run APK key; not the upstream signing identity.",
        "reproducible_bytes": False,
    }
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    for name, path in outputs.items():
        shutil.copyfile(path, dist / name)
    (dist / "build-info.json").write_text(json.dumps(info, indent=2) + "\n")
    (dist / "SHA256SUMS").write_text("".join(
        f"{digest(dist / name)}  {name}\n"
        for name in [*outputs, "build-info.json"]
    ))
    summary = (
        f"Built installer from `{commit}`.\n\n"
        f"SHA-256: `{info['sha256']['ota_package.tar']}`\n\n"
        "Download `nemesis-installer-" + commit + "` from this run's artifacts. "
        "It contains the complete USB installation .7z, OTA tar, core update ZIP/descriptor, Installer APK, checksums, and build record. "
        "The full USB bundle includes checksum-pinned upstream navigation binaries and signed support files; "
        "Nemesis binaries are freshly compiled with the minimal USB-only policy. "
        "No vehicle installation or compatibility test was performed.\n"
    )
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as out:
        out.write(summary)
    print(summary)


if __name__ == "__main__":
    main()
