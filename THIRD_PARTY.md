# Third-party components and distribution notes

SevenUP's project license does not relicense dependencies or Apple firmware.
Copyright stays with each upstream author. Retain this file, LICENSE, the notices
under Darwin/licenses/, and source/provenance manifests when redistributing the
included runtime bundle.

## Included host components

| Component | Upstream license / notice | Source and provenance |
| --- | --- | --- |
| SSHRD workflow | BSD-3-Clause; root LICENSE preserves Nathan's 2022 notice | [verygenericname/SSHRD_Script](https://github.com/verygenericname/SSHRD_Script), reference revision d99ec4a19172b87d80fd9dea25eabf39291425a0 |
| gaster | Apache-2.0; Darwin/licenses/gaster-LICENSE.txt | [0x7ff/gaster](https://github.com/0x7ff/gaster). Binary unchanged from the pinned SSHRD distribution; SHA256 in Darwin/manifest.json |
| img4tool | LGPL-3.0; img4tool-LICENSE.txt and GPL-3.0.txt | [tihmstar/img4tool](https://github.com/tihmstar/img4tool/tree/aca6cf005c94caf135023263cbb5c61a0081804f), embedded version 0.197-aca6cf005c94caf135023263cbb5c61a0081804f |
| partialZipBrowser / pzb | LGPL-3.0; pzb-LICENSE.txt and GPL-3.0.txt | [tihmstar/partialZipBrowser](https://github.com/tihmstar/partialZipBrowser); binary from the pinned SSHRD distribution |
| irecovery / libirecovery | LGPL-2.1; irecovery-LICENSE.txt | [libimobiledevice/libirecovery](https://github.com/libimobiledevice/libirecovery); binary from the pinned SSHRD distribution |
| iproxy / libusbmuxd | LGPL-2.1; iproxy-COPYING | [libimobiledevice/libusbmuxd](https://github.com/libimobiledevice/libusbmuxd/tree/36ffb7a), embedded version 2.0.2+git20220504.36ffb7a |
| GNU tar 1.32 | GPL-3.0-or-later; GNU-tar-COPYING | [GNU tar 1.32 source](https://ftp.gnu.org/gnu/tar/tar-1.32.tar.xz). Copyright 2019 Free Software Foundation, Inc. |
| sshpass 1.06 | GPL-2.0; sshpass-COPYING | [sshpass 1.06 source](https://sourceforge.net/projects/sshpass/files/sshpass/1.06/sshpass-1.06.tar.gz/download). Copyright 2006–2011 Lingnu Open Source Consulting Ltd.; 2015–2016 Shachar Shemesh |
| Kernel64Patcher3, embedded label “MOD edwin” | GPL-3.0; Kernel64Patcher-edwin-LICENSE.txt | [edwin170/Kernel64Patcher](https://github.com/edwin170/Kernel64Patcher), [pwnerblu fork](https://github.com/pwnerblu/Kernel64Patcher/tree/dev). See the provenance limitation below |
| LLVM / LLD 23.1.4 | Apache-2.0 WITH LLVM-exception; llvm-LICENSE.TXT and lld-LICENSE.TXT | [llvm-project source](https://github.com/llvm/llvm-project/releases/tag/llvmorg-23.1.4); exact source archive/checksum and installed build recipes in Darwin/sources.json and Darwin/source-recipes/ |
| Z3 5.3.3 | MIT; z3-LICENSE.txt | [Z3](https://github.com/Z3Prover/z3); exact source archive/checksum in Darwin/sources.json |
| Zstandard 1.5.7 | BSD-3-Clause OR GPL-2.0; zstd-LICENSE and zstd-COPYING | [facebook/zstd](https://github.com/facebook/zstd/releases/tag/v1.5.7) |
| libimobiledevice 1.4.0, libplist 2.8.0, libimobiledevice-glue and libusbmuxd 2.1.1 libraries | LGPL-2.1 family; individual COPYING / COPYING.LESSER files under Darwin/licenses/lockdown/ | [libimobiledevice organization](https://github.com/libimobiledevice). Exact installed source packages/checksums and original/relocated library hashes are recorded in Darwin/sources.json and Darwin/lib/lockdown/manifest.json |
| OpenSSL 4.1.0 libraries | Apache-2.0; lockdown/openssl@4-LICENSE.txt | [openssl/openssl](https://github.com/openssl/openssl/releases/tag/openssl-4.1.0); source checksum in Darwin/sources.json |
| Recorded Homebrew build recipes | BSD-2-Clause; Homebrew-COPYING | [Homebrew/homebrew-core](https://github.com/Homebrew/homebrew-core); recipe snapshots are under Darwin/source-recipes/ |

License spellings above follow the upstream notice or recorded package recipe.
For the complete terms and applicable copyright notices, read the individual
license files. Source links are provided alongside the binary provenance;
compiled filenames alone do not identify a unique source build.

### Changes to the host runtime bundle

The SSHRD-distributed executables are unmodified. The linker and lockdown dylibs
have project-relative Mach-O load paths, removed external rpaths and ad-hoc code
signatures. No library source changes were made for these layout adjustments.
The maintenance scripts tools/import_darwin.py and tools/import_lockdown.py
record the transformations. The large LLVM dylib is stored as .xz and expanded
without changing its bytes. Original and distributed SHA256 values are preserved
in the manifests. Source package recipes and archive checksums are included for
rebuilding the original libraries and applying these layout changes.

### Kernel64Patcher3 provenance limitation

The author obtained the working binary through surrealra1n. Its pinned script at
[e1f0ecba9e993e6add89d5fed638c21334425cda](https://github.com/pwnerblu/surrealra1n/blob/e1f0ecba9e993e6add89d5fed638c21334425cda/surrealra1n.sh)
references both edwin170/downr1n's prebuilt patcher and a source build of the
pwnerblu/Kernel64Patcher dev branch. Both identified Kernel64Patcher source
families carry GPLv3. The local binary identifies itself as “MOD edwin”; its
exact compiled source revision is not embedded or independently established.
It is retained unchanged with its locked hash, rather than replacing a tested
binary with a different build. The upstream source-family license text is
preserved; this record is not a claim of a reproducible rebuild of that binary.

## Upstream-only inputs: downloaded, not committed

The following inputs are deliberately excluded by .gitignore:

- Darwin/KPlooshFinder
- Darwin/iBoot64Patcher
- Darwin/img4
- Darwin/kerneldiff
- resources/sshrd/ssh.tar.gz
- resources/sshrd/0x8010.shsh

No clear separate redistribution grant was confirmed for all content of these
inputs. SevenUP therefore fetches the exact upstream bytes for local use instead
of including them in its source distribution. This does not assign them a new
license or establish any broader permission to redistribute them. Original
copyright notices and terms remain applicable.

profiles/dependencies.lock.json records immutable upstream commit URLs, exact
sizes and SHA256 values. First use automatically downloads a missing input;
subsequent use checks the cached bytes. An error or hash mismatch stops before
installation. No user configuration, Git submodule initialization or manually
chosen binary is required. Downloaded local copies remain ignored by Git.

The four host tools come from the pinned SSHRD_Script revision above. The SSH
archive comes from verygenericname/sshtars revision
6c05c8a74095c63e1d130ecbf309d77efa6d17d5. The initial A10 preset comes from the
pinned SSHRD_Script other/shsh/0x8010.shsh; it is not the author's device ticket.

The upstream SSH archive includes pre-generated ramdisk host keys and a mixture
of tools. Its local-use SHA256 is pinned, but it is not included in the SevenUP
Git repository. These shared upstream ramdisk keys are separate from full-system
SSH: the latter generates a new device-local host key during installation.

## Optional TrollStore helper

The optional command downloads PersistenceHelper_Embedded from the TrollStore
2.1.1 release. The helper is not included in the SevenUP repository. Its upstream
terms remain applicable; the current upstream license text is preserved as
Darwin/licenses/TrollStore-LICENSE.txt for reference. Upstream:
https://github.com/opa334/TrollStore/releases/tag/2.1.1

## Apple firmware and generated files

Apple firmware is supplied by the user or read from their own device. The
repository contains recipes, hashes and compact transformation deltas, not
complete Apple rootfs, kernel, Cryptex or SEP images. Generated Apple executables,
device tickets, stock hardware resources, logs and private host keys stay under
ignored local paths. SevenUP's BSD notice does not grant rights to Apple software.
