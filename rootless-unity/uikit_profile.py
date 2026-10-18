"""Fixed metadata-only catalog for the UIKit found in the supplied DVK 6.8.1 APK.

Names identify definitions, not live instances. No getters or actions are invoked.
Do not substitute this catalog for a main-thread scheduler or a UI backend.
"""
from native_metadata import build_native_function, validate_metadata

PROFILE_ID='dvk-6.8.1-uikit-v1'
TYPES=[('UIKit.'+name,'Core.dll','UIKit',name) for name in (
    'UIRuntime','UIApplication','UIWindow','UIView','UIViewController',
    'Control','Button','Label','TextField','UITextView')]+[
    ('DV.DVButton','DV.dll','DV','DVButton'),
    ('UIKit.UIRuntimeComponent','UIKit.Unity.dll','UIKit','UIRuntimeComponent'),
    ('UnityEngine.UnitySynchronizationContext','UnityEngine.CoreModule.dll','UnityEngine','UnitySynchronizationContext')]
METHODS=[
    ('UIKit.UIRuntime','get_OptionalInstance',0),
    ('UIKit.UIRuntime','get_IsOnMainThread',0),
    ('UIKit.UIRuntime','GetCurrentApplication',0),
    ('UIKit.UIRuntime','get_MainWindow',0),
    ('UIKit.UIRuntime','get_PrimaryWindows',0),
    ('UIKit.UIRuntime','RunOnMainThread',1),
    ('UIKit.UIRuntime','OnUnityUpdate',0),
    ('UIKit.UIApplication','get_Window',0),
    ('UIKit.UIWindow','get_RootViewController',0),
    ('UIKit.UIView','get_Subviews',0),
    ('UIKit.UIView','get_Parent',0),
    ('UIKit.UIView','get_Name',0),
    ('UIKit.UIView','get_EffectivelyHidden',0),
    ('UIKit.UIView','get_UserInteractionEnabled',0),
    ('UIKit.UIViewController','get_View',0),
    ('UIKit.UIViewController','get_TopViewController',0),
    ('UIKit.Control','get_Enabled',0),
    ('UIKit.Control','OnDidClicked',0),
    ('UIKit.Button','get_TitleText',0),
    ('UIKit.Label','get_Text',0),
    ('UIKit.TextField','get_Text',0),
    ('UIKit.TextField','set_Text',1),
    ('UIKit.TextField','get_UserInputEnabled',0),
    ('UIKit.UITextView','get_Text',0),
    ('UIKit.UITextView','set_Text',1),
    ('DV.DVButton','get_Text',0),
    ('UIKit.UIRuntimeComponent','Update',0),
    ('UnityEngine.UnitySynchronizationContext','get_MainThreadId',0),
    ('UnityEngine.UnitySynchronizationContext','Exec',0),
]
IMAGES=sorted({t[1] for t in TYPES})
SCRIPT=build_native_function(TYPES,METHODS,IMAGES)


def validate(value):
    return validate_metadata(value,types=TYPES,methods=METHODS,images=IMAGES)
