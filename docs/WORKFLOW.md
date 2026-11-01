# Workflow and remaining stages

## Implemented preparation / SSHRD stages

1. Individual confirmations: D10 model, fresh 15.8.8 restore, activation,
   no passcode, no important data or restored backup, restore readiness,
   and acceptance of the documented limitations.
2. Check pinned IPSW size, MD5, SHA1, product/build, and customer erase identity;
   record SHA256 and extract only required components into a private workspace.
3. Fetch only the pinned 15.6 SSHRD components automatically if they are not
   cached. No complete 15.6 IPSW is required. Query the real phone in DFU;
   build a D10 15.6 SSHRD with rd=md0 and retain its patched donor kernel.
4. Explicitly boot the bootstrap SSHRD, then verify SSH version before mounting.
5. Run mount_filesystems with a separate confirmation; read the mounted stock
   build, active Preboot directory, original SEP IMG4, matching device IM4M and original D10 hardware resources.
6. Rebuild the exact HC3 kernel from verified IPSW sources and project-owned
   C/assembly helpers. Check all 28 raw checkpoints, the compressed IM4P, and
   two independent decoders. The local reference bridge is optional.
7. Build a 16.1 iPad-resource ramdisk. Retain D10 15.6 iBSS, iBEC, and device
   tree IM4P payloads; use the stock SEP and collected device ticket throughout.
8. Verify the full kernel raw hash, then explicitly boot the second SSHRD.
9. Reconstruct the 667 rootfs compatibility files from IPSWs, captured stock
   resources and bundled recipes; prepare a raw APFS root.dmg and both matching
   Cryptex archives on the Mac. No external reference tree or configuration.
10. Explicitly recreate disk1s8 after a volume-specific confirmation, with all
    container volumes unmounted before apfs_invert. Install both Cryptex archives,
    reconstructed rootfs patches, optional SSH and ticket-derived Preboot paths.
    See INSTALL.md for exact commands and source provenance.
11. Build a separate full-iOS bundle from the verified 16.1 SSHRD files, changing
    only the D10 iBEC boot arguments to rd=disk1s8. Preserve the HC3 kernel;
    omit AVE and ramdisk. The retained stock iBEC plaintext must reproduce the
    verified bootstrap patch before being used.
12. Run install finalize explicitly: require current deployment receipts, retain
    stock System/current Preboot kernelcache copies as kernelcache.bak, and
    offer reboot. Either answer exits immediately after completion; no waiting
    for device reconnection. Data is not mounted during finalization.
13. Enter DFU manually and explicitly boot ios16 on the same device. Send/load
    DeviceTree, TrustCache, SEP and Kernel, in that order. A successful bootx
    command is a handoff, not proof that full iOS booted successfully.
14. Enable AssistiveTouch with the separate assistive-touch command over USB
    lockdown. Check the live device identity, set AssistiveTouchEnabledByiTunes
    to 1, and read it back. No phone executable or SSH connection is needed.
15. Optionally run install trollstore in SSHRD with Data mounted at /mnt2.
    Discover Tips' real app-container UUID, preserve Tips.bak and install the
    upstream 2.1.1 embedded persistence helper. Missing Tips produces a reminder
    to install it in full iOS and exits without changing files.

## Not implemented yet

- A repeat clean end-to-end installation is planned before release. The
  development device has reached full iOS and full-system SSH is working.
- A complete source-build bootstrap and license/source inventory for every
  bundled third-party host and SSHRD executable.
- Automatic migration-completion monitoring. Complete Setup Assistant normally
  without configuring a passcode; use AssistiveTouch for the physical Home limitation.
- Offer the implemented persistence-helper command in an integrated guided
  workflow, explicitly selected by the user and default recommended.
- Final verification/reboot and an option to keep or disable full-system SSH.

Formatting/invert occurs only through the explicit install command and its typed
confirmation. Original-kernel rename is confined to install finalize. Tips
replacement is confined to install trollstore. No Setup flag or account change
is performed.

## Failure behavior

Do not guess a Preboot directory, accept a mismatched build, continue after a
failed mount, or overwrite an existing output bundle. Keep failed build work
for diagnosis. Expired confirmations and a different ECID stop device actions.
Every completed stage is recorded atomically. An open USB command returning
success is not considered proof of a successful ramdisk boot or firmware load.
