# Building NEMESIS from source

The fork's **Build USB-only Nemesis installation packages** GitHub Action builds upstream 1.16.9
at `357a1440df3bd35f06393b96280a725f3efac226` plus the fork's USB-only runtime changes and build tooling.
The fork version is **1.16.9.1**, so existing upstream 1.16.9 installations
can accept its core update from USB.
It compiles the native executable, Manager APK and Installer APK on a clean
GitHub-hosted Ubuntu runner. The complete USB package also preserves navigation
binaries and signed supporting files from a checksum-pinned upstream release.

## USB-only network policy

The Manager has no `INTERNET` permission and no Portal HTTP/TLS client. It does
not query the author service for updates, catalogs, dependencies or device/model
compatibility. Compatibility checks still happen locally. Startup/wake events
retain app auto-launch but perform no online checks. The native online monitor
is no longer seeded, and an existing monitor is retired on startup.

The Package Store reads USB lists and ZIPs only; dependencies must be installed
already or supplied in the USB list. Core updates use a ZIP plus its matching
`NEMESIS.data` at USB root. Cached online downloads and old online intent modes
cannot start an online update. The Manager title identifies this as USB-only.

CI rejects internet permissions in both compiled manifests and network client
APIs/endpoint strings in both APKs' DEX code, and scans first-party native/boot sources for outbound
network clients. These checks cover the code built here. They are not a firewall
for the head unit: OEM telematics, third-party mods/scripts, wireless ADB and the
preserved navigation hook remain outside that claim. Arbitrary root scripts
must still be trusted. Installing a future online-capable build would change
this policy.

## Outputs and their intended use

| Artifact file | Purpose |
| --- | --- |
| `nemesis-usb-update-package.7z` | Complete new USB installation bundle: extract to USB root, leaving its 144 inner TARs intact. |
| `usb-template-info.json` | Pinned upstream input hashes and an inventory of preserved template contents. |
| `ota_package.tar` | Original DSP/OTA installation method; requires that entrypoint on the head unit. Copy intact, do not extract. |
| `nemesis-update-1.16.9.1.zip` and `NEMESIS.data` | Update an existing NEMESIS 1.16+ installation; put both files at USB root. |
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
bytes and their intended destinations. The full bundle retains upstream installation mechanics and the previously
documented navigation hook, while the Manager and built-in service behavior
is USB-only. It has not been tested on a vehicle. Hash checks and provenance do not establish safety.

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
The USB-only build removes Nemesis online requests; it does not disable the
vehicle modem or prevent unrelated software from using LTE.

## Run and verify

1. In your fork, open **Actions → Build USB-only Nemesis installation packages → Run workflow**.
2. Select `main` and wait for both `build` and `attest` to pass.
3. Download `nemesis-usb-only-<fullcommit>` from the run's artifacts.
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

CI runs metadata, Setup and Store host tests plus archive-verifier and offline-policy tamper tests.
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
validation. Runtime differences are the USB-only policy described above;
other upstream behavior still requires separate review.
