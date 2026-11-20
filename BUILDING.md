# Building NEMESIS from source

The fork's **Build Nemesis installation packages** GitHub Action builds upstream 1.16.9
at `357a1440df3bd35f06393b96280a725f3efac226` plus the fork's build tooling and the minimal USB-only changes below.
It compiles the native executable, Manager APK and Installer APK on a clean
GitHub-hosted Ubuntu runner. The complete USB package also preserves navigation
binaries and signed supporting files from a checksum-pinned upstream release.

## Minimal USB-only policy

Version **1.16.9.2** replaces the Manager's `Portal` network client with an offline
stub and removes its `INTERNET` permission. Automatic checks, online store access,
and the modem opt-in are disabled. The existing USB installation, dependency,
and update paths are preserved; all required packages must be supplied on USB.
**Settings → Check for updates** keeps its existing USB scan and shows USB
instructions when no update is present, instead of contacting the server. Previously downloaded online
updates are not offered for installation.

Native service supervision, the installer, navigation inputs, Wi-Fi controls,
and package execution are unchanged. The original update monitor may still send
an hourly local broadcast, which the Manager ignores. This does not disable the
vehicle modem or restrict OEM services, navigation binaries, or installed mods.

## Outputs and their intended use

| Artifact file | Purpose |
| --- | --- |
| `nemesis-usb-update-package.7z` | Complete new USB installation bundle: extract to USB root, leaving its 144 inner TARs intact. |
| `usb-template-info.json` | Pinned upstream input hashes and an inventory of preserved template contents. |
| `ota_package.tar` | Original DSP/OTA installation method; requires that entrypoint on the head unit. Copy intact, do not extract. |
| `nemesis-update-1.16.9.2.zip` and `NEMESIS.data` | Update an existing NEMESIS 1.16+ installation; put both files at USB root. |
| `NEMESIS-Installer.apk` | Source-built installer application; also embedded in every TAR in the full USB bundle. Not installed separately for the USB method. |
| `build-info.json`, `SHA256SUMS` | Source/toolchain information and output hashes. |

## Complete USB package and provenance

The workflow runs `make -C "USB package path" TEMPLATE=...` with the pinned
Android toolchain. It produces all 144 brand/region/variant TARs plus
`NEW_TarList.txt_encrypted` and `NEW_TarList.txt_encrypted.rsa`, compressed into
`nemesis-usb-update-package.7z`. This matches the public release's file inventory;
`splash.png` is not present in that release and is not invented. Optional mod
packages such as engine-sound are not part of upstream's USB installation target.

The template comes from upstream's `v1.16.9/nemesis-usb-update-package.7z`, with
archive SHA-256 `aeccf9050f36817592cc91b20e6e946f462cf2faf99d2cc35c2666fe655d5f54`.
Its selected TAR has SHA-256
`c39a62d61bc74c11f850ed2763a74a355608914c69e90ff691a99ac4fa22ee17`.
All 144 upstream TARs were found to be byte-identical. Preparation verifies the
archive, selected template, complete filename inventory and both signed extras.
It reads the TAR as data; it never extracts its traversal/symlink members on CI.

This is a mixed-input build: Nemesis's three executables are freshly compiled,
but navigation-library payloads and signed/encrypted supporting files are copied
from upstream. They are not represented as source-rebuilt or independently
verified manufacturer inputs. `usb-template-info.json` records these exact
bytes and their intended destinations. The full bundle retains the upstream
installer behavior and the previously documented risks; it has not been tested
on a vehicle. Hash checks and provenance do not establish safety.

To prepare the USB, extract only the outer `.7z` onto a blank FAT32/exFAT drive.
The 144 `.tar` files and the two `NEW_TarList` files must sit directly at the USB
root, with no enclosing folder. Do not extract those inner TARs on your computer.
The full USB archive is a separate installation option from `ota_package.tar`;
do not combine the two layouts. See upstream's `02-USB-Update-Package.md` for
the head-unit procedure.

The new upstream compatibility guidance requires an Android Gen5W **S5W_M**
head unit with recent firmware (250818 or newer is documented as confirmed).
The earlier blanket Ioniq 6 exclusion was removed. A `260903` suffix alone does
not identify the platform or establish compatibility; check the complete SW
identifier. Neither this build nor its tests demonstrate installation on a car.
The USB-only policy removes Manager server requests; it does not disable LTE
for other software on the vehicle.

## Run and verify

1. In your fork, open **Actions → Build Nemesis installation packages → Run workflow**.
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
all output files and their build/input metadata for default-branch builds.

```sh
EXPECTED_COMMIT='replace-with-the-reviewed-full-commit'
gh attestation verify ota_package.tar \
  --repo klanthier/hmg_nemesis \
  --signer-workflow klanthier/hmg_nemesis/.github/workflows/build-installer.yml \
  --source-digest "$EXPECTED_COMMIT" \
  --deny-self-hosted-runners
```

Repeat for the USB `.7z`, `usb-template-info.json`, update ZIP, descriptor,
Installer APK and `build-info.json`.
The signed bundle is also available as `nemesis-provenance-<fullcommit>`.
Provenance identifies the source/build association; it does not certify that
source is benign or that a vehicle installation is safe.

## Toolchain and validation

Pinned toolchain: Ubuntu 22.04, Temurin 17.0.17+10, Android API 30 compile SDK,
Build Tools 30.0.3, command-line tools build 13114758 with SHA-256 verification,
and NDK 21.4.7075529 (r21e). Native and APK minimum API remains 19; native is ARMv7.
Actions are pinned by commit. The source layout contains spaces, so paths are quoted.

CI runs metadata, Setup, Store and offline-policy host tests plus archive-verifier tamper tests.
Both compiled APKs are checked for internet permission, network API references
and executable references to author endpoints.
It cleans both APK build directories, generates fresh local signing keys, builds
the full USB package, OTA installer and core update, and checks their embedded
binaries against the freshly compiled files. The shared Manager APK is built once
and reused to avoid re-signing it between packaging targets. Every USB TAR is
checked for exact template preservation, payloads, mode/ownership and names.
The outer archive is tested, extracted into a temporary directory, then all
144 TARs and support files are verified again without extracting inner TARs. The update verifier also checks its
member allowlist, descriptors, scripts, certificates and checksum manifest.
The Installer APK gets DEX/version/class/permission checks. Compilation must not
change tracked files. No generated installer or Android app is executed.

Both APKs use fresh per-run signing keys. Builds are not byte-reproducible and
do not share the upstream APK signing identity. Normal Android replacement of an
APK signed with another key may fail; installation/upgrade handling needs device
validation. Runtime changes are limited to the USB-only policy above; the rest
of upstream behavior still needs separate review.
