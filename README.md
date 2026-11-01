# SevenUP — iOS 16.1 on iPhone 7

A terminal-based research tool for running **iOS 16.1 (20B82)** on the
**iPhone 7 Global, iPhone9,1 / D10AP**. It prepares the boot chain, reconstructs
the ported kernel, deploys an iPad-based root filesystem and Cryptex contents,
and applies the compatibility files used by the development device.

**macOS is required. Tested only on macOS 26.4.1 running on an Apple Silicon
Mac. Intel/x86 Macs and Hackintosh systems have not been tested.**

> **Highly experimental. For personal research only, not daily use.**
> Do not store sensitive personal information, important accounts or irreplaceable
> files on the device. This is intended for experienced users familiar with DFU,
> SSH ramdisks, APFS, firmware restoration and command-line troubleshooting.
> **Users without that background should not attempt this procedure.**
>
> **Do not set a device passcode, including during Setup Assistant.**
> SEP support is partial. Passcode operations can hang or restart the device.
>
> The iOS 16 system volume uses **disk1s8**, but the Data volume is shared with
> the original installation. This is **not an isolated dual-boot setup**.
> Do not boot iOS 15 again after iOS 16 has migrated that Data volume.

## Project status

The development iPhone has booted to SpringBoard and a substantial part of the
hardware is working. This is a research port with known failures, not a complete
or Apple-supported iOS upgrade. The author has reported a successful clean
end-to-end installation using a copy of the project at a different location.
This does not establish compatibility beyond the tested configuration.

The kernel rebuilder reproduces the accepted HC3 raw kernel and compressed
IM4P byte-for-byte from verified firmware inputs. See [KERNEL.md](docs/KERNEL.md).
Rootfs compatibility files are reconstructed from the two supplied IPSWs,
original D10 resources captured from the phone, and bundled transformation
recipes. No external research directory or user configuration file is required.
See [release preparation](docs/RELEASING.md) for remaining release qualification.

## Contents

- [Supported configuration](#supported-configuration)
- [Feature status and limitations](#what-works-and-what-does-not)
- [Disclaimer and responsibility](#disclaimer-and-responsibility)
- [Host requirements](#host-requirements-and-dependencies)
- [Firmware inputs](#firmware-inputs)
- [Installing iOS 16.1](#installing-ios-161)
- [Test-session commands](#everyday-test-session-commands)
- [Optional Tips persistence helper](#optional-install-the-trollstore-persistence-helper-in-tips)
- [Troubleshooting and recovery](#troubleshooting-and-recovery)
- [Cleanup and layout](#cleanup-and-project-layout)
- [Development and release preparation](#development-testing-and-release-preparation)
- [Credits and licensing](#credits-and-licensing)

## Supported configuration

| Component | Required configuration |
| --- | --- |
| Device | iPhone 7 Global — **iPhone9,1 / D10AP**, A10 |
| Stock starting system | Freshly restored **iOS 15.8.8 / 19H422**, activated, no passcode |
| Target system | **iOS 16.1 / 20B82**, using the pinned iPad7,5 / J71b resources |
| Additional donor | Pinned iPhone 8 iOS 16.1 / 20B82 resources |
| Initial SSHRD | iPhone 7 iOS 15.6 / 19G71 components, fetched automatically |
| Installer SSHRD | iOS 16.1 / 20B82, using D10 bootloaders and DeviceTree |
| Target system volume | **/dev/disk1s8**, mounted as **/mnt8** in SSHRD |
| Host | **macOS required**; tested only on **macOS 26.4.1 / Apple Silicon**. Intel/x86 Macs and Hackintosh systems are untested |
| Boot method | Computer-assisted DFU boot **after every restart or power loss** |

GSM models and iPhone 7 Plus are not supported by this workflow. Other firmware
builds, donor combinations and host architectures have not been qualified.
Do not substitute them into the pinned build.

## What works, and what does not

“Working” means observed on the development device. It is not a compatibility
or reliability guarantee for every application or every device.

| Feature | Current status |
| --- | --- |
| Display, GPU acceleration, touch and system UI | Working on the development device |
| USB device connection and optional root SSH | Working; OTG/storage accessories remain unqualified |
| Wi-Fi and Bluetooth | Working |
| Speaker and Bluetooth audio playback | Working |
| Microphone and Voice Memos | Working; Voice Memos can record audio |
| Siri and keyboard dictation | Problematic; not considered working reliably |
| Camera preview and QR/barcode scanning | Working in tested applications |
| Still photography | Works with **Settings → Camera → Formats → Most Compatible** |
| Camera video recording | **Not working**; AVE/video-encoding support is not operational |
| High Efficiency capture and panorama | Unresolved; capture/save failures or app crashes may occur |
| Vibration / haptics | Working |
| Pressure-sensitive physical Home button | **Not working**; use AssistiveTouch |
| Accelerometer, gyroscope and gravity data | Observed working |
| Compass and location | Observed working; broader accuracy and reliability tests remain pending |
| Battery percentage and charging information | Restored; some third-party diagnostic fields may be incomplete |
| Standby and battery life | **Unresolved**; severe overnight drain has been observed |
| SEP | **Partial support only**; not a complete passcode/data-protection implementation |
| Device passcode | **Do not configure it**; setting one can hang or restart the device |
| Touch ID | Fingerprint enrollment was observed; unlocking and authentication are not validated |
| Adding VPN configurations | Currently blocked by the ACM/SEP local-authentication failure |
| App Store | Third-party download, installation and launch have been observed working |
| Removable built-in apps carried over from iOS 15 | Some may crash; delete and download them again from the App Store |
| Cellular / baseband | **Not researched or validated**; see the explanation below |
| Health, alarms, timers and Sleep-related features | Not qualified; the current patch set retains disabled healthd/mobiletimerd jobs |

### Why cellular/baseband is not supported

The author has not investigated baseband support. The development phone has
faulty cellular/SIM-related hardware, preventing meaningful cellular testing.
iPhone 7 devices also use **two different baseband hardware variants**. The
author does not have a GSM device and **has not tested the GSM variant**.

Consequently, this project makes no claim about calls, SMS, cellular data or
compatibility with either baseband variant. The software currently accepts
only the Global iPhone9,1 configuration listed above. This limitation is not a
claim that all baseband variants have the same software defect.

See [KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) for details about partial SEP support,
VPN, camera encoding, Siri/dictation and standby power.

## Disclaimer and responsibility

This project is provided **AS IS**, without warranty, under the terms of the
included [license](LICENSE). It is an independent research project, not an
Apple product or a supported upgrade procedure.

- Use only a device you own or are authorized to modify. Begin with a freshly
  restored, activated phone containing no important data or restored backup.
- Formatting, repartitioning and migration can permanently destroy data. A
  mistake, disconnect, failed write or incompatible input may require a full
  restore. Individual `.bak` files are not a whole-device recovery plan.
- The port changes kernel behavior and parts of the operating system's trust
  and enforcement mechanisms. Do not assume stock iOS security, data protection,
  device-management, banking or authentication guarantees.
- Use it only for personal research. **Do not use it as a daily driver or rely
  on it for emergency communication. Do not store sensitive personal information.**
- You are responsible for understanding the commands, confirming the device and
  partitions, and knowing how to recover the phone with a computer.
- The tool does not perform the initial stock restore or supply activation
  records. Activate the stock system normally before starting.
- Obtain Apple firmware and third-party dependencies yourself. This repository
  does not grant redistribution rights to Apple software or third-party binaries.

## Host requirements and dependencies

**Use a reliable USB-A connection for every `pwn` operation. Do not use a direct
USB-C-to-Lightning connection for these steps.** A USB-C hub/dock connected to
the Mac, with the phone attached through its **USB-A port** using a reliable
USB-A-to-Lightning cable, is acceptable. If you are unsure which stages can use
USB-C and which cannot, **keep using the reliable USB-A connection throughout
the entire procedure**.

- **macOS is required.** The only tested host configuration is **macOS 26.4.1
  on an Apple Silicon Mac**. Intel/x86 Macs, Hackintosh systems and other macOS
  versions have not been tested; compatibility is not established.
- Python **3.10+** and a reliable USB data cable.
- Full Xcode with the iPhoneOS SDK, plus the accepted `ld64.lld` linker/toolchain.
  Exact kernel reconstruction is sensitive to compiler output; the recorded
  environment is in [toolchain-reference.json](profiles/toolchain-reference.json).
- Enough free host storage for two full IPSWs, extracted images, temporary DMGs,
  kernel checkpoints and output bundles. Plan for tens of gigabytes; a universal
  peak-space minimum has not been established.
- Enough free device storage for the additional rootfs and installation staging.
- Host tools use the project-local `Darwin/` directory. Most are included;
  four upstream-only tools are downloaded automatically on first use:

```text
irecovery       gaster          img4             img4tool
iBoot64Patcher  KPlooshFinder   Kernel64Patcher3 kerneldiff
gtar            iproxy          sshpass          pzb
ld64.lld
```

macOS `hdiutil`, `ssh`, `scp`, `curl` and `codesign` are also used. The Python CLI
uses the standard library. The AssistiveTouch libimobiledevice/libplist libraries
and their non-system dependencies are bundled under `Darwin/lib/lockdown/`.
A separate Homebrew installation is not required. The linker uses project-local
libraries; its large LLVM library is stored compressed and unpacked automatically
on first use (including `doctor`). Xcode and its iPhoneOS SDK are not bundled.

See [resources/README.md](resources/README.md) and
[Darwin/README.md](Darwin/README.md) for the resource layout and notices.
The current bundle targets Apple Silicon; other host architectures are untested.

From the project directory, run:

```sh
./run.sh doctor
```

`doctor` checks tool availability, downloads any missing upstream-only inputs
from their pinned commits, and loads the AssistiveTouch libraries and required
APIs. Internet access to GitHub is required for that initial download; later
uses verify and reuse the local files. It does not connect to, boot or modify a phone. Passing it does
not prove that a full kernel rebuild or a device installation will succeed.

## Firmware inputs

Place these two IPSWs in `inputs/ipsw/`, keeping the pinned filenames:

| Required IPSW | Purpose |
| --- | --- |
| `iPad_64bit_TouchID_ASTC_16.1_20B82_Restore.ipsw` | iPad rootfs, Cryptex and target kernel resources |
| `iPhone_4.7_P3_16.1_20B82_Restore.ipsw` | iPhone 8 donor resources |

A full iPhone 7 **15.6 IPSW is not required**: the bootstrap stage retrieves the
necessary components from the pinned Apple archive. A 15.8.8 iPhone 7 IPSW is
not required by the tool: the stock D10 hardware resources are collected from
the phone during `capture`. Restoring the physical phone to 15.8.8 first is
mandatory and is performed outside this tool.

Inputs are selected by [sources.lock.json](profiles/sources.lock.json). Complete
IPSWs are checked against their pinned size, MD5/SHA1 and build identity, with
SHA256 recorded. Partial downloads check the pinned manifest and component
digests; they do not claim verification of an entire un-downloaded IPSW.

No `local.json`, external `mywork/` tree or author-specific paths are used.
The pinned SSHRD archive and upstream temporary A10 bootstrap preset are fetched
automatically into ignored `resources/sshrd/` paths on first use.
`profiles/dependencies.lock.json` records immutable URLs, sizes and SHA256 values.
Four upstream-only host tools are fetched into ignored `Darwin/` paths in the
same way; no configuration or manual download is needed. The bootstrap preset is not your device ticket.
`capture` later collects the original SEP and actual-device IM4M from Preboot,
plus the original D10 audio, touch, camera and wireless files needed by the port.
Those device-specific/generated inputs remain private under `work/`.

## Installing iOS 16.1

Run the following stages in order. Device-state notes are part of the procedure;
do not paste every block into a shell at once. If a command fails, stop and
inspect its error before proceeding. Details are in [INSTALL.md](docs/INSTALL.md).

### 1. Restore, activate and confirm the stock phone

Restore the supported Global iPhone 7 to **15.8.8 / 19H422** with your usual
restoration software. Activate it and finish its stock setup. Leave the passcode
disabled, do not restore personal data, and ensure you can restore it again.

```sh
./run.sh start
```

The tool asks you to confirm the model, stock version, activation, absence of a
passcode and important data, recovery readiness and experimental limitations
**individually**. `start` then verifies/extracts firmware resources; it does not
boot or repartition the phone. Confirmations expire after 24 hours. To renew
only the confirmations, use `./run.sh confirm`.

### 2. Build and boot the 15.6 bootstrap SSHRD

Put the same phone in **DFU mode** before `build bootstrap`.
Use the USB-A connection described above: both bootstrap preparation and boot
commands include a `gaster pwn` step.

```sh
./run.sh fetch-bootstrap
./run.sh kernel-build
./run.sh build bootstrap
./run.sh boot bootstrap
```

`fetch-bootstrap` is host-only and is also called automatically when needed.
`kernel-build` reconstructs the accepted kernel from firmware sources. Both
build and boot stages requiring DFU have their own explicit confirmation.

Wait until the bootstrap SSHRD is responsive, then collect the stock SEP/ticket
and D10 hardware resources:

```sh
./run.sh capture
```

This stage explicitly runs `/usr/bin/mount_filesystems` in the **15.6 bootstrap
SSHRD**, reads the stock build and selects the ticket-matched Preboot SEP image.
It also copies the pinned original D10 resources from `/mnt1` onto the Mac.
It then offers reboot; either answer saves the result and exits. Reboot is
scheduled after SSH disconnects, without waiting for the device to reconnect.

### 3. Build and boot the 16.1 installer SSHRD

```sh
./run.sh build ios16-sshrd
# Manually enter DFU on the same phone again.
./run.sh boot ios16-sshrd
```

This retains D10 bootloader/DeviceTree payloads and uses the collected SEP/IM4M
and exact ported kernel. Wait for SSHRD to become responsive.

**Do not run `mount_filesystems` in this phase before rootfs installation.**
The APFS container's volumes must be unmounted for `apfs_invert`; the installer
handles its own required mounts and unmounts.

### 4. Prepare the rootfs, Cryptex archives and compatibility files

On the Mac:

```sh
./run.sh prepare-install
```

This command reconstructs and packages all 667 compatibility files, builds a raw
APFS `root.dmg`, and archives both Cryptex images. Sources are the supplied IPSWs,
captured stock D10 files and bundled resources/deltas; the final file hashes
must match the working port. It does not write to the phone. To prepare only
the compatibility archives, use `./run.sh prepare-rootfs-patches`. The older
`import-rootfs-patches` name remains an alias for the same standalone workflow.

### 5. Deploy the system in the 16.1 SSHRD

For an explicit, step-by-step installation:

```sh
./run.sh install rootfs
./run.sh install cryptex
./run.sh install patches
./run.sh install preboot
```

`./run.sh install all` combines these four phases. It does **not** include
`finalize` or the optional Tips helper installation.

The rootfs step creates **disk1s8**. If additional volumes already exist at s8 or
above, it lists them and requires a volume-specific deletion confirmation before
recreating s8. This can delete an earlier port installation. The seven stock
volumes are excluded from deletion, but that does not make shared Data migration
reversible.

The installer uploads `root.dmg`, unmounts the container and runs `apfs_invert`,
then extracts both Cryptex archives, installs compatibility files and prepares
Preboot. Original replaced files are preserved as `.bak`; an existing conflicting
backup stops the relevant operation. Uploaded files are not rehashed on the phone.

Choose **yes** to the recommended full-system SSH option for the first test.
Device port is **22**, forwarded to host port **2222** by default. Installing SSH
does not reset or clear the existing root password.

If you already have your own iproxy running, append `--existing-forward` to the
relevant SSH/capture/install command. Otherwise, the tool starts and stops its
own forward. It leaves user-owned forwarding processes untouched.

### 6. Prepare full-iOS boot and disable the old stock boot path

```sh
./run.sh build ios16
./run.sh install finalize
```

The full-system iBEC selects **rd=disk1s8**. The separate `output/ios16/` bundle
retains the verified kernel and other required images; it loads **no AVE image
and no ramdisk**.

`install finalize` requires completed deployment and a prepared full-iOS bundle.
It preserves supported stock kernelcache copies as `kernelcache.bak`, records
their paths, then offers reboot and exits. **Do not restore the old stock boot
path and boot iOS 15 after Data has migrated.** Use a fresh restore to return to
stock iOS instead.

### 7. Boot iOS 16 and complete Setup Assistant

Manually put the phone in **DFU mode**, then run:

```sh
./run.sh boot ios16
```

This runs `gaster pwn` and `gaster reset`, sends iBSS/iBEC, then loads DeviceTree,
TrustCache, SEP and the kernel. Successful `bootx` handoff is not proof that the
system has finished starting. Allow first-boot migration to complete.

Complete activation/Setup Assistant normally. **Do not configure a passcode**:
choose **Passcode Options → Don't Use Passcode**. Skip Touch ID setup when it
requires a passcode. Leave the device without a passcode after setup as well.

The physical Home button does not work. Once full iOS is running and visible
over USB, enable the floating Home button from the Mac:

```sh
./run.sh assistive-touch
```

This uses USB lockdown, not SSH or iproxy. It checks the connected device and
reads the enabled setting back. With multiple USB devices connected, disconnect
the others or specify `--udid`.

For removable built-in apps that crash after migration, delete the affected app
and download its iOS 16 version again from the App Store. Voice Memos recording
and camera video encoding are separate paths: a working microphone does not
mean video recording, Siri or dictation is fixed.

For still photos, select **Settings → Camera → Formats → Most Compatible**.
Camera video recording and High Efficiency capture remain unsupported.

## Everyday test-session commands

```sh
./run.sh boot ios16          # Same phone in DFU; required after each restart
./run.sh assistive-touch     # Full iOS running; enable floating Home
./run.sh ssh                 # Root shell over USB
./run.sh status              # Local completed-stage timestamps
```

The SSH client initially tries `root / alpine`. On an authentication rejection,
it asks for a hidden password and retries. The entered password is kept only
for that CLI invocation and is not written to configuration or logs.
There is no password configuration file. Password-management utilities are not
installed by this workflow.

Project SSH/SCP connections address USB-forwarded `127.0.0.1` and accept changing
host keys across ramdisk rebuilds and full-iOS boots. This is deliberately scoped
to the local USB workflow; it does not alter your global SSH configuration.
`--system` remains an accepted compatibility flag. Native SSH shell commands and
session output are not recorded by the interactive-shell command.

## Optional: install the TrollStore persistence helper in Tips

Boot the **16.1 SSHRD** again and manually mount Data at **/mnt2**. Then:

```sh
./run.sh install trollstore
```

The command searches the real container UUID at:

```text
/mnt2/containers/Bundle/Application/<UUID>/Tips.app/Tips
```

It downloads the pinned
[TrollStore 2.1.1 embedded persistence helper](https://github.com/opa334/TrollStore/releases/download/2.1.1/PersistenceHelper_Embedded),
keeps `Tips.bak` and replaces only the Tips executable. Open Tips after booting
iOS to use the helper's TrollStore installation function. Installing the helper
does not automatically install TrollStore or make this port untethered.

If Tips is missing, the tool tells you to boot iOS and install Tips from the
App Store, then exits. If Data is unmounted, it asks you to mount it first.
For a Data-mount error **after rootfs installation is complete**, open an SSHRD
shell from the Mac:

```sh
./run.sh ssh
```

Inside that SSHRD shell, run:

```sh
/usr/bin/mount_filesystems
exit
```

Then rerun `./run.sh install trollstore` on the Mac. The bundled command is
`mount_filesystems`, not `run_filesystems`. **Do not run it before
`./run.sh install rootfs`**: rootfs inversion needs the container unmounted.

This optional command never calls `mount_filesystems` or mounts Data automatically.
An existing `Tips.bak` is not overwritten. Add `--existing-forward` if appropriate.

## Troubleshooting and recovery

| Situation | Action |
| --- | --- |
| Missing tools/libraries | Run `doctor`, populate `Darwin/`, and review the dependency instructions |
| Kernel hash mismatch | Stop; check the pinned inputs and toolchain rather than bypassing the check |
| Port 2222 already occupied | Use `--existing-forward` for your existing iproxy, or select `--port 2223` |
| Wrong SSH password | Enter the current password at the hidden prompt; SSHRD/full iOS may differ |
| Install fails after rootfs creation | Fix the reported error and rerun the unfinished phase; do not recreate rootfs unnecessarily |
| A `.bak` already exists | Inspect the earlier installation; do not overwrite the preserved original blindly |
| Black screen, hang or power loss | Re-enter DFU and boot the accepted bundle; use a fresh restore if recovery is needed |
| Built-in removable app crashes | Delete it and download it again from the App Store |
| VPN returns from Settings without saving | Known partial-SEP/ACM issue; see KNOWN_ISSUES.md |

Preserve `logs/last-command.json` and the relevant stage receipt when reporting
an error. Redact device identifiers, account information, tickets and private
network configuration. Do not post complete diagnostic archives publicly.

The tool does not provide a one-command Data downgrade or general rollback.
After migration, returning to stock iOS means a **fresh restore**, not simply
selecting the old system volume. OTA updates are not a supported upgrade path
for this port.

## Cleanup and project layout

```sh
./run.sh clean              # Removes disposable installation files, logs and Python caches
./run.sh clean --install    # Removes installation media/rootfs archives only; keeps logs
./run.sh clean --all        # ALSO DELETES boot bundles, all generated state and IPSW archives
```

Default `clean` preserves `output/`, boot/build resources, captured SEP/IM4M and
D10 files, IPSWs and the device/installation state required for subsequent boots.
If full-iOS preparation was completed, `./run.sh boot ios16` remains available
after cleaning; enter DFU and use USB-A as usual. Prerequisite confirmations may
still need renewal with `./run.sh confirm`. To recreate installation media, run
`./run.sh prepare-install` again. `--install` additionally preserves logs and
Python caches.

**`clean --all` deletes the boot chain, captured device resources, progress and
IPSW archives. You cannot boot using those deleted bundles afterward.** Back up
anything you intend to keep before running it. For a completely fresh test,
use `--all`, put the two IPSWs back in `inputs/ipsw/`, and restart from
`./run.sh start`. Source, bundled resources, Darwin tools and licenses are kept
in every mode. These commands only clean the Mac project; they do not erase the phone.

```text
inputs/ipsw/       User-provided firmware archives
profiles/         Pinned firmware, ABI metadata and accepted kernel hashes
Darwin/           Bundled macOS tools, libraries and third-party notices
src/iphone7_port/ Python CLI and transformation code
resources/        Helpers, fixed SSHRD inputs and compact rootfs deltas
tools/            Host-side tool import utilities
docs/             Installation, known issues and release documentation
tests/            Host regression and transformation tests
work/             Private inputs, tickets, state, caches and intermediate files
output/           Generated device-specific boot bundles
logs/             Private command logs
```

Keep `work/`, `output/` and `logs/` private. Legacy `local.json` files are ignored. Do not publish IPSWs,
Apple kernels/rootfs/Cryptex contents, SEP firmware, IM4M tickets, host private
keys, pairing or activation records, device identifiers or account data.

## Development, testing and release preparation

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
# Host-only exact-kernel rebuild acceptance:
PYTHONPATH=src python3 tests/accept_kernel_rebuild.py
# Relocated rootfs rebuild acceptance after capture and prepare:
python3 tests/accept_rootfs_rebuild.py
```

Host tests do not replace a fresh phone installation. The release test should
cover the entire restore-to-Setup-Assistant workflow, repeated computer-assisted
boot, SSH, AssistiveTouch and the explicitly documented hardware behavior.
See [RELEASING.md](docs/RELEASING.md), [WORKFLOW.md](docs/WORKFLOW.md),
[INSTALL.md](docs/INSTALL.md) and the historical [validation notes](docs/VALIDATION.md).

Useful contributions include reproducible diagnosis, compatibility work,
maintainable firmware transformation recipes and clearer recovery documentation. Include
the model, build, command and redacted error in a report; distinguish previously
working hardware from untested hardware.

## Credits and licensing

- [verygenericname/SSHRD_Script](https://github.com/verygenericname/SSHRD_Script)
  for the SSHRD workflow on which this orchestration is based.
- [palera1n/PongoOS](https://github.com/palera1n/PongoOS) for related rootful/KPF work.
- [libimobiledevice](https://github.com/libimobiledevice/libimobiledevice), libplist
  and libusbmuxd for host/device communication.
- [opa334/TrollStore](https://github.com/opa334/TrollStore) for the optional embedded
  persistence helper.
- The authors of gaster, img4/img4tool, iBoot64Patcher, KPlooshFinder,
  Kernel64Patcher3, kerneldiff, Dropbear, GNU tar and LLVM/LLD.

The upstream SSHRD_Script BSD-3-Clause notice is preserved in [LICENSE](LICENSE).
Dependencies retain their own licenses; the project license does not relicense
them. See [THIRD_PARTY.md](THIRD_PARTY.md) for the component inventory, preserved
license texts, source/build references, runtime-download exclusions and the
remaining Kernel64Patcher3 source-revision limitation. Apple firmware is
user-supplied and is not licensed for redistribution by this repository.
