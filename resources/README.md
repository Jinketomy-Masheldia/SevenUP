# Bundled resources

Normal operation needs no local configuration file or external research tree.
User-supplied firmware belongs in `inputs/ipsw/`; device-specific and generated
files remain private under `work/`, `output/` and `logs/`.

## Host tools

The CLI resolves tools relative to the project-local `Darwin/` directory,
regardless of the shell's current directory. PATH is a fallback when a bundled
executable is absent. The Apple Silicon bundle includes most host tools, the linker,
non-system linker libraries and libimobiledevice/libplist runtime used by
AssistiveTouch. See [Darwin/README.md](../Darwin/README.md).

macOS system commands and Xcode's iPhoneOS SDK are host prerequisites. Xcode is
not redistributed. The accepted compiler/tool versions and kernel hashes are
recorded in `profiles/toolchain-reference.json`; exact raw/IM4P equality remains
required. No `irecovery.fake` executable or author-specific device identity is
used: the actual device supplies ECID, serial and nonces.

## Fixed upstream inputs

`sshrd/ssh.tar.gz` and `sshrd/0x8010.shsh` are pinned upstream inputs, downloaded
automatically on first use and ignored by Git. Four host tools (img4,
iBoot64Patcher, KPlooshFinder and kerneldiff) use the same download mechanism.
Immutable URLs, sizes and hashes are recorded in profiles/dependencies.lock.json.
A failed download or mismatch stops before publishing a file; current verified
local copies are reused. No configuration is required. Their origins
are documented in [sshrd/README.md](sshrd/README.md), and their SHA256 values are
fixed in the loader. The SHSH is an upstream temporary A10 bootstrap preset,
not the author's device ticket. Later images use the user's captured SEP/IM4M.

The SSH archive retains its upstream executable contents and temporary ramdisk
host keys. These are separate from the full-system SSH host key, generated on
the target during installation. Do not put device-private keys or credentials in
repository assets. Distribution must preserve applicable third-party notices.

## Rootfs recipes

`profiles/rootfs-recipes.json` reconstructs 667 working compatibility files:
645 unchanged copies, 17 compact deltas and five project-authored resources.
The original Apple files come from the supplied IPSWs or the supported phone's
stock System, collected by bootstrap `capture`. No third full IPSW is required.

`rootfs/deltas/` contains compressed write records and source/target metadata,
not complete Apple executables. `rootfs/files/` contains the project-owned
helpers, SSH launchd jobs and shell profile. Every reconstructed target must
match `profiles/rootfs-reference.json` before packaging.

Run `./run.sh prepare-install` after firmware preparation and stock capture.
It prepares both rootfs patch variants and the rootfs/Cryptex installation media
on the Mac. It does not connect to or modify the phone.

Per-component licenses, source references and distribution boundaries are
documented in [THIRD_PARTY.md](../THIRD_PARTY.md).
