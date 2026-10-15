# Offline sanitizer test. No account, device, ADB or network required.
$ErrorActionPreference = 'Stop'
function Stop-Safely([string]$Message) { throw $Message }
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'ui-inspect.ps1')
$fixture = @'
<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
 <node package="drug.vokrug" class="android.widget.FrameLayout" resource-id="drug.vokrug:id/root" bounds="[0,0][1080,1920]" text="PRIVATE_PERSON" content-desc="PRIVATE_DESCRIPTION" clickable="false" enabled="true">
  <node package="drug.vokrug" class="android.widget.EditText" resource-id="drug.vokrug:id/message" bounds="[100,900][900,1000]" text="PRIVATE_MESSAGE" content-desc="PRIVATE_PHONE" clickable="true" enabled="true" focused="true"/>
  <node package="drug.vokrug" class="android.widget.ImageButton" resource-id="drug.vokrug:id/send" bounds="[900,900][1080,1000]" text="" content-desc="Send" clickable="true" enabled="true"/>
 </node>
 <node package="other.package" class="android.widget.TextView" resource-id="other.package:id/data" text="PRIVATE_OTHER_APP"/>
</hierarchy>
'@
$result = ConvertTo-SafeUiReport $fixture
$json = $result | ConvertTo-Json -Depth 8
if ($result.node_count -ne 3) { throw 'Incorrect app node filtering' }
if ($json -match 'PRIVATE_') { throw 'Private value leaked' }
if ($result.text_values_exported -ne $false) { throw 'Invalid text export flag' }
if ($result.nodes[1].semantic_hint -ne 'editable_field') { throw 'Missing field hint' }
if ($result.nodes[2].semantic_hint -ne 'send_label') { throw 'Missing send hint' }
if ($result.nodes[1].parent_resource_id -ne 'drug.vokrug:id/root') { throw 'Missing parent id' }
if ($null -ne (Get-SafeResourceId 'INVALID with spaces')) { throw 'Invalid id accepted' }
$rejected = $false
try { ConvertTo-SafeUiReport '<!DOCTYPE x [<!ENTITY a "secret">]><hierarchy>&a;</hierarchy>' } catch { $rejected = $true }
if (-not $rejected) { throw 'DTD accepted' }
$window = 'mCurrentFocus=Window{aa11 u0 drug.vokrug/.MainActivity}'
if ((Find-ForegroundPackage $window) -cne 'drug.vokrug') { throw 'Window parser failed' }
$activity = 'topResumedActivity=ActivityRecord{ab12 u0 drug.vokrug/.MainActivity t12}'
if ((Find-ForegroundPackage $activity) -cne 'drug.vokrug') { throw 'Top resumed parser failed' }
$legacy = 'mResumedActivity: ActivityRecord{ac13 u0 drug.vokrug/.MainActivity t12}'
if ((Find-ForegroundPackage $legacy) -cne 'drug.vokrug') { throw 'Resumed parser failed' }
if ($null -ne (Find-ForegroundPackage 'mCurrentFocus=null')) { throw 'Null focus accepted' }
if ($null -ne (Find-ForegroundPackage 'Hist #1: ActivityRecord{ab u0 drug.vokrug/.MainActivity t1}')) { throw 'Historical activity accepted' }
Write-Host 'Offline UI sanitizer and foreground parser tests passed.'
