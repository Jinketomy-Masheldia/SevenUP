# Release preparation

This checklist distinguishes publishing a research preview from claiming a
standalone public installer. Known hardware limitations may remain documented;
the checklist does not require claiming a complete iOS port.

## Source and input completeness

- [x] Label the release experimental/personal-research-only.
- [x] Replace the private rootfs-artifact import with firmware/captured-stock
      recipes; preserve all 667 working output hashes and remove author paths.
- [x] Pin the SSHRD archive and upstream bootstrap preset; fetch them on first
      use instead of redistributing the mixed archive and preset.
- [x] Remove the user configuration requirement; a legacy local.json is ignored.
- [x] Identify the shared upstream SSHRD host keys and exclude that archive from
      Git. Keep full-system SSH host-key generation device-local.
- [x] Record known dependency versions, official license texts, source archive
      checksums and library layout modifications in THIRD_PARTY.md and manifests.
- [ ] Identify the exact compiled source revision of MOD edwin Kernel64Patcher3;
      the GPLv3 source family is known but an exact rebuild is not established.
- [ ] Verify Darwin tools and dylibs are relocatable on the supported Mac
      architecture; a local Homebrew installation must not hide missing files.
- [ ] Review the project license/copyright notices and preserve upstream notices.
- [x] Exclude legacy local.json/local.json.bak, generated private state, expanded
      LLVM and the six upstream-only runtime downloads.
- [ ] Publish only the intended project tree, not the surrounding private
      research workspace or its raw diagnostic archives.
- [x] Inspect the candidate tree for complete Apple firmware images, personal
      tickets, host private keys, pairing/activation records and identifiers.
      The upstream-only archive and preset are runtime downloads, not Git assets.
- [ ] Inspect both staged files and Git history. .gitignore alone does not remove
      a sensitive file that was previously tracked.

## One clean end-to-end phone test

Use the author's supported Global iPhone7, freshly restored to the pinned stock
15.8.8 build and activated. Keep it free of important data and device passcodes.
Do not claim that an already patched device validates a first-time installation.

- [x] Author-reported clean end-to-end installation from a relocated project.
      Other individual release checks below remain to be recorded separately.
- [ ] Follow README.md without relying on an undocumented developer path.
- [ ] Run doctor and verify dependency errors explain how to resolve them.
- [ ] Prepare sources and rebuild the accepted HC3 raw/IM4P output.
- [ ] Build/boot the 15.6 SSHRD; capture SEP/IM4M and original D10 resources;
      exercise reboot yes/no behavior.
- [ ] Build/boot the 16.1 SSHRD using the captured device ticket.
- [ ] Prepare raw root.dmg, both Cryptex archives and the selected rootfs patches.
- [ ] Test the clean stock volume layout and the explicit existing-s8 deletion
      prompt separately if an additional destructive test is appropriate.
- [ ] Install rootfs, Cryptex, patches/SSH and Preboot; verify error recovery by
      resuming the specific failed phase rather than recreating rootfs blindly.
- [ ] Build the full-iOS bundle and run install finalize; retain kernelcache.bak.
- [ ] Boot full iOS16 in DFU, allow migration, and complete activation/setup
      normally using Don't Use Passcode. Do not configure a passcode later.
- [ ] Enable AssistiveTouch over USB and verify the visible button.
- [ ] Test SSH/SCP, including wrong-password hidden prompting and session exits.
- [ ] Test optional install trollstore with Tips present and absent; preserve
      the original executable and do not install TrollStore automatically.
- [ ] Power-cycle and perform another computer-assisted full-iOS boot.

## Functional checks and reporting

- [ ] Display, GPU/UI, touch, USB, Wi-Fi and Bluetooth.
- [ ] Speaker, Bluetooth playback, microphone and a Voice Memos recording.
- [ ] QR scanning and saved still photos in Most Compatible format.
- [ ] Haptics, motion sensors, compass/location and battery readouts.
- [ ] App Store download/install/launch and a reinstalled removable Apple app.
- [ ] Record camera video/AVE, Siri/dictation, Home, partial SEP/passcode and VPN
      as known limitations rather than passing tests.
- [ ] Record baseband as unresearched: faulty author hardware, two baseband
      variants and no available/tested GSM device. Do not claim cellular support.
- [ ] Record unplugged standby drain/temperature observations separately from
      USB-connected testing. An unresolved result can remain a disclosed issue.
- [ ] State the disabled healthd/mobiletimerd choices and their validation limits.
- [ ] Publish a redacted result summary with date/model/build/tool versions;
      do not publish raw device diagnostics or identifiers.
- [ ] Cross-check README, KNOWN_ISSUES, CLI prerequisite warnings and release notes.

A passing host suite and a successful bootx command do not substitute for this
phone test. Mark untested steps honestly. Do not publish performance, security
or hardware-support claims that have not been demonstrated.
