"""Explicit one-time branch cleanup after a verified main build; preserve every tip."""
import json,os,subprocess
from urllib.parse import quote
REPO=os.environ['GITHUB_REPOSITORY']
if os.environ.get('GITHUB_REF')!='refs/heads/main':raise SystemExit('main required')
HEADS={
 'codex/hierarchy-production-hardening':'beb73533a0ee9f2696d454618231e525a629ba04',
 'codex/production-readiness':'a82e877633ba37f5ff726330261af9eef12e0878',
 'feature/android-ui-hierarchy':'67b0bb38c8974a7decd4586fb2d961ce2efeab84',
 'feature/mumu-five-profile-test':'63514e6794f9149ac9117c8c9b84616e920b5525',
 'feature/mumu-limited-five-scenario':'0cebed2b579097607505fd2ed5c96e664a808f2c',
 'feature/mumu-local':'a82c3cd57c81ccf46f46913aaaa2b89cfa75aebe',
 'fix/dialog-selection-diagnostics':'2ce54aeb546af2e9aa49989f81ce1b0294d8a24c',
 'snapshot/morelogin-ocr-2026-10-15':'d413e5dd82a355fdcb6bae381d4bcc4121ad781a'}
def api(method,path,**fields):
    cmd=['gh','api','--method',method,'repos/'+REPO+'/'+path]
    for k,v in fields.items():cmd+=['-f',k+'='+v]
    result=subprocess.run(cmd,check=True,capture_output=True,text=True)
    return json.loads(result.stdout) if result.stdout.strip() else None
def archive(name,sha):
    path='git/ref/tags/'+quote('archive/before-morelogin/'+name,safe='')
    result=subprocess.run(['gh','api','repos/'+REPO+'/'+path],capture_output=True,text=True)
    if result.returncode==0:
        if json.loads(result.stdout)['object']['sha']!=sha:raise SystemExit('archive tag mismatch')
    else:api('POST','git/refs',ref='refs/tags/archive/before-morelogin/'+name,sha=sha)
# First preserve the old default branch as well; no branch deletion before all tags exist.
archive('main','d413e5dd82a355fdcb6bae381d4bcc4121ad781a')
branches={x['name']:x['commit']['sha'] for x in api('GET','branches?per_page=100')}
if branches.get('mumu')!='2ce54aeb546af2e9aa49989f81ce1b0294d8a24c':raise SystemExit('MuMu backup differs')
selected={}
for name,expected in HEADS.items():
    if name not in branches:continue
    if branches[name]!=expected:raise SystemExit('Branch changed; manual review: '+name)
    selected[name]=expected
if 'morelogin' in branches:
    sha=branches['morelogin']
    subprocess.run(['git','merge-base','--is-ancestor',sha,os.environ['GITHUB_SHA']],check=True)
    selected['morelogin']=sha
for name,sha in selected.items():archive(name,sha)
for name,sha in selected.items():
    if name in ('main','mumu'):raise SystemExit('protected branch')
    current=api('GET','git/ref/heads/'+quote(name,safe=''))['object']['sha']
    if current!=sha:raise SystemExit('Branch changed after archival')
    api('DELETE','git/refs/heads/'+quote(name,safe=''))
    print('Archived and removed: '+name)
