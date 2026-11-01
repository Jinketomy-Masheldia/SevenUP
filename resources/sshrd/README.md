# Fixed upstream SSHRD inputs

These inputs are downloaded automatically on first use and cached locally.
They are not committed to the SevenUP repository. No path configuration is
required; profiles/dependencies.lock.json pins the immutable URLs and sizes.

- ssh.tar.gz: upstream verygenericname/sshtars revision
  6c05c8a74095c63e1d130ecbf309d77efa6d17d5; original filename ssh.tar.gz.
  https://github.com/verygenericname/sshtars/tree/6c05c8a74095c63e1d130ecbf309d77efa6d17d5
- 0x8010.shsh: upstream verygenericname/SSHRD_Script revision
  d99ec4a19172b87d80fd9dea25eabf39291425a0, other/shsh/0x8010.shsh.
  https://github.com/verygenericname/SSHRD_Script/tree/d99ec4a19172b87d80fd9dea25eabf39291425a0

The loader pins both SHA256 values in source. The SHSH is the upstream temporary
A10 bootstrap preset, not the developer's device ticket. Actual-device SEP and
IM4M are collected by capture and used for subsequent device-specific images.
Do not replace these resources with device-private keys, tickets or account data.
The SSH archive retains its upstream tool contents and shared ramdisk host keys.
It is a local-use dependency, excluded from the SevenUP source distribution.
See ../../THIRD_PARTY.md for the component and distribution notes.
