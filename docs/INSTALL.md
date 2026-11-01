# Rootfs installation in the 16.1 SSHRD

All commands are run from the project directory. Firmware preparation remains
host-only. No installer command calls `mount_filesystems`, boots full iOS,
or changes Setup flags. The separate `finalize` step backs up the stock
kernelcache and offers reboot after installation. `install trollstore` is an
optional separate Data-volume operation for the Tips persistence helper.

## Prepare on the Mac

After `prepare` has verified/extracted the IPSWs and `capture` has collected
the original D10 resources from the 15.8.8 phone:

```sh
./run.sh prepare-install
```

The installer uses the pinned iPad 16.1/20B82 rootfs and both matching Cryptex
images. It converts the OS image to a temporary UDRW file, copies exactly the
APFS partition described by its partition table, and discards the outer GPT/MBR.
`root.dmg` must start with NXSB at byte 32, have 4096-byte blocks, and have the
exact container length in its superblock. A whole uncompressed GPT disk image
is rejected. Temporary UDRW data is removed after copying; the source is retained.

Both Cryptex images are mounted read-only on the Mac, archived from their root
with numeric root:wheel ownership, without macOS xattrs/ACLs or AppleDouble
sidecars, and detached. Archives contain `System/` and `usr/` directly, never a
`Volumes/...` wrapper. File modes and safe relative symlinks are preserved.
Preparation checks names, duplicates, member types and symlink traversal.
Final sizes, SHA256 values and archive inventories are recorded in
`work/install-media/media.json`.

No install helper is built or uploaded. Uploaded files are not rehashed or
size-checked on the phone. Preparation still checks local firmware sources;
installation relies on SCP/tar/apfs_invert return codes and stops on failure.

## Standalone rootfs compatibility files

`prepare-install` also reconstructs the compatibility archives. To prepare only
those archives, run:

```sh
./run.sh prepare-rootfs-patches
```

`import-rootfs-patches` is a compatibility alias for the same command. Neither
command accepts an external research directory or reads a local configuration.
All 667 output hashes remain pinned by `profiles/rootfs-reference.json`.
`profiles/rootfs-recipes.json` specifies the original firmware/captured source
for each file and the applicable transformation:

- 645 files are copied unchanged from verified firmware, captured stock D10
  resources or the bundled SSH archive.
- 17 files are reconstructed using compact delta records in `resources/rootfs/`.
  The original files come from firmware; complete modified Apple executables
  are not stored as repository assets.
- Five helper/service/profile files are project resources.

The stock D10 inputs are collected during bootstrap `capture`, after confirming
that `/mnt1` contains 15.8.8 / 19H422. They include audio tunings, touch properties,
camera configuration and wireless files. No third full IPSW is required.
Missing or mismatched stock inputs stop preparation and ask for capture.
Firmware images are mounted read-only on the Mac. Generated source caches,
reconstructed files and patch archives remain under ignored `work/`.

The final selection includes PM1 normal migration with status text, CL1 only
for CoreLocation migration, WD1, NR1 `.09`, TH1 `.11`, SC3 `.27.dylddata`, CM1
location, TF1 touch, D10 audio/camera resources, keyboard/Control Center/iPhone
UI resources, wallpapers, final WL3 wireless compatibility, original H2,
the matching SystemApp catalog/signatures, and optional SSH2 tools/services.
It excludes the abandoned broad migration skips, headless backboardd changes,
failed driver transplants and intermediate wireless loaders.

Healthd and mobiletimerd retain the prior TH1 disabled state. Alarm/timer and
Sleep-framework functionality must not be advertised as validated.
The original 503 Apple jobs remain in the no-SSH cache; the SSH variant retains
the three final System/Interactive SSH2 jobs and the known-working detached
signature. The no-SSH variant removes only those three added jobs and signs the
revised cache on the Mac.

## Install

If the phone has already reached the 16.1 SSHRD and you want to repeat only
install-resource preparation, run `./run.sh clean --install`, then
`./run.sh prepare-install`. This retains the captured SEP/IM4M, both SSHRD
builds, extracted IPSW components and earlier progress. Default `clean` also
preserves these boot resources and state, but removes logs and Python caches.
Only `clean --all` resets the entire local workflow, deletes the boot bundles
and captured resources, and removes the IPSW archives.

Boot the prepared 16.1 SSHRD. **Do not run mount_filesystems.** If volumes are
already mounted, the installer unmounts each container volume individually and
refuses to proceed after any failed unmount. It does not force-unmount volumes.

```sh
./run.sh install
# If your own iproxy already listens on 2222:
./run.sh install --existing-forward
```

The flow is:

1. Read the prepared media receipt. The standalone `rootfs` step requires only
   root.dmg and does not rehash it or require the patch/helper packages. The first
   remote command is `/usr/bin/sw_vers`; require ProductVersion 16.1 and
   BuildVersion 20B82 before prompting for SSH or uploading any file. Check
   the ramdisk root (`/dev/md*`, or the generated SSHRD's `root_device` HFS
   alias), live D10 model/ECID, disk0s1-to-disk1 relationship,
   the seven stock volume roles.
   Registry queries use normal `ioreg -l -w 0` output, since the bundled
   SSHRD ioreg's `-a` archive mode fails with "can't open file". The host parser
   strips terminal colors and retains only the fields needed by installation.
2. Offer full-system SSH, default yes. `--without-ssh` explicitly omits it.
   Setup Assistant can be completed normally, without a passcode.
3. If disk1s8 or higher exists, print every affected name/role/UUID and require
   a token such as `DELETE disk1s9 disk1s8`. Refusal cancels installation.
   With only stock volumes, require `INSTALL DISK1S8` before creation.
4. Unmount all container volumes. Delete only indices 8 and above, highest
   first, using the detected `apfs_deletefs <device>` utility. Check the registry
   after every deletion. Stock disk1s1 through disk1s7 are never deletion targets.
5. Run `/sbin/newfs_apfs -A -D -o role=r -v Xystem /dev/disk0s1`. Require exactly
   disk1s1 through disk1s8 and confirm the new recovery-role Xystem volume.
6. Mount disk1s8 on /mnt8 and upload root.dmg by SCP. On SCP success, sync and
   unmount every disk0s1/disk1 volume. There is no helper upload, remote hash,
   file-size check or free-space query in this phase. SCP/invert errors stop it.
7. Run `/System/Library/Filesystems/apfs.fs/apfs_invert -d /dev/disk0s1 -s 8 -n root.dmg`.
   Stop on failure. Mount /mnt8 again, verify 16.1/20B82, and record container/volume
   UUIDs plus a random installation marker for subsequent steps.
8. Upload each Cryptex archive to /mnt8 and directly extract it using
   `tar -zxpf archive -C /mnt8`.
   Rootfs contains native framework-directory links into Cryptex. Preserve those
   links as adjacent `.bak` files and create physical directories in their place
   before extraction, rather than rejecting the native layout or following links
   outside /mnt8. Existing uploaded archives are reused on retry; no device-side
   hash or size check is added. Remove only the uploaded
   temporary archives, then run `chown -R -h root:wheel /mnt8/System /mnt8/usr`.
9. Extract the prepared rootfs patch archive and install its files. Keep each
   original as `filename.bak`. DriverKit backups are moved outside the signed
   bundle under `/usr/local/share/iphone7-ios16-backups/` with `.bak` names,
   because extra backup files inside a sealed bundle invalidate its resources.
   Existing backups or redirected destination parents stop installation.
10. For SSH, generate a new ECDSA host key on the phone using SSHRD dropbearkey;
    never import/export an old private key. The key is root:wheel/0600. Root's
    account/password are unchanged. The job listens on device port 22.
11. Mount only Preboot disk1s6 on /mnt6. Use the captured device ticket hash to
    select the existing firmware directory, which must contain sep-firmware.img4.
    No hash is guessed and no empty replacement firmware directory is fabricated.
    Create OS/App Cryptex compatibility links to rootfs `System/Library`,
    `System/DriverKit`, `usr/lib`, `usr/libexec`, `usr/bin`, `usr/sbin` and
    `usr/share`; preserve all stock firmware.
    Links contain runtime absolute paths, never `/mnt8` host/ramdisk paths.
12. Leave the phone in SSHRD. No automatic reboot is performed.

Each complete phase has its own state receipt. After a later failure, rerun the
specific unfinished step instead of recreating the root volume:

```sh
./run.sh install rootfs   # DESTRUCTIVE: begins a new installation, with confirmation
./run.sh install cryptex
./run.sh install patches
./run.sh install preboot
```

## Finalize and boot full iOS

After all four deployment phases succeed, prepare the full-system boot bundle
on the Mac first:

```sh
./run.sh build ios16
./run.sh install finalize
# Or reuse a user-owned iproxy:
./run.sh install finalize --existing-forward
```

This is a separate step, not part of `install all` or `install preboot`. It
requires the current installation's Cryptex, patch and Preboot receipts and a
complete device-matched full-iOS boot bundle. It does not need to recheck or
upload the installation media.

Finalization uses mounted Preboot `/mnt6` and mounts only stock System
`disk1s1` on `/mnt1` if needed. It checks these exact locations:

```text
/mnt1/System/Library/Caches/com.apple.kernelcaches/kernelcache
/mnt6/<captured-device-ticket-hash>/System/Library/Caches/com.apple.kernelcaches/kernelcache
```

Every existing stock copy is renamed to adjacent `kernelcache.bak`. Backups
are never overwritten. A backup-only path is accepted on retry; an original
and backup together, symbolic paths, or no supported kernelcache path cause
an error. All conflicts are checked before the first rename. No Data mount,
file upload or device-side file hash is involved. The original/backup paths
are recorded in `install-finalize`; a stock System mount created by this step
is unmounted afterward. Pre-existing mounts are retained.

The terminal then asks `Reboot the iPhone now? [y/N]:`. Either answer reports
completion and exits. Yes schedules a detached reboot after SSH exits; the
tool never waits for the phone to return. If submission itself fails (for
example, authentication or connection refusal), the real error is still shown.

Enter DFU manually on the same phone, then:

```sh
./run.sh boot ios16
```

This uses the separate `output/ios16/` bundle with `rd=disk1s8`. Only the D10
iBEC boot arguments change; iBSS, DeviceTree, TrustCache, SEP and the exact HC3
kernel are copied unchanged from the device-ticketed 16.1 SSHRD bundle.
The retained stock `iBEC.dec` must reproduce the bootstrap iBEC before it is
used. No new DFU decryption is required to build this bundle.

After iBSS/iBEC and `go`, the send/load order follows the tested bootchain:
DeviceTree → TrustCache → SEP → Kernel / `bootx`. AVE and ramdisk are omitted.
Boot commands completing proves handoff only; allow migration to finish before
testing SSH. Normal reboot cannot automatically start the port, and stock iOS15
must not be booted after the shared Data volume has migrated. For deliberate
recovery before migration, the recorded `.bak` files can be renamed back in
SSHRD; after migration, use a fresh restore instead of booting stock iOS15.

Rerunning a completed Cryptex/patch phase is refused. A partially installed patch
set is retained with its backups for inspection rather than automatically rolled
back or deleted. Container UUID, volume UUID and marker must match on resumed
steps. Concurrent installation/preparation is locked; clean refuses the active
lock. No additional device-side file verification or free-space probes run.

SCP uses a Mac-only SSH transport wrapper so the foreground scp process can
display its native progress meter. No helper is uploaded to the phone. Recovery
transfers, newfs/invert and Cryptex extraction stream output live; failed scripts
and action labels are recorded privately in logs/last-command.json.

First full-iOS connection after installing its SSH server:

```sh
./run.sh ssh --system
```

Both SSH modes now accept changing USB host keys without reading known-hosts
files. `--system` is retained for compatibility. Complete activation and Setup
Assistant normally, choosing Don't Use Passcode. Do not set a passcode later.
To enable the floating Home button over USB lockdown, run
`./run.sh assistive-touch`; SSH and iproxy are not required for that command.

## Optional persistence helper in SSHRD

Run `./run.sh install trollstore` after mounting Data on `/mnt2` yourself.
Use `--existing-forward` if your own iproxy is already listening. The command
verifies the 16.1 SSHRD, searches the real Data container UUID for
`/mnt2/containers/Bundle/Application/*/Tips.app/Tips`, and stops with an
installation reminder if Tips is missing. It does not mount Data automatically.

The helper comes from the fixed upstream TrollStore 2.1.1 URL, cached privately
under `work/downloads/trollstore-2.1.1/`. The original executable is renamed to
`Tips.bak` only after upload succeeds. The helper keeps its upstream signature
and is installed executable with mode 0755 and owner 33:33, matching the upstream
persistence-helper installer. A conflicting backup is never overwritten.
No other application files are replaced. Opening Tips in full iOS starts the
embedded helper, which can then install TrollStore at the user's request.

SSH, SCP and installation scripts now prompt for a hidden password after an
authentication rejection. Credentials remain in memory for the current CLI
invocation only. Ordinary remote/file errors are not retried as password errors.
