param(
    [Parameter(Mandatory)][ValidateSet('arm', 'disarm', 'status')][string]$Mode,
    [string[]]$Only,
    [string]$NvrHost = '192.168.8.1',
    [string]$User = $env:NVR_USER,
    [string]$Pass = $env:NVR_PASS
)
# Arm/disarm = pridėti/pašalinti <notificationMethod>center</notificationMethod> (Notify Surveillance Center)
# įvykių linkage'e. Hik-Connect push siunčiamas tik kai center yra.
# NVR leidžia tik SHA-256 digest, todėl curl --digest netinka.

$Base = "http://$NvrHost"
# Įvykiai, kurie originaliai turėjo center (be diskfull - sisteminį įspėjimą paliekam visada).
$Triggers = @('VMD-2', 'VMD-3', 'VMD-4', 'VMD-6', 'VMD-7', 'VMD-8') + (1..8 | ForEach-Object { "fielddetection-$_" })
if ($Only) { $Triggers = $Triggers | Where-Object { $_ -in $Only } }
$CenterXml = "<EventTriggerNotification>`n<id>center</id>`n<notificationMethod>center</notificationMethod>`n</EventTriggerNotification>`n"

function Get-Sha256([string]$s) {
    -join ([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($s)) | ForEach-Object { $_.ToString('x2') })
}

function Invoke-Isapi([string]$Method, [string]$Path, [string]$Body) {
    $r = Invoke-WebRequest -Uri "$Base$Path" -Method $Method -SkipHttpErrorCheck -UseBasicParsing
    $ch = @{}
    [regex]::Matches(($r.Headers['WWW-Authenticate'] | Select-Object -First 1), '(\w+)="([^"]*)"') |
        ForEach-Object { $ch[$_.Groups[1].Value] = $_.Groups[2].Value }
    $nc = '00000001'; $cn = [guid]::NewGuid().ToString('N')
    $ha1 = Get-Sha256 "${User}:$($ch.realm):${Pass}"
    $ha2 = Get-Sha256 "${Method}:${Path}"
    $resp = Get-Sha256 "${ha1}:$($ch.nonce):${nc}:${cn}:auth:${ha2}"
    $auth = "Digest username=`"$User`", realm=`"$($ch.realm)`", nonce=`"$($ch.nonce)`", uri=`"$Path`", algorithm=SHA-256, qop=auth, nc=$nc, cnonce=`"$cn`", response=`"$resp`", opaque=`"$($ch.opaque)`""
    $p = @{ Uri = "$Base$Path"; Method = $Method; Headers = @{ Authorization = $auth }; SkipHttpErrorCheck = $true; UseBasicParsing = $true }
    if ($Body) { $p.Body = $Body; $p.ContentType = 'application/xml' }
    Invoke-WebRequest @p
}

if (-not $User -or -not $Pass) { throw 'Nustatykite NVR_USER ir NVR_PASS aplinkos kintamuosius.' }

$failed = @()
foreach ($id in $Triggers) {
    $path = "/ISAPI/Event/triggers/$id"
    $get = Invoke-Isapi GET $path
    if ($get.StatusCode -ne 200) { $failed += "$id (GET $($get.StatusCode))"; continue }
    $xml = $get.Content.Substring($get.Content.IndexOf('<?xml'))
    $has = $xml -match '<notificationMethod>center</notificationMethod>'

    if ($Mode -eq 'status') { [pscustomobject]@{ Trigger = $id; Armed = $has }; continue }
    if (($Mode -eq 'arm') -eq $has) { continue }   # jau reikiamos būsenos

    $new = if ($Mode -eq 'arm') { $xml -replace '</EventTriggerNotificationList>', "$CenterXml</EventTriggerNotificationList>" }
           else { [regex]::Replace($xml, '<EventTriggerNotification>\s*<id>center</id>.*?</EventTriggerNotification>\s*', '', 'Singleline') }
    $put = Invoke-Isapi PUT $path $new
    if ($put.StatusCode -ne 200 -or $put.Content -notmatch '<statusString>OK') { $failed += "$id (PUT $($put.StatusCode))"; continue }

    # patikra po pakeitimo
    $again = (Invoke-Isapi GET $path).Content -match '<notificationMethod>center</notificationMethod>'
    if ($again -ne ($Mode -eq 'arm')) { $failed += "$id (patikra nepavyko)" }
}

if ($Mode -ne 'status') {
    if ($failed) { Write-Error "Nepavyko: $($failed -join ', ')"; exit 1 }
    Write-Output "OK: $Mode"
}
