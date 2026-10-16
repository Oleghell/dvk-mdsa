"""Isolated, pinned city-only Android transport. No result taps or message text."""
import base64
import hashlib
import hmac
import json
from pathlib import Path
import re
from io import BytesIO
from PIL import Image
from city_field import CITY_ANCHORS, CITY_EDITOR_BOUNDS
from city_release import CITY_COMPONENT, CITY_APK_SHA256, CITY_CATALOG
from limited_scenario import CITIES
from mumu_bridge import BridgeError, SERIAL, ACTION_LIMIT


def city_args_allowed(args, ready):
    prefix=['-s',SERIAL,'shell','am','instrument','-w','-r','-e','op']
    if not (ready is True and isinstance(args,list) and len(args)==20 and args[:9]==prefix
            and args[10:12]==['-e','expected_content_sha256']
            and isinstance(args[12],str) and re.fullmatch('[0-9a-f]{64}',args[12])
            and args[13:15]==['-e','x'] and args[16:18]==['-e','y']
            and args[19]==CITY_COMPONENT):return False
    x,y=args[15],args[18]
    if not (isinstance(x,str) and isinstance(y,str) and re.fullmatch('0|[1-9][0-9]?',x)
            and re.fullmatch('0|[1-9][0-9]?',y)):return False
    return ((args[9]=='inspect_city' and x==y=='0') or
            (args[9]=='city_input' and 0<=int(x)<30 and 0<=int(y)<=30))


def city_context_sha256(png):
    try:
        with Image.open(BytesIO(png)) as im:
            if im.format!='PNG' or im.size!=(900,1600):raise ValueError()
            rgb=im.convert('RGB')
        for box,sha in CITY_ANCHORS:
            if hashlib.sha256(rgb.crop(box).tobytes()).hexdigest()!=sha:raise ValueError()
        rgb.paste((0,0,0),tuple(CITY_EDITOR_BOUNDS))
        return hashlib.sha256(rgb.crop((0,48,900,1600)).tobytes()).hexdigest()
    except (ValueError,OSError,TypeError):
        raise BridgeError('Неподдержанное окно поиска города; ввода не было.') from None


class CityTransport:
    def __init__(self,reader):self.reader=reader
    def install(self,base):
        path=(Path(base)/'city-helper.apk').resolve()
        try:
            if hashlib.sha256(path.read_bytes()).hexdigest()!=CITY_APK_SHA256:raise ValueError()
        except (OSError,ValueError):
            raise BridgeError('Отдельный APK города отсутствует или повреждён.') from None
        self.reader.city_helper_path=path
        output=self.reader._run(['-s',SERIAL,'install','-t','-r',str(path)])
        if b'Success' not in output:raise BridgeError('Помощник города не установлен. Автоудаления нет.')
        self.reader.city_helper_ready=True
    def _instrument(self,op,expected='0'*64,x=0,y=0):
        args=['-s',SERIAL,'shell','am','instrument','-w','-r','-e','op',op,
              '-e','expected_content_sha256',expected,'-e','x',str(x),'-e','y',str(y),CITY_COMPONENT]
        if not city_args_allowed(args,self.reader.city_helper_ready):raise BridgeError('Команда города не разрешена.')
        self.reader._foreground()
        output=self.reader._run(args).decode('utf-8','replace')
        states=re.findall(r'^INSTRUMENTATION_RESULT: navigation_status=([a-z_]+)\s*$',output,re.M)
        if len(states)!=1:raise BridgeError('Исход Android-команды города неизвестен; повтор запрещён.')
        return states[0],output
    @staticmethod
    def _inspection_error(state, output):
        states={'denied_field','denied_arguments','denied_context_or_layout','denied_operation','denied_screen_changed'}
        reasons={'node_not_ready','root_not_ready','wrong_package','tree_truncated','editor_invalid','editor_bounds',
                 'screenshot_unavailable','screen_size','title_anchor','search_anchor','query_length',
                 'context_changed','internal_error'}
        code=re.findall(r'^INSTRUMENTATION_RESULT: city_diagnostic_code=([a-z_]+)\s*$',output,re.M)
        safe_state=state if state in states else 'invalid_inspection_response'
        safe_reason=code[0] if len(code)==1 and code[0] in reasons else 'not_reported'
        phases={'startup','inspect_before','inspect_confirm','input_before','input_confirm','input_after'}
        phase=re.findall(r'^INSTRUMENTATION_RESULT: city_diagnostic_phase=([a-z_]+)\s*$',output,re.M)
        details='; phase='+phase[0] if len(phase)==1 and phase[0] in phases else ''
        bounds=re.findall(r'^INSTRUMENTATION_RESULT: actual_editor_bounds=(-?[0-9]{1,5},-?[0-9]{1,5},-?[0-9]{1,5},-?[0-9]{1,5})\s*$',output,re.M)
        if safe_reason=='editor_bounds' and len(bounds)==1:
            values=[int(v) for v in bounds[0].split(',')]
            if all(-10000<=v<=10000 for v in values):details+='; actual_bounds='+str(values)
        return BridgeError('Проверка города отказала до ввода: '+safe_state+' / '+safe_reason+details+'. Автоповтора ввода нет.')
    def inspect(self):
        state,output=self._instrument('inspect_city')
        if state!='city_inspection_ok':raise self._inspection_error(state,output)
        data=re.findall(r'^INSTRUMENTATION_RESULT: layout_b64=([A-Za-z0-9+/=]+)\s*$',output,re.M)
        try:
            if state!='city_inspection_ok' or len(data)!=1:raise ValueError()
            d=json.loads(base64.b64decode(data[0],validate=True).decode('utf-8'))
            if (not isinstance(d,dict) or d.get('catalog')!=CITY_CATALOG
                or not isinstance(d.get('query'),str) or len(d['query'])>128
                or type(d.get('focused')) is not bool or d.get('bounds')!=CITY_EDITOR_BOUNDS
                or any(type(v) is not int for v in d['bounds'])
                or not isinstance(d.get('city_context_sha256'),str)
                or not re.fullmatch('[0-9a-f]{64}',d['city_context_sha256'])
                or any(d.get(k) is not False for k in ('result_rows_available','city_selected','filters_applied'))):raise ValueError()
        except (ValueError,TypeError,UnicodeError,KeyError):
            raise BridgeError('Некорректный ответ проверки города: invalid_inspection_response. Ввода не было.') from None
        return dict(d,catalog_cities=list(CITIES))
    def preflight(self,expected,index,previous):
        if (type(index) is not int or not 0<=index<30 or type(previous) is not int
                or not -1<=previous<30 or index==previous
                or not isinstance(expected,str) or not re.fullmatch('[0-9a-f]{64}',expected)):
            raise BridgeError('Разрешён только другой город из каталога city-v1.')
        if self.reader.action_uncertain or self.reader.action_attempts>=ACTION_LIMIT:
            raise BridgeError('Лимит действий или неизвестный предыдущий исход; ввод запрещён.')
        if not self.reader.city_helper_ready:raise BridgeError('Отдельный помощник города не установлен.')
        if not hmac.compare_digest(city_context_sha256(self.reader.screen()),expected):
            raise BridgeError('Окно/результаты поиска изменились; сначала прочитайте их заново.')
        d=self.inspect()
        old='' if previous==-1 else CITIES[previous]
        if not d['focused'] or d['query']!=old or d['city_context_sha256']!=expected:
            raise BridgeError('Сначала сфокусируйте поле города; запрос и контекст должны совпасть.')
        return d
    def input(self,expected,index,previous):
        self.preflight(expected,index,previous)
        self.reader.action_attempts+=1;self.reader.action_uncertain=True
        state,output=self._instrument('city_input',expected,index,previous+1)
        if state in ('denied_screen_changed','denied_field','denied_context_or_layout','denied_arguments','denied_operation'):
            self.reader.action_uncertain=False
            raise self._inspection_error(state,output)
        if state!='city_input_native_verified':
            raise BridgeError('Исход ввода города неизвестен; повтор запрещён.')
        self.reader.action_uncertain=False
        return {'native_query_verified':True,'query':CITIES[index],'catalog':CITY_CATALOG,
                'city_selected':False,'filters_applied':False,'message_sent':False,
                'action_attempts':self.reader.action_attempts}
