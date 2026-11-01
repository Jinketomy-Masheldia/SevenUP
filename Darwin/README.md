# Project-local macOS tools

The CLI uses executables from this directory independently of the terminal's
current directory. No local configuration is required. Missing upstream-only tools are downloaded
automatically from pinned commits and verified before use. PATH is a fallback
only for a tool that is neither bundled nor in the dependency lock. The supplied bundle targets Apple Silicon;
other host architectures have not been qualified.

The working directory contains twelve SSHRD tools and ld64.lld after preparation.
Eight tools and the linker are bundled. img4, iBoot64Patcher, KPlooshFinder and
kerneldiff are upstream-only downloads, excluded by .gitignore. Their expected
bytes are pinned in profiles/dependencies.lock.json. Linker libraries live in
`lib/`; AssistiveTouch's libimobiledevice/libplist libraries and their non-system
dependencies live in `lib/lockdown/`. Load paths use @loader_path and modified
Mach-O files are ad-hoc signed. A separate Homebrew installation is not required
to load these libraries. Xcode, its iPhoneOS SDK and macOS system utilities are
not bundled.

`lib/libLLVM.23.1.dylib.xz` stores the large LLVM library within GitHub's single
file size limit. `doctor` and kernel compilation unpack it automatically on first
use, checking the compressed and expanded hashes from `manifest.json`. The
expanded `.dylib` is ignored by Git. Keep the compressed source in the checkout.

`manifest.json` and `lib/lockdown/manifest.json` record original and bundled
hashes. Available license notices are preserved under `licenses/`. Per-component
licenses, source package URLs/checksums and build references are recorded in
../THIRD_PARTY.md and sources.json. Exact original/relocated hashes are retained.
The project license does not replace upstream licenses; the exact compiled
source revision of the MOD edwin patcher remains a documented limitation.

The developer import utility `tools/import_darwin.py` is retained for maintaining
the bundle. Ordinary users do not need to run it. Its output must be reviewed
for relocation, notices and any oversized files before replacing this bundle.
