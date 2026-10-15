"""Temporary real HTTPS transport test with synthetic data only; always closes tunnel."""
import json, queue, re, secrets, subprocess, threading, time, urllib.request, urllib.error
from pathlib import Path
import os
from mumu_bridge import BridgeServer
class TestReader:
    def status(self): return {'connected':True,'synthetic_test':True,'read_only':True}
    def screen(self): raise RuntimeError('No real device or screen in this test')
key=secrets.token_urlsafe(32)
server=BridgeServer(TestReader(),key)
threading.Thread(target=server.serve_forever,daemon=True).start()
proc=None
try:
    proc=subprocess.Popen([os.environ.get('CLOUDFLARED_TEST_PATH',str(Path(__file__).parent/'cloudflared-linux')),'tunnel','--protocol','http2','--url','http://127.0.0.1:'+str(server.server_port)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    lines=queue.Queue()
    def read():
        for line in proc.stdout:
            lines.put(line)
            if b'ERR' in line or b'Registered tunnel' in line: print(line.decode('utf-8','replace').strip(),flush=True)
    threading.Thread(target=read,daemon=True).start()
    deadline=time.time()+90; url=None
    while time.time()<deadline:
        try: line=lines.get(timeout=1).decode('utf-8','replace')
        except queue.Empty: continue
        match=re.search(r'https://[a-z0-9-]+\.trycloudflare\.com',line)
        if match: url=match.group(); break
    if not url: raise RuntimeError('No temporary tunnel URL within 90 seconds')
    server.public_url=url
    print('Temporary synthetic-test endpoint:', url,flush=True)
    def request(method,params=None,auth=True):
        headers={'Content-Type':'application/json','Accept':'application/json'}
        if auth: headers['Authorization']='Bearer '+key
        req=urllib.request.Request(url+'/mcp',data=json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params or {}}).encode(),headers=headers)
        try:
            with urllib.request.urlopen(req,timeout=20) as res: return res.status,json.load(res)
        except urllib.error.HTTPError as e: return e.code,None
    # DNS and edge propagation can lag hostname creation.
    for attempt in range(30):
        try:
            status,obj=request('initialize',{'protocolVersion':'2025-03-26'})
            if status==200: break
            print('HTTP',status,flush=True)
        except (OSError,urllib.error.URLError) as e: print('Network:',type(e).__name__,str(e)[:160],flush=True)
        time.sleep(3)
    else: raise RuntimeError('Tunnel created but HTTPS endpoint not reachable from this sandbox')
    assert obj['result']['serverInfo']['name']=='mumu-readonly'
    assert request('tools/list')[1]['result']['tools'][0]['name']=='mumu_status'
    obj=request('tools/call',{'name':'mumu_status'})[1]
    assert json.loads(obj['result']['content'][0]['text'])['synthetic_test'] is True
    assert request('tools/list',auth=False)[0]==401
    server.token=''
    assert request('tools/list')[0]==401
    print(json.dumps({'real_https_tunnel':'passed','initialize':'passed','tool_discovery':'passed','synthetic_status':'passed','unauthenticated_blocked':True,'revocation_checked':True,'real_phone_used':False,'real_screens_transmitted':False}))
finally:
    server.token='';server.shutdown();server.server_close()
    if proc:
        proc.terminate()
        try: proc.wait(timeout=10)
        except subprocess.TimeoutExpired: proc.kill();proc.wait()
