# Production readiness diagnostics

This utility performs read-only checks. It does not interact with the app UI, tap controls, type, or send messages.

## Run

From the repository root on Windows:

```powershell
py .\mumu-navigation\production_readiness.py --pretty
```

If ADB is not on PATH:

```powershell
py .\mumu-navigation\production_readiness.py --adb "C:\\path\\to\\adb.exe" --pretty
```

You can also set `ADB_PATH` to the full path of `adb.exe`.

Exit codes:
- `0`: ADB responds and at least one device is online.
- `2`: diagnostics are incomplete or a device is not ready.

The JSON output has a stable `schema_version` field and per-check status. Device serials are intentionally omitted from output. A connected device in `unauthorized` state must be authorized in the emulator/device UI; this tool does not bypass Android's authorization.

## Tests

From the repository root:

```powershell
py -m unittest discover -s .\\mumu-navigation\\tests -v
```

These unit tests use mocked ADB responses. They are not evidence of real MuMu integration. Before declaring a production release, also test on the actual supported Windows versions and MuMu releases, verify the packaged executable, and exercise reconnect/crash recovery with a real emulator.
