# Building an installer from source

The [Build installer from source workflow](.github/workflows/build-installer.yml)
builds the native NEMESIS executable and Manager APK from the checked-out source,
then packages them as `ota_package.tar`. Use this
when you want a build associated with a particular source commit instead of the
prebuilt archive committed to the repository.

This is a build workflow only. It does not change NEMESIS network behavior,
disable LTE, remove the package store, or add vehicle support. The upstream
[compatibility list](README.md#compatibility-check) still identifies the Hyundai
Ioniq 6 as unsupported, including for this build.

## Run a build in your fork

1. Create a fork and enable GitHub Actions in it if GitHub prompts you.
2. Open the fork's **Actions** tab and select **Build installer from source**.
3. Select **Run workflow**, choose the branch to build, and start the run.
4. Wait for the build and validation steps to succeed. Open the run's summary
   and download the artifact named `nemesis-installer-<fullcommit>`.
5. Extract the GitHub artifact ZIP on your computer. It contains the installer
   archive `ota_package.tar`, `SHA256SUMS`, and `build-info.json`.

For manual runs, the workflow must first exist on your fork's default branch
and you need write access to the fork. See [GitHub's manual-run documentation](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow).

The workflow also runs on pushes to `main` and on pull requests. A pull-request
run builds GitHub's checked-out test merge commit; use the recorded full commit
and run metadata to identify what was built. Use a manual run to build another
branch directly. Artifacts are retained for 30 days.

## Check the result

Read `build-info.json` and compare `source_commit` with the full commit you
intended to build. It also records the source repository/tree/ref, workflow and
run URL, toolchain versions, and SHA-256 hashes of the installer and embedded
native executable/APK. Those two binaries are embedded in the installer, not
provided as separate artifact files. In the extracted artifact directory, verify
the installer and build record against `SHA256SUMS`:

```sh
# Linux
sha256sum -c SHA256SUMS

# macOS
shasum -a 256 -c SHA256SUMS
```

The workflow runs `make -C Sources test-meta`, the existing Setup and Store host
tests, and `Sources/tests/test_check_built_tar.py`. After compilation,
[check_built_tar.py](Sources/tests/check_built_tar.py) validates that the native
executable and Manager APK embedded in the new installer match the freshly
compiled files. The build also runs the existing archive and APK checks and
rejects changes to tracked source files during compilation.

[write_build_info.py](Sources/tools/write_build_info.py) records the build and
copies `Sources/usb_bundle/ota_package.tar` into the downloadable artifact. The
prebuilt `ota_package.tar` at repository root stays untouched and is not used as
a build input or published as the result.

Checksums detect changes relative to the downloaded checksum file. They do not
establish that a build is safe or that the source contains no malicious code.
Inspect the source, workflow, and selected commit as part of deciding whether to
trust a build. Successful build checks also do not demonstrate compatibility
with a particular head unit or that installation works on a vehicle.

## Verify a default-branch build's provenance

After a successful push build on the default branch, or a manual build of the
default branch, a separate `attest` job signs GitHub provenance attestations for
`ota_package.tar` and `build-info.json`. It publishes the signed bundle as
`nemesis-provenance-<fullcommit>`. The job does not execute project code. Pull
requests and manual builds of other branches produce the installer artifact
without this attestation.

For a build from `klanthier/hmg_nemesis`, use GitHub CLI on your computer:

```sh
# Replace this with the full source commit you reviewed on GitHub.
EXPECTED_COMMIT='replace-with-reviewed-full-commit'
gh attestation verify ota_package.tar \
  --repo klanthier/hmg_nemesis \
  --signer-workflow klanthier/hmg_nemesis/.github/workflows/build-installer.yml \
  --source-digest "$EXPECTED_COMMIT" \
  --deny-self-hosted-runners
```

Repeat the command with `build-info.json` in place of `ota_package.tar`. For your
own fork, replace the repository owner in both flags. `--source-digest` enforces
the expected source commit; choose that commit independently of the downloaded
metadata. GitHub CLI fetches the attestations from GitHub by default; the saved
provenance bundle can instead be supplied with `--bundle PATH`. See the
[GitHub CLI verification reference](https://cli.github.com/manual/gh_attestation_verify).

This verification establishes the artifact's association with the expected
repository, workflow, and source commit. It does not prove that the source is
benign, that every build dependency is trustworthy, or that the installer is
suitable for your car.

## Toolchain and build target

The workflow uses this toolchain:

| Component | Selection |
| --- | --- |
| GitHub-hosted runner | Ubuntu 22.04 |
| Java | Temurin 17.0.17+10 |
| Android SDK platform | API 30 |
| Android Command-Line Tools | Build 13114758, SHA-256 checked |
| Android Build Tools | 30.0.3 |
| Android NDK | 21.4.7075529 (r21e) |

Checkout, Java setup, artifact upload/download, and `actions/attest` (v4.2.2)
actions are pinned to full commit IDs in the workflow. The workflow downloads
the pinned command-line tools directly from Google and verifies the archive
checksum before using `sdkmanager` to install the selected SDK/NDK packages.
The build uses the `Sources` Makefile's
`troubleshooter` target:

```sh
make -C Sources troubleshooter
```

The workflow supplies the SDK/NDK paths and build-tool commands expected by the
Makefiles. The native binary targets Android API 19 on ARMv7, and the Manager
APK retains the repository's Android API 19 minimum. API 30 is the compile-time
Android platform, not a change to the supported head-unit software.

## Signing and repeat builds

Each run generates a fresh local APK signing key using the existing Manager
build process. The private key is not included in the downloadable artifact.
Consequently, the APK signature and resulting installer bytes can differ between
runs of the same source commit. This workflow does not promise reproducible
bytes or a byte-for-byte match with the upstream committed installer.

A fresh signing key is also not the upstream APK signing identity. Do not treat
this build as an APK signed by the upstream publisher or assume that normal
Android APK updates will accept it over an existing installation with another
signing key. This workflow does not test installation or upgrades on a vehicle.
