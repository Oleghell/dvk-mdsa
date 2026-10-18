# DVK 6.8.1: actual UIKit metadata, not standard Unity uGUI

## Confirmed offline

The original APK supplied privately contains standard `global-metadata.dat`, version
31. The bounded reader in `offline_metadata.py` validated all image/type/method
ownership: 49 images, 9,742 types and 80,676 methods. This is definition metadata,
not a screen snapshot or a runtime object dump. The source metadata SHA-256 and
**only the fixed requested catalog** are in `UIKIT-OFFLINE-EVIDENCE.json`.
No APK, complete metadata/type dump, application method bodies, user data, token
or signing material is checked in.

All **13 types and 29 method signatures** in `uikit_profile.py` match unique
metadata definitions in this input. The metadata-only native script can now be
built and validated against that separate catalog. It still uses the same nine
fixed IL2CPP C API calls, no managed invocation, hooks or actions.

The user-returned 0.1.3 runtime report independently completed a 49-assembly scan
on MuMu #4 with a valid IL2CPP domain and clean thread attach/detach. That report
used the *old* generic catalog: it did **not** test these UIKit types at runtime.
Matching assembly counts is corroboration, not proof of live UI access.

## Why the old UI probes missed the controls

The relevant definitions are not `UnityEngine.UI.Button` or TextMeshPro. They are
in the application's own cross-platform UIKit (not Apple's native UIKit API):

| Image | Fixed relevant definitions |
| --- | --- |
| `Core.dll` | `UIKit.UIRuntime`, `UIApplication`, `UIWindow`, `UIView`, `UIViewController`, `Control`, `Button`, `Label`, `TextField`, `UITextView` |
| `DV.dll` | `DV.DVButton` |
| `UIKit.Unity.dll` | `UIKit.UIRuntimeComponent` |
| `UnityEngine.CoreModule.dll` | `UnityEngine.UnitySynchronizationContext` |

The `.dll` labels identify IL2CPP images; no live CLR or loose DLL loading is
implied. The Android accessibility tree's few Unity containers do not expose
these custom managed view definitions as Android controls.

## Concrete hierarchy and action candidates

- Entry point: **static** `UIRuntime.get_OptionalInstance/0`.
- Main-thread guard: **static** `UIRuntime.get_IsOnMainThread/0`.
- Root candidates: **instance** `UIRuntime.get_MainWindow/0`, `get_PrimaryWindows/0`;
  `UIWindow.get_RootViewController/0` and `UIViewController.get_View/0`.
- Structure: `UIView.get_Subviews/0`, `get_Parent/0`, `get_Name/0`.
- Eligibility: `UIView.get_EffectivelyHidden/0`, `get_UserInteractionEnabled/0`,
  `Control.get_Enabled/0`.
- Labels: `Button.get_TitleText/0`, `Label.get_Text/0`, `DVButton.get_Text/0`.
- Future input: `TextField.set_Text/1`, `UITextView.set_Text/1`.
- Future action candidate: `Control.OnDidClicked/0`. A definition name alone does
  **not** prove equivalence to a user click, enabled checks or event sequencing.
  Do not invoke it until its semantics and a safe test target have been verified.

No listed getter, setter, click handler, task/delegate or UI method is invoked
by the current catalog script. Text getters are especially excluded from a first
live-object probe to avoid returning profile/conversation contents.

## Main-thread gate before inspecting objects

The metadata contains `UIRuntimeComponent.Update/0` (instance),
`UIRuntime.OnUnityUpdate/0` (instance),
`UnitySynchronizationContext.Exec/0` (instance), and `UIRuntime.RunOnMainThread/1`
(static). These are **candidates**, not an implemented or verified scheduler.

The next runtime step must observe an existing frame callback without replacing
its behavior, verify `get_IsOnMainThread` there, then attempt only a null/non-null
root check. No UI operations on the Frida RPC thread. Do not pass a native callback
pointer as a managed `System.Action`. Do not assume that a metadata method handle
is an executable code pointer, or use guessed MethodInfo offsets under libnb.
Unknown ABI, unsafe pointer resolution, lack of callbacks or main-thread mismatch
must stop the probe; no fallback to OCR, coordinate taps or protection bypass.

Before actual hierarchy traversal, validate collection types through runtime APIs,
cap depth/node counts, filter allowed UI data and retain managed references safely.
Never walk arbitrary object fields/heaps or issue app business/API requests instead
of verified UI actions. Subsequent click/input paths need visible/enabled checks,
unique semantic matches and an explicit separate action gate.

## What changed / what did not

- Added a strict offline v31 reader and a fixed, separately validated UIKit catalog.
- Factored the existing native probe into a catalog builder; the default 0.1.3
  catalog/GUI and its native call set remain compatible and unchanged in behavior.
- Added synthetic malformed-input/ownership tests and a native C ABI UIKit fixture.
- Added Linux/Windows verification CI. No EXE/APK release is published by this CI.
- No device contacted, app re-signed/installed, account accessed or actions sent in
  this step. The user does **not** need to download another diagnostic for this work.
- OCR/coordinates were not introduced. The original workflow has **not** yet been
  migrated to a functioning live UIKit backend; an all-workflow pass is not claimed.

## Reproduce locally (no Android connection)

Extract the single metadata file from your own original APK into a private folder,
then run:

```sh
python rootless-unity/offline_metadata.py /private/global-metadata.dat --out /private/uikit-catalog.json
python -m unittest discover -s rootless-unity/tests -v
```

The reader rejects unsupported versions, out-of-range/overlapping sections,
misaligned records, invalid strings and inconsistent type/method ownership. It
reads only metadata names, not the managed string-literal section. Output includes
fixed requested labels and counters, not a full vendor-definition dump.

Native smoke tests run **only an owned synthetic child**, not MuMu or an installed
application. Existing null-domain/count limits/thread cleanup cases are retained;
the added case checks the UIKit catalog and preserves negative/missing-type flags.

Layout reference consulted:
https://github.com/Perfare/Il2CppDumper/blob/master/Il2CppDumper/Il2Cpp/MetadataClass.cs
Frida API:
https://frida.re/docs/javascript-api/
