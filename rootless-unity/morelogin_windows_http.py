"""Windows .NET HTTPS transport matching the successful local auth diagnostic.
Fixed code, no shell, no secrets in arguments/files, no redirects/proxy/TLS bypass.
Only the two documented read-only MoreLogin Open API operations are supported.
"""
import base64
import io
import json
import os
from pathlib import Path
import subprocess
import urllib.error
from morelogin_common import CloudError

LIMIT = 2 * 1024 * 1024
SCRIPT = r'''
$ErrorActionPreference = 'Stop'
Set-PSDebug -Off
[Console]::InputEncoding = New-Object Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$reply = @{ error='api-unavailable' }
$response=$null; $request=$null; $bytes=$null
try {
    $payload = [Console]::In.ReadToEnd() | ConvertFrom-Json
    if ($payload.path -notin @('/oauth2/token','/cloudphone/batchAdbInfo')) { throw 'Invalid endpoint' }
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $request = [Net.HttpWebRequest]::Create('https://api.morelogin.com' + $payload.path)
    $request.Method='POST'
    $request.ContentType='application/json'
    $request.Accept='application/json'
    $request.Proxy=$null
    $request.AllowAutoRedirect=$false
    $request.Timeout=25000
    $request.ReadWriteTimeout=25000
    if ($payload.path -eq '/cloudphone/batchAdbInfo') {
        if ($payload.token -notmatch '^[A-Za-z0-9_.~-]{16,16384}$') { throw 'Invalid token' }
        $request.Headers['Authorization']='Bearer ' + $payload.token
    } elseif ($payload.token) { throw 'Unexpected token' }
    $bytes=[Text.Encoding]::UTF8.GetBytes($payload.body)
    if ($bytes.Length -gt 65536) { throw 'Invalid size' }
    $request.ContentLength=$bytes.Length
    $stream=$request.GetRequestStream()
    try { $stream.Write($bytes,0,$bytes.Length) } finally { $stream.Dispose() }
    try { $response=$request.GetResponse() }
    catch [Net.WebException] {
        if ($null -eq $_.Exception.Response) { throw }
        $response=$_.Exception.Response
    }
    $status=[int]$response.StatusCode
    if ($status -lt 200 -or $status -ge 300) {
        # HTTP errors never export body, headers, URLs or server text.
        $reply=@{ status=$status; body='' }
    } else {
        $source=$response.GetResponseStream()
        $memory=New-Object IO.MemoryStream
        try {
            $buffer=New-Object byte[] 8192
            while (($read=$source.Read($buffer,0,$buffer.Length)) -gt 0) {
                if (($memory.Length+$read) -gt 2097152) { throw 'Response too large' }
                $memory.Write($buffer,0,$read)
            }
            $reply=@{ status=$status; body=[Convert]::ToBase64String($memory.ToArray()) }
        } catch {
            $reply=@{ error='api-response' }
        } finally { $source.Dispose(); $memory.Dispose() }
    }
} catch [Net.WebException] {
    $code=switch ([string]$_.Exception.Status) {
        'NameResolutionFailure' { 'api-dns' }
        'Timeout' { 'api-timeout' }
        'TrustFailure' { 'api-tls' }
        'SecureChannelFailure' { 'api-tls' }
        default { 'api-network' }
    }
    $reply=@{ error=$code }
} catch { $reply=@{ error='api-unavailable' } }
finally {
    if ($null -ne $response) { $response.Close() }
    if ($null -ne $request) { $request.Abort() }
    if ($null -ne $bytes) { [Array]::Clear($bytes,0,$bytes.Length) }
    $payload=$null; $bytes=$null
}
[Console]::Out.Write(($reply | ConvertTo-Json -Compress))
'''


def command():
    # Never resolve PowerShell via PATH or execute anything from the app directory.
    root = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    exe = root/'System32'/'WindowsPowerShell'/'v1.0'/'powershell.exe'
    if not root.is_absolute() or not exe.is_file():
        raise CloudError('api-transport')
    encoded = base64.b64encode(SCRIPT.encode('utf-16-le')).decode('ascii')
    return [str(exe), '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded]


class WindowsOpener:
    def open(self, request, timeout):
        paths = ('/oauth2/token', '/cloudphone/batchAdbInfo')
        path = next((p for p in paths if request.full_url == 'https://api.morelogin.com'+p), None)
        if path is None or request.get_method() != 'POST' or not isinstance(request.data, bytes) or len(request.data)>65536:
            raise CloudError('configuration')
        auth = request.get_header('Authorization')
        if auth is not None and (path!='/cloudphone/batchAdbInfo' or not auth.startswith('Bearer ')):
            raise CloudError('configuration')
        token = auth[7:] if auth else None
        payload = json.dumps({'path':path, 'body':request.data.decode('utf-8'), 'token':token}).encode('utf-8')
        child = None
        try:
            child = subprocess.Popen(command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            output,_ = child.communicate(payload,timeout=35)
            if child.returncode != 0 or len(output)>LIMIT*2:
                raise CloudError('api-transport')
            reply = json.loads(output.decode('utf-8-sig'))
            if not isinstance(reply, dict):raise ValueError()
            if 'error' in reply:
                allowed={'api-dns','api-timeout','api-tls','api-network','api-response','api-unavailable'}
                raise CloudError(reply['error'] if reply['error'] in allowed else 'api-transport')
            status=reply.get('status')
            if type(status) is not int or not 100<=status<=599:raise ValueError()
            if not 200<=status<300:
                raise urllib.error.HTTPError(request.full_url,status,'MoreLogin HTTP error',{},io.BytesIO())
            data=base64.b64decode(reply['body'],validate=True)
            if len(data)>LIMIT:raise ValueError()
            return io.BytesIO(data)
        except subprocess.TimeoutExpired:
            if child is not None:
                child.kill();child.communicate()
            raise CloudError('api-timeout') from None
        except (CloudError, urllib.error.HTTPError):
            raise
        except OSError:
            raise CloudError('api-transport') from None
        except Exception:
            raise CloudError('api-response') from None
