# Current test: semantic navigation 0.2.2

## 0.3.10 — модель профиля без прежней обрезки

[Запуск](PROFILE-NAVIGATION-0.3.10.md). «Найти счётчик» теперь раскрывает объявленные типы get_Profile / m_Profile / m_StatsMarker и их count/stat/friend-связи. Общие группы расширены до 1024 записей: найденные в 0.3.9 639 методов и 323 поля помещаются полностью. Сам счётчик в приложении ещё не исправлен.

## 0.3.9 — найти фактический счётчик в APK

[Инструкция](PROFILE-NAVIGATION-0.3.9.md). Новая кнопка «Найти счётчик» читает только локальные определения полей/методов, без запуска MuMu и посещений. Пришли rootless-friends-metadata-0.3.9.json. Это диагностика источника, не объявление исправленным счётчика 97.

## 0.3.8 — путь ADB и запуск без галочки

[Запуск](PROFILE-NAVIGATION-0.3.8.md). ADB по указанному пользователем пути, без галочки, запуск только кнопкой. Паузы 1 с сохранены. По отчёту 0.3.7 переход работает, источник числа друзей пока не найден.

## 0.3.7 — паузы 1 с и проверка счётчика друзей

[Запуск](PROFILE-NAVIGATION-0.3.7.md). 0.3.6 подтверждена реальным тестом: профиль → возврат. Теперь перед действиями неблокирующие паузы 1 с; число друзей читается только при поддерживаемом getter, иначе остаётся неизвестным. Только #4, без сообщений.

## 0.3.6 — компактный тест профиля

[Запуск](PROFILE-NAVIGATION-0.3.6.md). Компактное окно, одна строка за UI-кадр, исправлена проверка неинтерактивного Avatar. Только #4 / 5563, без сообщений и переустановки. Реальное открытие профиля пока не подтверждено.

## Сценарий профиля: 0.3.5 — ограниченный выбор и причины пропуска

[Инструкция и разбор отчёта 0.3.4](PROFILE-NAVIGATION-0.3.5.md).

Реальный 0.3.4 подтвердил поиск, но не открывал профиль: повторные обходы дошли до 6000 вызовов, все 1398 ссылок освобождены. В 0.3.5 — максимум три попытки выбора и закрытые числовые причины пропуска вместо повторов до call-limit. Проверки идентичности и прежние лимиты не ослаблены. Это диагностический шаг: реальное открытие профиля ещё не подтверждено. Только одна анкета на #4 / 5563, без сообщений, чтения контактов и переустановки; #0 / 5555 защищён. Windows-артефакт — в успешном запуске GitHub Actions.


See [NAVIGATION-0.2.2.md](NAVIGATION-0.2.2.md) for the separate consented
search → open filters → cancel → verify return workflow on the existing MuMu #4.
No OCR, coordinates, root, reinstall, messages or changes to working #0.
It invokes two existing UIKit UI handlers, not Android Accessibility clicks.
Live navigation still requires the user's first 0.2.2 report; 0.1.8 proved structure only.
Older preparation/diagnostic utilities below remain available, but are not the current navigation entry point.

---

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

## Actual UIKit definitions found offline

The supplied 6.8.1 APK uses custom UIKit classes in `Core.dll`, `DV.dll` and
`UIKit.Unity.dll`, rather than the generic Unity uGUI/TextMeshPro controls probed
in diagnostics 0.1.3. See [UIKIT-FINDINGS.md](UIKIT-FINDINGS.md) for confirmed
metadata, scope and the still-unimplemented main-thread/live-object gate.
`offline_metadata.py` verifies a private metadata file without a device connection;
`uikit_profile.py` provides a fixed **metadata-only** catalog. No new EXE, APK
installation or OCR is needed for this offline development step.


## Guarded live-root probe 0.1.5 (experimental, explicit opt-in)

`python rootless-unity/diagnose_uikit.py` opens the dedicated #4-only probe GUI.
The ordinary `diagnose_device.py` entrypoint remains metadata-only 0.1.3.
See [DIAGNOSTICS-0.1.5.md](DIAGNOSTICS-0.1.5.md) before running.
Do not repeat 0.1.4: its uint32 GC-handle binding truncated pointer-sized Unity 6
handles. 0.1.5 preserves the full opaque pointer and tests high-bit handles.
Restart only test MuMu #4 before retrying; no APK reinstall. The new mode
observes only the exported invocation API for a bounded period, requires an
existing frame callback plus the UIKit main-thread check, and invokes only two
root-presence getters after that guard. No guessed code pointers, text/field
reads, traversal or UI actions. Synthetic tests are not proof of MuMu/libnb
compatibility; do not mark the full workflow migrated based on `root-ready`.

### UIKit structure probe 0.1.6 (opt-in, test #4 only)

See [DIAGNOSTICS-0.1.6.md](DIAGNOSTICS-0.1.6.md) for the bounded structure-only GUI. It uses the existing authenticated Gadget and verified main-thread root, not OCR or screen coordinates. It does not read UI text or perform actions. Run `python rootless-unity/diagnose_tree.py` from the repository root with the pinned Frida client, or use the separately built Windows EXE. Keep the old private `test-apks` folder. No APK reinstall. Synthetic graph tests do not establish real-device tree support.

### Safe ADB evidence 0.1.7

[DIAGNOSTICS-0.1.7.md](DIAGNOSTICS-0.1.7.md) describes fixed-label ADB failure reporting for repeated `device-preflight` stops. This does not add commands, retry installation, modify ports or claim to fix the user's connection. Tree limits and no-OCR/no-input behavior are unchanged. The structure GUI now writes `rootless-diagnostics-0.1.7.json`; the older root-only and metadata-only modes retain their report versions.

### Subviews boxed Iterator adapter 0.1.8

[DIAGNOSTICS-0.1.8.md](DIAGNOSTICS-0.1.8.md) adds the exact metadata-verified `ShortList<UIView>.Iterator` protocol without OCR, text reads or UI input. The dedicated structure GUI writes `rootless-diagnostics-0.1.8.json`. Read-only ADB evidence from 0.1.7 is retained. No APK reinstall. Synthetic C ABI coverage includes the unboxed receiver and mandatory GetEnumerator copy; a real MuMu tree report is still needed.
