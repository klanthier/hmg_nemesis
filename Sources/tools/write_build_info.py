#!/usr/bin/env python3
"""Record the current CI build, copying only the freshly generated installer."""
from __future__ import annotations

import hashlib
import json
import os
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
    # Keep this separate from the prebuilt ota_package.tar at repository root.
    installer = ROOT / "Sources/usb_bundle/ota_package.tar"
    native = ROOT / "Sources/native/nemesis"
    apk = ROOT / "Sources/manager/NEMESIS.apk"
    commit = command("git", "rev-parse", "HEAD")
    if commit != os.environ["GITHUB_SHA"]:
        raise SystemExit("checkout commit differs from the workflow source commit")
    command("git", "diff", "--exit-code", "HEAD")
    ndk = Path(os.environ["ANDROID_HOME"]) / "ndk" / os.environ["NDK_VERSION"]
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
        "build_target": "make -C Sources troubleshooter",
        "toolchain": {
            "java_requested": os.environ["JAVA_VERSION"],
            "java": command("java", "-version"),
            "android_platform": os.environ["ANDROID_PLATFORM"],
            "android_build_tools": os.environ["BUILD_TOOLS_VERSION"],
            "ndk": os.environ["NDK_VERSION"],
            "clang": command(str(clang), "--version"),
            "aapt": command("aapt", "version"),
            "d8": command("d8", "--version"),
            "python": command("python3", "--version"),
            "make": command("make", "--version"),
        },
        "sha256": {
            "ota_package.tar": digest(installer),
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
    shutil.copyfile(installer, dist / "ota_package.tar")
    (dist / "build-info.json").write_text(json.dumps(info, indent=2) + "\n")
    (dist / "SHA256SUMS").write_text("".join(
        f"{digest(dist / name)}  {name}\n"
        for name in ("ota_package.tar", "build-info.json")
    ))
    summary = (
        f"Built installer from `{commit}`.\n\n"
        f"SHA-256: `{info['sha256']['ota_package.tar']}`\n\n"
        "Download `nemesis-installer-" + commit + "` from this run's artifacts. "
        "It contains the fresh tar, checksums, and build record. "
        "The root prebuilt tar was not used. Runtime/network behavior is unchanged. "
        "No vehicle installation or compatibility test was performed.\n"
    )
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as out:
        out.write(summary)
    print(summary)


if __name__ == "__main__":
    main()
