# Exact HC3 reconstruction

The source rebuilder reproduces the current HC3 artifact, including retained
diagnostic instrumentation. It does not substitute HU12, omit AMFI/SSHRD
preprocessing, remove the panic renderer, or silently select another baseline.

The complete raw kernel and compressed IM4P are byte-identical to the working
HC3 reference. Device-ticket-dependent outer IMG4 bytes may differ.

## Build

```sh
./run.sh prepare
./run.sh fetch-bootstrap
./run.sh kernel-build
./run.sh kernel-build --fresh
```

`--through STAGE` stops at a historical checkpoint. Normal builds verify and
reuse completed checkpoints. `--fresh` creates an empty private workspace,
regenerates all three kernel inputs, and rebuilds every requested stage. Only
the verified extracted IPSW component cache is shared.

`PYTHONPATH=src python3 tests/accept_kernel_rebuild.py` adds a Python audit guard
that rejects legacy input file access and legacy paths in subprocess arguments.
This host acceptance passed all 28 checkpoints with zero legacy input access
attempts. A separate post-build comparison confirmed full reference byte equality.
No phone operations are part of this test.

## Source normalization

| Source | Original research input | Preparation |
| --- | --- | --- |
| iPhone 7, 15.6 / 19G71 | SSHRD-patched raw kernel | Decode; run KPlooshFinder exactly once |
| iPad, 16.1 / 20B82 | SSHRD-patched raw kernel | Decode; run KPlooshFinder exactly once |
| iPhone 8, 16.1 / 20B82 | Pristine raw kernel | Decode only |

Every source has pristine and research-state hash locks. A full 15.6 IPSW is
optional: the bootstrap builder fetches only its required components and checks
the pinned manifest and component digests.

## Reconstructed chain

The ordered hash graph is in `profiles/kernel-stages.json`.

| Stages | Behavior retained |
| --- | --- |
| D, E, F, G | Historical no-PMU paths, USB logging and red console formats |
| H, I, O | Rootful mount changes, firmware-update compatibility and optional button wake lookup |
| CH1, CH2, DS2, AG1 | Chestnut append, power diagnostics, D2333 in D2365 allocations, PMU sample guard |
| AU3, AU4, AU5, AU6 | Amplifier, virtual-MCA transport, AOP completion and AD81006 |
| MG1, AK1, AK2 | Maggie ABI and retained legacy SEP request compatibility |
| BT1 | SN2400 battery driver and native dependency bindings |
| MC1, MC1D, MC2D | Codec ABI, typed allocations, panic renderer and switch accesses |
| HU9, HU10, HU11, HU12 | UART/STMB, Homer firmware handling, metaclass aliases and dispatch fixes |
| HC1, HC3 | Homer event consumers and bounded Home command records |

The failed HU1-HU8 builds are not intermediate inputs. HU9 retains the reviewed
common UART class reconstruction logic. The transplant engine's AU2 history
does not make the failed AU2 artifact an input to AU3.

## Proprietary inputs and project source

Kernel and driver executable bytes, original parsers and their strings are
read from verified firmware. No driver blob, full Apple kernel, precompressed
kernel, original IM4M, or historical generated helper is bundled.

The project contains Python transformations, project-owned C/assembly helpers,
and reviewed fixed-build ABI metadata: addresses, class sizes, inheritance,
vtable correspondence, expected source-word hashes and new immediate values.
ABI profiles change fields on instructions read from the donor; they contain
no complete original instruction streams. Class insertion order is intentional
because it affects typed-signature placement and exact output.

Transplants check allocation bounds, pointers, KASLR relocations, dependencies,
typed metadata, unrelated driver bytes and outer Mach-O layout. Every stage
also checks its complete expected raw hash. Compiler-produced helpers must
therefore reproduce historical bytes too. Python optimized mode is rejected
because structural checks use assertions.

## Final acceptance and packaging

- Raw SHA256: `d11e37f4c349d997577894d9f9bc08bcac718a3ee1ce62d1d1c055e47053c168`
- IM4P SHA256: `5af51daeaf69e737f2288e32b8db05209c3eab64a099f0aec212327d0e18a408`
- Frozen original IMG4 MD5: `d6e496e1917fc7c808e896706a4dca00`

Original IPSW IM4P description and compression-size metadata are retained.
LZFSE_SMALL encoding is checked by the native decoder, then the final IMG4 is
decoded independently by img4 and img4tool. The complete compressed IM4P must
match its lock. Toolchain changes that alter bytes stop acceptance; the known
compiler, SDK, linker and tool hashes are in `profiles/toolchain-reference.json`.

Generated packages stay under ignored work directories. Before a device IM4M
is collected, packaging uses the explicit bootstrap preset and labels it
temporary. `build ios16-sshrd` uses the collected device ticket and preserves
the source-built kernel IM4P unchanged.

Kernel reconstruction is complete. The development phone has reached full iOS
and full-system SSH; a repeat clean installation is planned before release.
Source-only rootfs patch preparation, dependency source/bootstrap packaging and
licensing review remain release work. Current functional limitations are in
KNOWN_ISSUES.md; complete Setup Assistant without configuring a passcode.
