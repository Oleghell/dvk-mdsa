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
