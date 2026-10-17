"""Named supervised actions using a generic UI engine, not business-layer XY.

Existing greeting/history/send safeguards remain the compatibility workflow;
this adapter never auto-sends, reopens a skipped visit or resets profile limits.
"""
import logging
from ui_model import UIError,ElementNotFound,UnsupportedUI,detect_screen
from ui_runtime import AndroidUI
from ui_backend import NativeBackend,ProfileVisionFallback
from ui_ocr import TesseractFallback
from ui_protocol import valid_tool

LOG=logging.getLogger('dvk.ui')
LABELS={
 'open_filters':({'description':'Настройки поиска'},{'text':'Настройки поиска'}),
 'open_city':({'description':'Город'},{'text':'Город'}),
 'apply_filters':({'description':'Применить'},{'text':'Применить'},{'text':'Готово'}),
 'open_chat':({'description':'Открыть чат'},{'text':'Открыть чат'},{'text':'Написать'}),
}
REFUSALS={'denied_arguments','denied_context','denied_screen_changed','denied_not_found','denied_ambiguous','denied_incomplete','denied_field','denied_unsupported'}

class UIWorkflow:
    def __init__(self,supervised):
        self.supervised=supervised;self.reader=supervised.inner;self.ledger=supervised.ledger
        self.backend=NativeBackend(self.reader,self.ledger)
        self.ui=AndroidUI(self.backend,self._mutate,TesseractFallback(self.reader.screen),ProfileVisionFallback(self.backend))
        self.action=None;self.allow_fallback=False
    def inspect(self):
        tree,state=self.ui.inspect()
        return {'tree_sha256':tree.context,'width':tree.width,'height':tree.height,'rotation':tree.rotation,'density_dpi':tree.density_dpi,
                'nodes':list(tree.nodes),'screen':state,'fallback_policy':'hierarchy -> optional local OCR -> target-specific CV',
                'coordinate_api':False,'sending_scope':'legacy guarded finite workflow only'}
    def find(self,query,timeout_ms=0,allow_fallback=False):
        element=self.ui.find_element(**query,timeout=timeout_ms/1000,allow_fallback=allow_fallback)
        return {'selector':element.query,'node':element.node,'method':element.method,'tree_sha256':element.context,
                'identity_verified':False,'action_performed':False}
    def _between(self):
        from test_session import TERMINAL_VISITS
        current=self.ledger.current()
        if current is not None and current['state'] not in TERMINAL_VISITS:raise UnsupportedUI('Finish current profile before changing search settings')
    def _reserve(self,ident):
        with self.ledger.transaction():
            self.ledger._no_hold()
            if self.ledger.db.execute('SELECT COUNT(*) FROM control_actions').fetchone()[0]>=500:raise UnsupportedUI('Persistent action limit exhausted; no reset')
            if self.ledger.db.execute('SELECT 1 FROM control_actions WHERE id=?',(ident,)).fetchone():raise UnsupportedUI('Action ID already reserved; no replay')
            if self.action=='open_chat':
                visit=self.ledger._visit(('opening','chat_opening'))
                key='semantic-profile:'+visit['id']
                if self.ledger.db.execute('SELECT 1 FROM control_config WHERE key=?',(key,)).fetchone():raise UnsupportedUI('Open-chat attempt already recorded for this visit')
                self.ledger.db.execute('INSERT INTO control_config VALUES (?,?)',(key,ident))
            self.ledger.db.execute('INSERT INTO control_actions VALUES (?,?)',(ident,'reserved'))
    def _execute(self,ident,fn,expected='input_injected'):
        self.supervised._run_ready();self.backend.control.ready();self._reserve(ident)
        self.reader.action_attempts+=1;self.reader.action_uncertain=True
        try:
            state,data=fn()
            if state in REFUSALS:
                LOG.warning('[ERROR] Native action refused: %s',state)
                self.backend.control.finish(ident,'refused');self.reader.action_uncertain=False
                raise UIError('Native action refused before injection: '+state+'; do not retry automatically')
            if state!=expected:raise UIError('Unknown native action outcome; no retry')
        except BaseException:
            if self.reader.action_uncertain:
                LOG.error('[ERROR] Native outcome unknown; persistent journal stopped')
                self.backend.control.finish(ident,'unknown')
            raise
        self.backend.control.finish(ident,'succeeded');self.reader.action_uncertain=False
        return dict(data,native_status=state,result_screen_verified=False,message_sent=False,test_session=self.ledger.status())
    def _mutate(self,element,operation,*,action_id,purpose,**args):
        if purpose!=self.action or self.action is None:raise UnsupportedUI('Named action authorization missing')
        if element.method=='profile_cv' and purpose!='open_chat':raise UnsupportedUI('Profile vision only authorizes open_chat')
        # There is no public arbitrary-selector mutation tool. Only the named
        # action dispatcher below may call this policy-bound engine.
        return self._execute(action_id,lambda:self.backend.perform(element,operation,**args),expected='text_verified' if operation=='set_text' else 'input_injected')
    def action_call(self,args):
        if not valid_tool('mumu_ui_action',args):raise UIError('Invalid named UI action')
        self.supervised._run_ready();self.backend.control.ready()
        self.action=args['action'];ident=args['action_id'];self.allow_fallback=args['allow_fallback']
        action=self.action
        if action in ('open_filters','open_city','apply_filters','enable_online','input_city','select_city','open_profile'):self._between()
        if action in ('open_filters','open_city'):
            self.supervised.online_confirmed=False
            e=self.ui.find_element(alternatives=LABELS[action],timeout=2,allow_fallback=self.allow_fallback)
        elif action=='apply_filters':
            # Never infer a checkmark from OCR or mere presence of the label.
            self.ui.find_element(text='Только онлайн',checkable=True,checked=True)
            self.supervised.online_confirmed=False
            e=self.ui.find_element(alternatives=LABELS[action],timeout=2,allow_fallback=self.allow_fallback)
        elif action=='enable_online':
            e=self.ui.find_element(text='Только онлайн',checkable=True,enabled=True)
            if e.node['checked']:return {'already_enabled':True,'action_performed':False}
        elif action=='input_city':
            from limited_scenario import CITIES
            tree,state=self.ui.inspect()
            if state['state']!='city_search':raise UnsupportedUI('Native city-search state is not proven; use compatibility diagnostics, not a guessed editor')
            city=CITIES[args['city_index']]
            e=self.ui.find_element(class_name='android.widget.EditText',editable=True,enabled=True)
            if e.node['text'] not in ('',*CITIES):raise UnsupportedUI('Unrelated existing text will not be cleared')
            previous=CITIES.index(e.node['text']) if e.node['text'] else -1
            city_action=self.ledger.reserve_city_input(args['city_index'],previous)
            self.supervised.online_confirmed=False
            try:result=e.set_text(city,action_id=ident,purpose=action,expected_text=e.node['text'])
            except BaseException:
                self.ledger.finish_city_input(city_action,'unknown' if self.reader.action_uncertain else 'refused')
                raise
            self.ledger.finish_city_input(city_action,'verified')
            return result
        elif action=='select_city':
            from limited_scenario import CITIES
            city=CITIES[args['city_index']];tree,state=self.ui.inspect()
            if state['state']!='city_search':raise UnsupportedUI('City picker state not proven')
            field=tree.find({'class_name':'android.widget.EditText','editable':True,'text':city})
            e=self.ui.find_element(text=city,editable=False,below={'class_name':'android.widget.EditText','editable':True,'text':city},first=True)
            if e.node['bounds'][1]<field['bounds'][3]:raise UnsupportedUI('Result is not below the query field')
        elif action=='open_profile':
            if not self.supervised.online_confirmed:raise UnsupportedUI('Online filter application has not been confirmed')
            # An explicit native search-results container is required. A Unity
            # surface or a generic Search label is not proof of being in grid.
            self.ui.find_element(description='Результаты поиска')
            label=args['target'];e=self.ui.find_element(alternatives=[{'description':label,'clickable':True},{'clickable':True,'child':{'text':label}}])
            self.ledger.begin_visit()
        elif action=='open_chat':
            visit=self.ledger._visit(('opening','chat_opening'))
            if visit['fingerprint'] is not None:raise UnsupportedUI('Chat already verified; reopening prohibited')
            e=self.ui.find_element(alternatives=LABELS[action],timeout=2,allow_fallback=self.allow_fallback)
            if visit['state']=='opening':self.ledger.transition(('opening',),'chat_opening')
        elif action=='focus_editor':
            self.ledger._visit(('chat_opening','empty_checked'))
            e=self.ui.find_element(class_name='android.widget.EditText',editable=True,enabled=True)
            if e.node['text']:raise UnsupportedUI('Nonempty draft will not be focused automatically')
        elif action=='back':
            self.ledger._visit(('skip_ready','sent_observed'))
            tree,_=self.ui.inspect()
            return self._execute(ident,lambda:self.backend.back(tree.context))
        else:raise UnsupportedUI('Action not implemented')
        try:result=e.click(action_id=ident,purpose=action)
        except BaseException:
            if action=='open_profile' and not self.reader.action_uncertain:self.ledger.skip()
            raise
        if action=='enable_online':
            self.ui.wait_for_element(text='Только онлайн',checkable=True,checked=True,timeout=2)
            result['online_checked_verified']=True
        elif action=='apply_filters':
            # Only a new hierarchy showing search results confirms application.
            self.ui.wait_for_element(description='Результаты поиска',timeout=2)
            self.supervised.online_confirmed=True
        return result
