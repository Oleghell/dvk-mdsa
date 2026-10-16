"""Bounded city diagnostics and focus recovery. Never input text or send.

No user scripts/coordinates, no downloads, no runtime code loading. A fallback
is allowed only after a known injected focus tap followed by native focused=false
in the same verified city context. Unknown effects stop the durable run.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from city_transport import CityTransport, CityInspectionError, city_context_sha256
from city_field import CITY_EDITOR_BOUNDS
from limited_scenario import CITIES
from mumu_bridge import BridgeError, content_pixel_sha256

FOCUS_POINTS = ((400,236),(240,236),(600,236))
SAMPLE_LIMIT = 3


def observe_city(reader):
    """Fresh bounded evidence; mask ONLY the already pinned native editor."""
    before=city_context_sha256(reader.screen())
    d=CityTransport(reader).inspect()
    png=reader.screen();after=city_context_sha256(png)
    if before!=after or d['city_context_sha256']!=after:
        raise CityInspectionError('City context changed; no action.',
                                  {'state':'denied_screen_changed','code':'context_changed'})
    return d,content_pixel_sha256(png)


def run_city_diagnostics(reader):
    samples=[];queries=[]
    for i in range(SAMPLE_LIMIT):
        try:
            d,_=observe_city(reader)
            query=d['query'];queries.append(query)
            samples.append({'sample':i+1,'ok':True,'bounds':d['bounds'],
                            'focused':d['focused'],'context_sha256':d['city_context_sha256'],
                            'query_kind':'empty' if query=='' else 'catalog' if query in CITIES else 'other',
                            'query_length':len(query)})
        except CityInspectionError as e:
            samples.append({'sample':i+1,'ok':False,'diagnostic':dict(e.details)})
            if e.details.get('code')=='wrong_package':break
        except BridgeError:
            # No raw exception/path/ADB output or screen text in saved reports.
            samples.append({'sample':i+1,'ok':False,'diagnostic':{'code':'read_refused'}})
            break
    hashes={s['context_sha256'] for s in samples if s['ok']}
    stable_query=len(set(queries))==1
    stable_focus=len({s['focused'] for s in samples if s['ok']})==1
    return {'schema':1,'suite':'city-readonly-v1','created_at':datetime.now(timezone.utc).isoformat(),
            'passed':len(samples)==SAMPLE_LIMIT and all(s['ok'] for s in samples) and len(hashes)==1 and stable_query and stable_focus,
            'query_stable':stable_query,'focus_stable':stable_focus,
            'sample_limit':SAMPLE_LIMIT,'samples':samples,'device_actions':0,'text_entered':False,
            'message_sent':False,'city_selected':False,'filters_applied':False}


def save_diagnostic_report(report):
    """Fixed local destination; no repo commits, screenshots, queries or secrets."""
    base=Path(os.environ.get('LOCALAPPDATA') or str(Path.home()/'.local/share'))/'DvkMuMu'/'diagnostics'
    try:
        base.mkdir(parents=True,exist_ok=True)
        tmp=base/'city-last.tmp';target=base/'city-last.json'
        tmp.write_text(json.dumps(report,ensure_ascii=True,indent=2)+'\n',encoding='utf-8',newline='\n')
        tmp.replace(target)
        return True
    except OSError:
        return False


def autofocus_city(reader,ledger,expected,run_ready,dispatch):
    if not isinstance(expected,str) or re.fullmatch('[0-9a-f]{64}',expected) is None:
        raise BridgeError('Нужен свежий CITY_CONTEXT_SHA256.')
    steps=[]
    def result(ok,already=False):
        return {'focus_verified':ok,'already_focused':already,'steps':steps,
                'tap_limit':len(FOCUS_POINTS),'text_entered':False,'message_sent':False,
                'city_selected':False,'filters_applied':False}
    run_ready()
    # Eligibility is checked even for a no-op; never inspect/mutate a live visit.
    ledger.check_city_focus_ready()
    first,_=observe_city(reader)
    if first['city_context_sha256']!=expected:
        raise BridgeError('Контекст города изменился; автофокус не начат.')
    original_query=first['query']
    if first['focused']:return result(True,True)
    used=ledger.city_focus_points_used()
    for index,point in enumerate(FOCUS_POINTS):
        if index in used:continue
        run_ready()
        d,sha=observe_city(reader)
        if d['city_context_sha256']!=expected or d['query']!=original_query:
            raise BridgeError('Окно или запрос изменились; запасные точки запрещены.')
        if d['focused']:return result(True)
        # Coordinates are compiled, strictly internal to the pinned editor.
        l,t,r,b=CITY_EDITOR_BOUNDS
        if not l<point[0]<r or not t<point[1]<b:raise BridgeError('Invalid compiled focus point')
        action=ledger.reserve_city_focus(index)
        try:
            injected=dispatch(reader.navigate,'tap',sha,*point)
            if not isinstance(injected,dict) or injected.get('input_injected') is not True:
                reader.action_uncertain=True
                raise BridgeError('Focus injection not confirmed')
        except BaseException:
            ledger.finish_city_focus(action,'unknown' if reader.action_uncertain else 'refused')
            raise
        try:
            after,_=observe_city(reader)
            if after['city_context_sha256']!=expected or after['query']!=original_query:
                raise BridgeError('Focus effect/context not confirmed')
        except BaseException:
            reader.action_uncertain=True
            ledger.finish_city_focus(action,'unknown')
            raise BridgeError('Исход фокуса не подтверждён; дальнейшие нажатия запрещены.') from None
        outcome='focused' if after['focused'] else 'no_focus'
        ledger.finish_city_focus(action,outcome)
        steps.append({'point_index':index,'point':list(point),'outcome':outcome})
        if after['focused']:return result(True)
        # Only KNOWN no-focus can progress to a DIFFERENT compiled point.
    return result(False)
