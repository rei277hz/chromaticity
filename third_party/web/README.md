# Web build dependencies

`dependencies.json` records the Linux x86_64 GNU dependency closure for the
modCAM16 web product. `dependencies.bzl` contains the same records for Buck;
`BUCK` declares each archive separately so downloading, verification, and CAS
transfer happen before build actions execute.

The npm records preserve package-lock versions and integrity values. Their
SHA256 values were computed only after verifying each tarball against its
lockfile SRI hash. Platform-specific optional packages are selected for Linux,
x86_64, and glibc. Rust dependencies, executable tools, and compiler distributions
are managed separately in [`third_party/rust`](../rust/README.md).

The pinned tool distributions are Node 26.13.0 and Chrome for Testing
153.0.8010.12 (the browser associated with Playwright 1.63.0). Node checksums
come from the official release manifest. Other archives are
hashed from the downloaded release bytes. PyOpenColorIO 2.5.0 uses its published
CPython 3.13 Linux wheel and PyPI SHA256.

After deliberately updating the application npm lockfile, refresh both declarations:

```sh
python3 third_party/web/update.py
```

Check the npm lockfile and both declarations offline without changing files:

```sh
python3 third_party/web/update.py --check
buck2 test //third_party/web:manifest_consistency --remote-only
```

This is a network-enabled maintenance command, never part of a Buck build.
It verifies npm integrity before writing either manifest and keeps temporary
downloads outside the repository. Review generated URL, version, and checksum
changes with the lockfile update. Runtime package licenses remain the upstream
licenses shipped in the declared distributions.
