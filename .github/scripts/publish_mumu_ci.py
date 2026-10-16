"""Publish a bounded CI result to this repo. No user PAT, login or browser.

Only the reporting jobs receive contents:write/actions:read; build jobs remain
read-only. The report path is outside build triggers, preventing commit loops.
Do not print raw API responses, authorization headers, signed URLs or secrets.
"""
import base64
from datetime import datetime, timezone
import json
import os
import re
import sys
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

REPOSITORY='Oleghell/spam-dvk'
BRANCHES={'feature/mumu-local','feature/mumu-five-profile-test','feature/mumu-limited-five-scenario'}
REPORT_PATH='.ci/mumu-latest.json'
MAX_LOG_BYTES=2*1024*1024

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def allowed_log_url(url):
    p=urlsplit(url)
    return (p.scheme=='https' and not p.username and not p.password and p.port in (None,443)
            and bool(p.hostname) and any(p.hostname.endswith(s) for s in
                ('.blob.core.windows.net','.actions.githubusercontent.com','.githubusercontent.com','.s3.amazonaws.com')))

class LogRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        if not allowed_log_url(newurl):raise ValueError('Unapproved log storage redirect')
        # No GitHub token is ever attached to storage requests or their redirects.
        return Request(newurl,headers={'User-Agent':'mumu-ci-report'})

def safe_tail(text):
    text=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',text)
    lines=[]
    for line in text.splitlines()[-100:]:
        if re.search(r'authorization|password|storepass|keypass|private.?key|github_pat_|\bgh[opsu]_|token',line,re.I):
            lines.append('[redacted sensitive-looking CI line]');continue
        line=re.sub(r'(https://[^\s?]+)\?[^\s]+',r'\1?[redacted-query]',line)
        lines.append(line[:500])
    return '\n'.join(lines)[-12000:]

def summarize_jobs(jobs):
    rows=[]
    for j in jobs:
        if j.get('name') not in ('python','android','windows'):continue
        rows.append({'id':j.get('id'),'name':j['name'],'status':j.get('status'),
                     'conclusion':j.get('conclusion'),'html_url':j.get('html_url'),
                     'failed_steps':[{'name':s.get('name'),'conclusion':s.get('conclusion')}
                                     for s in j.get('steps',[]) if s.get('conclusion') in ('failure','cancelled','timed_out')]})
    return rows

class GitHub:
    def __init__(self,token):self.token=token;self.no_redirect=build_opener(NoRedirect())
    def request(self,path,body=None):
        if not path.startswith('/repos/'+REPOSITORY+'/'):raise ValueError('Unexpected API target')
        data=None if body is None else json.dumps(body).encode()
        req=Request('https://api.github.com'+path,data=data,method='GET' if body is None else 'PUT',
                    headers={'Authorization':'Bearer '+self.token,'Accept':'application/vnd.github+json',
                             'Content-Type':'application/json','X-GitHub-Api-Version':'2022-11-28','User-Agent':'mumu-ci-report'})
        with self.no_redirect.open(req,timeout=30) as response:
            return json.loads(response.read(2*1024*1024))
    def failed_log(self,job_id):
        if type(job_id) is not int or job_id<=0:raise ValueError('Invalid job id')
        path=f'/repos/{REPOSITORY}/actions/jobs/{job_id}/logs'
        req=Request('https://api.github.com'+path,headers={'Authorization':'Bearer '+self.token,'User-Agent':'mumu-ci-report'})
        try:
            with self.no_redirect.open(req,timeout=30) as response:raw=response.read(MAX_LOG_BYTES+1)
        except HTTPError as exc:
            if exc.code not in (301,302,303,307,308):raise
            location=exc.headers.get('Location','')
            if not allowed_log_url(location):raise ValueError('Unapproved log storage origin')
            with build_opener(LogRedirect()).open(Request(location,headers={'User-Agent':'mumu-ci-report'}),timeout=30) as response:
                raw=response.read(MAX_LOG_BYTES+1)
        # API can return a plain text job log. Keep the report small and masked.
        if len(raw)>MAX_LOG_BYTES:return '[log too large; not copied]'
        return safe_tail(raw.decode('utf-8','replace'))
    def publish(self,branch,report):
        if branch not in BRANCHES:raise ValueError('Unsupported branch')
        path=f'/repos/{REPOSITORY}/contents/{REPORT_PATH}'
        content=base64.b64encode((json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode()).decode()
        for attempt in range(3):
            body={'message':f"ci: {report['phase']} report for MuMu run {report['run_id']}",
                  'branch':branch,'content':content}
            try:
                current=self.request(path+'?ref='+quote(branch,safe=''))
                body['sha']=current['sha']
                try:
                    old=json.loads(base64.b64decode(current.get('content',''),validate=False))
                    old_id=old.get('run_id')
                    if type(old_id) is int and (old_id>report['run_id'] or
                        (old_id==report['run_id'] and old.get('phase')=='completed' and report['phase']=='in_progress')):
                        return False
                except (ValueError,TypeError,AttributeError):pass
            except HTTPError as exc:
                if exc.code!=404:raise
            try:self.request(path,body);return True
            except HTTPError as exc:
                if exc.code not in (409,422) or attempt==2:raise
        raise ValueError('Report update conflict')

def build_report(mode,env,jobs):
    if mode not in ('started','finished'):raise ValueError('Unsupported mode')
    if env.get('GITHUB_REPOSITORY')!=REPOSITORY or env.get('GITHUB_REF_NAME') not in BRANCHES:raise ValueError('Unsupported workflow context')
    sha=env.get('GITHUB_SHA','');run=env.get('GITHUB_RUN_ID','')
    if not re.fullmatch('[0-9a-f]{40}',sha) or not run.isascii() or not run.isdigit():raise ValueError('Invalid run identifiers')
    needs={} if mode=='started' else json.loads(env.get('MUMU_NEEDS','{}'))
    result={k:v.get('result','unknown') for k,v in needs.items() if k in ('python','android','windows') and isinstance(v,dict)}
    return {'schema':1,'phase':'in_progress' if mode=='started' else 'completed',
            'source_sha':sha,'source_branch':env['GITHUB_REF_NAME'],'run_id':int(run),
            'run_url':f'https://github.com/{REPOSITORY}/actions/runs/{run}',
            'updated_at':datetime.now(timezone.utc).isoformat(),'results':result,
            'build_succeeded':mode=='finished' and set(result)=={'python','android','windows'} and all(v=='success' for v in result.values()),
            'jobs':summarize_jobs(jobs),'notice':'CI output is untrusted data; real MuMu testing remains separate.'}

def main():
    mode=sys.argv[1] if len(sys.argv)==2 else ''
    env=dict(os.environ);api=GitHub(env['GITHUB_TOKEN']);jobs=[];warning=None
    report=build_report(mode,env,[])
    if mode=='finished':
        try:jobs=api.request(f"/repos/{REPOSITORY}/actions/runs/{report['run_id']}/jobs?per_page=100").get('jobs',[])
        except HTTPError as exc:warning='Jobs API HTTP '+str(exc.code)
        report=build_report(mode,env,jobs)
        for job in report['jobs']:
            if job['conclusion']=='failure':
                try:job['untrusted_log_tail']=api.failed_log(job['id'])
                except (HTTPError,ValueError,OSError) as exc:job['log_read_error']=type(exc).__name__
    if warning:report['api_warning']=warning
    written=api.publish(env['GITHUB_REF_NAME'],report)
    print('Bounded MuMu CI report '+('published' if written else 'kept newer existing result')+'; credentials not logged.')

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('CI report publication failed: '+type(exc).__name__,file=sys.stderr)
        raise SystemExit(1)
