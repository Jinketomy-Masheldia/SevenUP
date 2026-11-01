# Local firmware inputs

Copy the two required files here:

```text
iPad_64bit_TouchID_ASTC_16.1_20B82_Restore.ipsw
iPhone_4.7_P3_16.1_20B82_Restore.ipsw
```

The 15.6 SSHRD components are downloaded automatically by the bootstrap
builder. Its patched kernel output is retained as a donor. No full 15.6 archive
is required. An optional full archive may be supplied for offline preparation:

```text
iPhone_4.7_P3_15.6_19G71_Restore.ipsw
```

Optional stock restore archive:

```text
iPhone_4.7_P3_15.8.8_19H422_Restore.ipsw
```

Run `../../run.sh prepare --verify-only --allow-missing` from this directory,
or `./run.sh prepare --verify-only --allow-missing` from the project root.
Archives are never committed. Do not rename an unrelated IPSW to these filenames;
its size, MD5, SHA1, product, build, and BuildIdentity must match the pinned lock.
