param(
    [int]$Seconds = 90,
    [string]$NvrHost = '192.168.8.1',
    [string]$User = $env:NVR_USER,
    [string]$Pass = $env:NVR_PASS
)
# Klauso NVR įvykių srauto (alertStream) ir spausdina įvykius: laikas, tipas, kanalas, būsena.
# Įvykiai matomi nepriklausomai nuo arm/disarm (center linkage veikia tik push pranešimus).

$Base = "http://$NvrHost"; $Path = '/ISAPI/Event/notification/alertStream'
if (-not $User -or -not $Pass) { throw 'Nustatykite NVR_USER ir NVR_PASS aplinkos kintamuosius.' }

function Get-Sha256([string]$s) {
    -join ([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($s)) | ForEach-Object { $_.ToString('x2') })
}

$r = Invoke-WebRequest "$Base$Path" -SkipHttpErrorCheck -UseBasicParsing
$ch = @{}
[regex]::Matches(($r.Headers['WWW-Authenticate'] | Select-Object -First 1), '(\w+)="([^"]*)"') |
    ForEach-Object { $ch[$_.Groups[1].Value] = $_.Groups[2].Value }
$cn = [guid]::NewGuid().ToString('N')
$ha1 = Get-Sha256 "${User}:$($ch.realm):${Pass}"
$resp = Get-Sha256 "${ha1}:$($ch.nonce):00000001:${cn}:auth:$(Get-Sha256 "GET:$Path")"
$auth = "Digest username=`"$User`", realm=`"$($ch.realm)`", nonce=`"$($ch.nonce)`", uri=`"$Path`", algorithm=SHA-256, qop=auth, nc=00000001, cnonce=`"$cn`", response=`"$resp`", opaque=`"$($ch.opaque)`""

$http = [Net.Http.HttpClient]::new(); $http.Timeout = [TimeSpan]::FromSeconds($Seconds + 15)
$req = [Net.Http.HttpRequestMessage]::new('GET', "$Base$Path")
[void]$req.Headers.TryAddWithoutValidation('Authorization', $auth)
$res = $http.SendAsync($req, [Net.Http.HttpCompletionOption]::ResponseHeadersRead).Result
if (-not $res.IsSuccessStatusCode) { Write-Error "HTTP $([int]$res.StatusCode) - vartotojui trūksta teisių?"; exit 1 }
Write-Output "Klausau $Seconds s..."

$stream = $res.Content.ReadAsStreamAsync().Result
$buf = New-Object byte[] 8192; $text = ''; $bytes = 0; $end = (Get-Date).AddSeconds($Seconds)
while ((Get-Date) -lt $end) {
    if (-not $t) { $t = $stream.ReadAsync($buf, 0, $buf.Length) }   # neaukoti kol praeitas skaitymas nebaigtas
    if (-not $t.Wait(2000)) { continue }
    $n = $t.Result; $t = $null
    if ($n -le 0) { break }
    $bytes += $n
    $text += [Text.Encoding]::UTF8.GetString($buf, 0, $n)
    while ($text -match '(?s)<EventNotificationAlert.*?</EventNotificationAlert>') {
        $m = $Matches[0]; $text = $text.Substring($text.IndexOf($m) + $m.Length)
        $f = @{}
        foreach ($k in 'dateTime', 'eventType', 'eventState', 'channelID', 'dynChannelID') {
            if ($m -match "<$k>([^<]*)</$k>") { $f[$k] = $Matches[1] }
        }
        if ($f.eventType -in 'videoloss', 'heartBeat') { continue }
        '{0}  {1,-16} ch={2} {3}' -f $f.dateTime, $f.eventType, ($f.dynChannelID ?? $f.channelID), $f.eventState
    }
}
Write-Output "Gauta baitų: $bytes"
