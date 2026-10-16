"""Configure disposable CI AVD physical display, never the user's emulator."""
import os,re
from pathlib import Path
root=Path(os.environ.get('ANDROID_AVD_HOME',str(Path.home()/'.android/avd')))
configs=list(root.glob('*.avd/config.ini'))
assert configs,'CI AVD config not found'
for path in configs:
    lines=[line for line in path.read_text(encoding='utf-8').splitlines() if not re.match(r'^hw\.lcd\.(width|height|density)\s*=',line)]
    lines+=['hw.lcd.width=900','hw.lcd.height=1600','hw.lcd.density=240']
    path.write_text('\n'.join(lines)+'\n',encoding='utf-8')
print('Configured disposable CI physical display: 900x1600; production device unchanged.')
