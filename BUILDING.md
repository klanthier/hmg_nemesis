# Building NEMESIS from source

The fork's **Build installer from source** GitHub Action builds upstream 1.16.9
at `357a1440df3bd35f06393b96280a725f3efac226` plus the fork's build tooling.
It compiles the native executable, Manager APK and Installer APK on a clean
GitHub-hosted Ubuntu runner. No upstream prebuilt executable is a build input.

## Outputs and their intended use

| Artifact file | Purpose |
| --- | --- |
| `ota_package.tar` | Original DSP/OTA installation method; requires that entrypoint on the head unit. Copy intact, do not extract. |
| `nemesis-update-1.16.9.zip` and `NEMESIS.data` | Update an existing NEMESIS 1.16+ installation; put both files at USB root. |
| `NEMESIS-Installer.apk` | Source-built installer application for inspection/development. Alone it does **not** provide the new USB installation method. |
| `build-info.json`, `SHA256SUMS` | Source/toolchain information and output hashes. |

**This workflow does not produce `nemesis-usb-update-package.7z`.** The new USB
entrypoint requires an external `new_system_package_*.tar` template. The public
1.16.9 bundle contains symlink/file pairs that replace navigation libraries under
`/navi/navi_backup/BIN/G40` and `G45`; their source/build recipe is not published
in this repository. Upstream's builder carries those members forward. Packaging
that template would reuse opaque executable inputs, so this workflow excludes it.
It also does not build the separate engine-sound or other optional mod packages.

The new upstream compatibility guidance requires an Android Gen5W **S5W_M**
head unit with recent firmware (250818 or newer is documented as confirmed).
The earlier blanket Ioniq 6 exclusion was removed. A `260903` suffix alone does
not identify the platform or establish compatibility; check the complete SW
identifier. Neither this build nor its tests demonstrate installation on a car.
Building from source does not disable LTE, remove the package store, or alter
upstream runtime behavior.

## Run and verify

1. In your fork, open **Actions → Build installer from source → Run workflow**.
2. Select `main` and wait for both `build` and `attest` to pass.
3. Download `nemesis-installer-<fullcommit>` from the run's artifacts.
4. Extract that GitHub artifact ZIP on your computer and check `SHA256SUMS`:

```sh
# macOS
shasum -a 256 -c SHA256SUMS
# Linux
sha256sum -c SHA256SUMS
```

The workflow also runs on pushes to `main` and pull requests. Artifacts are
retained for 30 days. PRs and manual non-default branches build without a
provenance attestation. A separate job with no project-code execution attests
the four payload files and build metadata for default-branch builds.

```sh
EXPECTED_COMMIT='replace-with-the-reviewed-full-commit'
gh attestation verify ota_package.tar \
  --repo klanthier/hmg_nemesis \
  --signer-workflow klanthier/hmg_nemesis/.github/workflows/build-installer.yml \
  --source-digest "$EXPECTED_COMMIT" \
  --deny-self-hosted-runners
```

Repeat for the update ZIP, descriptor, Installer APK and `build-info.json`.
The signed bundle is also available as `nemesis-provenance-<fullcommit>`.
Provenance identifies the source/build association; it does not certify that
source is benign or that a vehicle installation is safe.

## Toolchain and validation

Pinned toolchain: Ubuntu 22.04, Temurin 17.0.17+10, Android API 30 compile SDK,
Build Tools 30.0.3, command-line tools build 13114758 with SHA-256 verification,
and NDK 21.4.7075529 (r21e). Native and APK minimum API remains 19; native is ARMv7.
Actions are pinned by commit. The source layout contains spaces, so paths are quoted.

CI runs metadata, Setup and Store host tests plus archive-verifier tamper tests.
It cleans both APK build directories, generates fresh local signing keys, builds
the OTA installer and core update, and independently checks their embedded
binaries against the freshly compiled files. The update verifier also checks its
member allowlist, descriptors, scripts, certificates and checksum manifest.
The Installer APK gets DEX/version/class/permission checks. Compilation must not
change tracked files. No generated installer or Android app is executed.

Both APKs use fresh per-run signing keys. Builds are not byte-reproducible and
do not share the upstream APK signing identity. Normal Android replacement of an
APK signed with another key may fail; installation/upgrade handling needs device
validation. Only the build infrastructure and packaging verification are changed
in this fork; review upstream behavior separately.
