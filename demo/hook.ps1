# Beat 1 - "It's just an OpenAI call, but it knows your calendar."
#
# This is the exact same request shape as api.openai.com's chat completions.
# Any tool that speaks OpenAI can now read M365 data. No Azure app registration,
# no admin consent, no Graph SDK -- just an HTTP call to the local proxy.

param([string]$BaseUrl = "http://127.0.0.1:8000")

function Clean-Text([string]$s) {
    if (-not $s) { return "" }
    $s = [regex]::Replace($s, '\[\d+\]\((https?://[^)]+)\)', '')
    $s = [regex]::Replace($s, '\[([^\]]+)\]\((https?://[^)]+)\)', '$1')
    $s = [regex]::Replace($s, '[ \t]+', ' ')
    return $s.Trim()
}

$body = @{
    model    = "m365-copilot"
    messages = @(@{ role = "user"; content = "What does my day look like? Answer in one or two sentences." })
} | ConvertTo-Json -Depth 5

Write-Host "POST $BaseUrl/v1/chat/completions  (standard OpenAI shape)" -ForegroundColor DarkGray
Write-Host ""

$reply = (Invoke-RestMethod -Method Post -Uri "$BaseUrl/v1/chat/completions" `
    -ContentType "application/json" -Body $body -TimeoutSec 90).choices[0].message.content

Write-Host (Clean-Text $reply) -ForegroundColor Cyan
