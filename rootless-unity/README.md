# APK source exporter 0.1.0 — rootless preparation only

This utility **does not yet inject Frida Gadget, access Unity objects, or automate the app**.
It copies only installed `drug.vokrug` APK binaries into a local ZIP so that the actual
entrypoint, manifest and split layout can be examined before implementing test-only instrumentation.
It does not back up an account. The source app remains untouched.

## Windows

1. Start your normal MuMu instance. Enable its usual ADB connection, not root.
2. Extract the release ZIP; run `Dvk-apk-export.exe`.
3. If not detected, select `adb.exe` or `adb_server.exe` from your trusted MuMu installation.
4. Choose an output folder with at least 4.25 GiB free; confirm APK-only reading.
5. Click **Скопировать APK в ZIP** and attach the resulting `Dvk-apk-source-....zip` to the private support chat.

Do not publish the source APK archive, account data, modified APKs, or signing keys on GitHub.
The tool never uploads anything itself. An APK can contain vendor-provided bundled assets;
this archive is not a privacy scan of the vendor's application. No installed app-private data is copied.
Only instance `127.0.0.1:5555` is supported in this initial exporter. A different port fails explicitly.
If file access is denied, stop and report the error; do not enable root or change file permissions.
Do not disable Windows security protections if execution is blocked.

## Scope / safety

Finite subprocess allowlist, `shell=False`: ADB version, connect to the above local instance,
get-state, `pm path drug.vokrug`, pull validated `/data/app/.../drug.vokrug-.../*.apk`.
No arbitrary shell, root/su, run-as, app launch, installation, uninstall, input, screenshots,
OCR, chat reads or tunnel. Split APKs are preserved byte-for-byte, not unpacked or run.
Two reads of `pm path` detect installation-path changes during copying. SHA-256 and sizes
are stored per APK; offline package/version/signature verification is **not** claimed yet.
Cancellation takes effect after the current bounded ADB operation; temporary files are removed
on ordinary failure/cancellation. Force-killing Windows/process can leave a staging folder.
File-count, per-APK and total-byte limits are checked after copying; they are not transfer quotas.

## Next gate

Inspect the actual APKs before writing a bootstrap. Then evaluate a locally bound Gadget in a
**fresh separate test MuMu instance**, with a separate test signing key, not the helper key.
No original-app replacement, root, debug/security-policy weakening, anti-detection or integrity-check
bypass. If the modified test build refuses to run, stop. ARM64 library presence is not proof
that Gadget works under MuMu's ARM translation. Unity runtime object access remains unverified.

## Development

Python 3.13, standard library only:

```
python -m unittest discover -s rootless-unity/tests -v
python rootless-unity/apk_export.py
```

`--self-check` opens/verifies/closes the real Tk window without contacting ADB.
The Windows release is built with PyInstaller 6.16.0; no Android APKs or test keys are released.

## Audited 6.8.1 offline bootstrap (experimental)

`prepare_test_apks.py` now implements an **offline** bootstrap for the exact APK pair
received through the private chat. It is not part of the exporter EXE and has no ADB,
network client, installer or device actions. Other input versions fail SHA-256 checks.

The audited launcher is `drug.vokrug.activity.Launcher` in `classes5.dex`; it inherits
from `dv.DVPlayerActivity` and originally has only its constructor. The added class
initializer explicitly calls `System.loadLibrary("frida-gadget")`. Existing app methods,
Unity native libraries, resources and the binary Android manifests remain unchanged.
Only `classes5.dex` is taken from the DEX rebuild. The official ARM64 Gadget 17.24.1
and its `.config.so` are added to the ARM64 split. Original APK signatures/source-stamp
metadata are replaced with signatures from a **new separate test key**, not the helper key.

The config uses Android loopback `127.0.0.1:27042`, fresh token authentication,
`on_load=resume`, and `on_port_conflict=fail`; no script, asset server or portal.
The token is embedded in the test APK and is not a secret from anyone who can inspect
that APK. Use only an isolated trusted test emulator. Never forward it publicly or
through a tunnel/MCP. No anti-detection naming, integrity hooks, trust checks, root
checks, certificate pinning, debuggable flag or network-security config are altered.

Private build example (Linux, trusted JDK/Android build-tools, Apktool 3.0.3):

```
python rootless-unity/prepare_test_apks.py \
  --source /private/source-apks \
  --work /private/new-empty-build-directory \
  --apktool /tools/apktool_3.0.3.jar \
  --gadget /tools/frida-gadget-17.24.1-android-arm64.so.xz \
  --java-home /tools/jdk-17 \
  --build-tools /tools/android-build-tools
```

The builder intentionally does not download tools. Apktool and the Gadget XZ must
match pinned official-release SHA-256 values. Work/source must be outside this repo.
`test-apks/` contains only test APKs/report; `private/` contains keys/token/build logs
and must never be shared or committed. Reproduction creates a new signing key/token,
so signed output hashes naturally differ. Use a new build directory on each attempt.
A failed build can leave partial private outputs; do not install those.

The static report is in `OFFLINE_BUILD_REPORT-6.8.1.json`. Signatures and alignment
were checked with Android tools. A local round-trip disassembly of 8,540 classes in
`classes5.dex` found only Launcher changed, with its original constructor preserved.
**This is not an Android install, ART-verifier or runtime test.** Gadget load, ARM
translation support, Unity object enumeration and all user actions are still untested.

Before installation, create a **fresh separate MuMu instance**, confirm its ADB serial
is not the working instance (`127.0.0.1:5555`) and that `drug.vokrug` is absent. Do not
uninstall or replace any existing installation. No automatic installer exists in this
stage. If startup fails because the app rejects modification/signing, stop; do not
bypass the rejection. Login state is not copied. Use a test account if login is needed.

Official references:
- https://frida.re/docs/gadget/
- https://github.com/frida/frida/releases/tag/17.24.1
- https://github.com/iBotPeaches/Apktool/releases/tag/v3.0.3
