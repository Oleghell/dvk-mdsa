"""Independent strict transport gate: allow only image-free native operations."""
import base64,json
from control_protocol import SERIAL,COMPONENT,args_allowed

def allowed_adb(args,reader):
    if args in (["version"],["connect",SERIAL],["-s",SERIAL,"get-state"],
                ["-s",SERIAL,"shell","getprop","ro.build.version.release"],
                ["-s",SERIAL,"shell","dumpsys","window"]):return True
    if (reader._local_control_setup and len(args)==6 and args[:5]==['-s',SERIAL,'install','-t','-r']
        and args[5] in reader.control_install_paths and args[5].replace('\\','/').endswith('/control-helper.apk')):return True
    if not args_allowed(args,reader.control_enabled):return False
    try:r=json.loads(base64.b64decode(args[9],validate=True))
    except (ValueError,TypeError,UnicodeError):return False
    return (r['op'] in ('ui_dump','ui_diagnostics','ui_back','ui_set_text') or
            r['op']=='ui_click' and r['allow_coordinate_fallback'] is False)
