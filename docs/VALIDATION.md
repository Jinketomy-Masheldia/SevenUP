# Development validation, 2026-11-01

This file preserves historical milestone reports. Older pending/untested notes
describe the state at that milestone, not the latest support claim. Current
functional limitations and the planned repeat release test are documented in
README.md, KNOWN_ISSUES.md and RELEASING.md. The development phone has since
booted full iOS16, connected through SSH, and enabled AssistiveTouch. Complete
activation/Setup Assistant normally and never configure a device passcode.

All checks below were performed on the Mac. No phone was booted, mounted,
formatted, or modified during this validation.

## Passed

- 35 host regression tests: explicit confirmations and expiration, real device
  identity and ECID binding, IMG4 payload preservation, malformed container
  rejection, Preboot selection, archive traversal checks, component digest
  rejection, partial download caching, cache reuse without additional free
  space, mount failure stopping collection, and incomplete boot bundle rejection.
- Actual iPhone 8 16.1 / 20B82 IPSW: pinned size, MD5, SHA1, product/build and
  erase identity; selected boot, OS, and Cryptex resources extracted and hashed.
- Actual optional iPhone 7 15.8.8 / 19H422 IPSW: pinned size, MD5, SHA1,
  product/build and erase identity. It was not extracted or deployed.
- Automatic 15.6 component-only preparation: seven files downloaded from the
  pinned Apple URL; BuildManifest SHA256 and all six component digests matched.
  No full 15.6 archive was downloaded or required.
- The new bootstrap donor command reproduced the exact 15.6 SSHRD-patched raw
  kernel used in the research. Its SHA256 matched the existing historical lock.
- The new iPhone 8 input command reproduced the exact pristine raw donor.
- Full iPad 16.1 / 20B82 IPSW: pinned archive validation and selected resource
  extraction passed. Its pristine kernel plus one KPlooshFinder pass reproduced
  the historical iPad base.
- Actual 15.6 restore ramdisk rebuilt into a writable HFS+ image, local reviewed
  SSH archive extracted, mount helper and Dropbear present, image detached,
  resized and packed into an IMG4. All mounts were confined to project work.
- Current HC3 reference: full container hashes and raw kernel hash matched.
  Reticketing an actual IMG4 preserved the entire IM4P and decoded kernel bytes.
- Local host dependency discovery and English CLI help.
- All 28 HC3 checkpoints reconstructed from source and full raw hashes matched.
- Fresh empty-workspace acceptance: all kernel inputs and stages rebuilt;
  Python file access and subprocess arguments were guarded against legacy
  research, bootchain, original ramdisk, iPad and iPhone directories. No blocked
  access was attempted. Only the verified extracted IPSW component cache was reused.
- Fresh final raw SHA256:
  `d11e37f4c349d997577894d9f9bc08bcac718a3ee1ce62d1d1c055e47053c168`.
- Fresh compressed IM4P SHA256:
  `5af51daeaf69e737f2288e32b8db05209c3eab64a099f0aec212327d0e18a408`.
- Both img4 and img4tool independently decoded the newly packaged image to the
  exact rebuilt raw bytes. A separate post-build comparison then read the old
  reference and confirmed full raw and full IM4P byte equality. That reference
  was not an input to reconstruction.
- Tool/compiler versions and binary hashes are recorded in
  `profiles/toolchain-reference.json`.
- Terminal color behavior checked for TTY, redirected output and NO_COLOR.
  Optional post-capture reboot tested with mocks: default no, explicit yes,
  failed capture, expected SSH disconnect, and forwarding still active at prompt.
- Project-local tool resolution checked independently of working directory.
  The linker and all nine non-system libraries were copied to a temporary
  location, loaded without Homebrew libraries, and compiled the complete HC3
  observer byte-for-byte identically. No phone was contacted or rebooted.

## Still pending

The first phone capture test exposed a missing /usr/bin/plutil in the 15.6
SSHRD. Stock SystemVersion.plist collection now downloads its original bytes
and parses XML or binary plist on the Mac. Host regression coverage checks both
formats, malformed input rejection, and --already-mounted avoiding a remount.
The user subsequently confirmed capture, both SSHRD boot stages and interactive
SSH on the phone. This is user-reported validation rather than an automated
new full-system installation.

- New phone validation of the destructive rootfs/Cryptex/Preboot installer and
  its installation-specific SSH host-key generation.
- Source-only rootfs patch reconstruction and a locked dependency source bootstrap.
- The remaining full-system boot/finalization stages listed in WORKFLOW.md.

## Rootfs installer validation (2026-11-01)

- `prepare-install` ran on the actual pinned iPad IPSW components on the Mac.
  UDRW conversion and APFS partition extraction succeeded; root.dmg passed NXSB,
  4096-byte block geometry and exact-length checks. Both Cryptex images were
  archived read-only and successfully detached. All output remains under work/.
- Both private patch variants were built from the pinned final development
  artifacts: with SSH and without SSH. The original cache/signature pair is
  retained for SSH; the no-SSH cache removes only the three added SSH jobs.
  Source hashes, archive members and final file contents are checked locally.
- Tests exercise a simulated phone with existing s8/s9 volumes, descending
  deletion, stock-role preservation, busy unmounts, cancellation, upload
  corruption, full-iOS/wrong-device rejection, and typed deletion tokens.
  No simulated test calls any real disk-formatting or device command.
- The generated patch shell script was executed in a temporary host fixture:
  corruption stopped all replacements, originals were retained as .bak, and
  DriverKit backups stayed outside the sealed bundle. Owner changes were
  stubbed in that host-only fixture; real root:wheel metadata needs phone testing.
- Separate full-system host-key files, detached cache signature corruption,
  archive traversal rejection, and cleanup during installation are covered.
- Read-only inspection of the actual generated 16.1 SSHRD confirmed that df and
  readlink are absent. The owned helper now supplies those operations via libc;
  its iOS build is signed/verified on the Mac. A native test build passed ten
  SHA256 boundary vectors, a free-space query and symlink success/failure cases.
- The suite now has 65 passing tests, including version/build rejection before
  any other remote command or upload. The newly prepared pristine Cryptex `.09`,
  `.11` and `.27.dylddata` files all match the source hashes of their selected
  final patches. Both patch archives, their 667/649 files, detached signatures,
  modes and launchd job/cache consistency passed host verification.
- No new installer command has connected to or repartitioned the iPhone.

## Terminal output and Cryptex links

The first phone Cryptex attempt stopped before tar: an old symlink-parent guard
rejected native framework links into Cryptex. Read-only inspection confirmed the
stock layout. Extraction now retains those links as .bak and creates physical
directories before tar. A temporary host fixture verified extraction, retries,
backup conflicts, quoted paths and preservation of the original link targets.

Tool output now includes operation labels and direct failure diagnostics.
Foreground terminal execution streams native SCP, recovery and invert output;
a Mac-only SSH transport wrapper preserves SCP's foreground progress meter.
A host-local test used the actual scp/sshpass binaries to copy through a local
protocol sink and observed the native 0%/100% meter and speed output without
contacting the phone. The suite has 80 passing tests, including terminal process
groups, large script input, live failures and timeout cleanup.

## Full-system boot bundle and installation finalization

- The user reported successful installation through rootfs, both Cryptex archives,
  the selected rootfs/SSH patches and Preboot. No finalize/rename or reboot was
  performed during this development pass. The attempted read-only SSH query
  found no listener on port 2222, so live stock-kernel path discovery is pending.
- The actual full-iOS bundle was built successfully under output/ios16 using
  the retained stock D10 iBEC plaintext. Reapplying the ramdisk arguments
  reproduced the existing bootstrap iBEC exactly. The new iBEC contains the
  complete rd=disk1s8 argument string; every other image is copied unchanged
  from the device-ticketed 16.1 SSHRD. No AVE or ramdisk image is included.
- Host tests cover full-iOS send/load ordering, rejection before finalization,
  changed retained plaintext, unchanged kernel/SEP/DT inputs, backup conflicts
  before any rename, lossless .bak creation/retry, missing/symbolic kernel paths,
  installation-stage matching, and no Data mount or installation-media upload.
- A harmless local delayed-action test confirms that the reboot shell returns
  before the background action runs and that the scheduled action still runs.
  Optional reboot does not reconnect or wait for the phone. Expected shutdown
  disconnection is treated as completion; real submission failures remain errors.
- Full-system phone boot and actual stock-kernel backup still need user testing.
  At that milestone, AssistiveTouch and optional persistence-helper installation
  were still pending; both commands have since been implemented.

## Standalone checkout acceptance (2026-11-01)

This milestone supersedes the historical private rootfs-import dependency above.
No phone was contacted or modified during this work.

- 106 host regression tests pass, including configuration-free CLI aliases,
  stock-resource capture publication/retry, device binding, source containment,
  delta metadata/bounds checks and unchanged SSH password prompting.
- A separate checkout was copied into a temporary directory. Python file reads
  into the original project and its surrounding research tree were rejected by
  an audit hook. No forbidden access occurred.
- The isolated checkout received only verified extracted IPSW images, bundled
  project resources and original D10 stock files. For this host acceptance, the
  stock fixture was extracted from the verified 15.8.8 IPSW; this is explicitly
  not a test of the new live-device D10 capture step.
- All 667 compatibility outputs matched the locked working hashes: 645 copies,
  17 compact-delta reconstructions and five project-authored files. Both SSH
  variants were packaged; their file hashes, inventories, service counts and
  detached launchd signatures passed verification. Repeated preparation reused
  the checked archives successfully.
- The relocated checkout loaded the bundled libimobiledevice/libplist APIs
  without connecting to a phone. Its linker automatically expanded the bundled
  32 MB LLVM archive and loaded successfully at the new location.
- `doctor` resolved all host tools, fixed SSHRD inputs and AssistiveTouch
  libraries from the project bundle. No mandatory local JSON was read.
- HC3 transformation code and accepted raw/IM4P hashes were not changed by this
  packaging work. The full 28-stage rebuild was not repeated at this milestone.
- A new clean phone installation must still verify bootstrap D10-resource
  collection, subsequent preparation and the full end-to-end README workflow.
  Third-party binary source/license review remains listed in RELEASING.md.

## Upstream dependency download acceptance (2026-11-01)

- The author subsequently reported a complete successful installation from a
  relocated project copy. This is a user-reported device result.
- Six inputs now use runtime downloads instead of source-repository binary
  redistribution: img4, iBoot64Patcher, KPlooshFinder, kerneldiff, ssh.tar.gz and
  the bootstrap 0x8010.shsh preset. URLs reference immutable upstream commits.
- Each was downloaded into an empty temporary project using the actual runtime
  downloader. Size, SHA256, executable modes and complete byte equality against
  the existing working copies all passed. Cache reuse made no additional request.
- The large archive was once interrupted during transfer. Incomplete bytes were
  not installed. Transient-error retries were added and the complete acceptance
  then passed for all six files. Hash checks were not weakened.
- 112 host regressions passed, including changed-cache rejection, incomplete/
  wrong download rejection and preservation of existing files on errors.
- Download tests did not contact or modify a phone. HC3 transformations,
  accepted raw/IM4P hashes and the working kernel patcher were not changed.
- Official license texts, source-package recipes and per-component provenance
  are preserved in THIRD_PARTY.md and Darwin/. The MOD edwin patcher's exact
  compiled source revision remains explicitly unconfirmed.
