# Beat 2 - Morning briefing.
#
# Composes several M365 queries through the proxy into one formatted briefing --
# the kind of thing you'd actually run each morning. Demonstrates repeatable
# automation over enterprise data through a plain OpenAI-compatible API.
#
# Copilot decides per turn whether to ground; Ask-M365 retries on a refusal so a
# one-off "I can't access..." doesn't break the live demo.
#
#   -Safe   Counts + high-level only. No meeting titles, names, clients, or
#           project details. Use this for any audience that shouldn't see real
#           work content (external, recorded, large internal).

param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [int]$MaxAttempts = 3,
    [switch]$Safe
)

$refusal = 'can.?t access|cannot access|can.?t see|can.?t actually|no .{0,40}connector|not able to access|don.?t have (direct |the )?access|unavailable'

function Clean-Text([string]$s) {
    if (-not $s) { return "" }
    # Drop bare citation links like [1](https://...) entirely.
    $s = [regex]::Replace($s, '\[\d+\]\((https?://[^)]+)\)', '')
    # Turn [label](url) into just label.
    $s = [regex]::Replace($s, '\[([^\]]+)\]\((https?://[^)]+)\)', '$1')
    # Collapse leftover whitespace/blank lines.
    $s = [regex]::Replace($s, '[ \t]+', ' ')
    $s = [regex]::Replace($s, '(\r?\n){3,}', "`n`n")
    return $s.Trim()
}

function Ask-M365([string]$Question) {
    for ($i = 1; $i -le $MaxAttempts; $i++) {
        $body = @{
            model    = "m365-copilot"
            messages = @(@{ role = "user"; content = $Question })
        } | ConvertTo-Json -Depth 5
        try {
            $reply = (Invoke-RestMethod -Method Post -Uri "$BaseUrl/v1/chat/completions" `
                -ContentType "application/json" -Body $body -TimeoutSec 90).choices[0].message.content
        } catch {
            $reply = "(request failed: $($_.Exception.Message))"
        }
        if ($reply -notmatch $refusal) { return (Clean-Text $reply) }
    }
    return (Clean-Text $reply)  # last attempt, even if still a refusal
}

$today = (Get-Date).ToString("dddd, MMMM d")

Write-Host ""
Write-Host "=======================================================" -ForegroundColor DarkGray
Write-Host "  DAILY BRIEFING - $today" -ForegroundColor White
Write-Host "  (grounded in Microsoft 365 via the local Copilot proxy)" -ForegroundColor DarkGray
if ($Safe) { Write-Host "  [safe mode: counts and high-level only]" -ForegroundColor DarkGray }
Write-Host "=======================================================" -ForegroundColor DarkGray
Write-Host ""

Write-Host "CALENDAR" -ForegroundColor Yellow
if ($Safe) {
    $calendar = Ask-M365 "How many meetings do I have on my calendar today? Reply with a single short sentence like 'You have N meetings today.' Do not list titles or names."
} else {
    $calendar = Ask-M365 "Summarize my calendar for today. List each meeting as a short bullet with its title. Do not include long URLs. If I have no meetings, say 'No meetings today.'"
}
Write-Host $calendar
Write-Host ""

Write-Host "INBOX" -ForegroundColor Yellow
$unread = Ask-M365 "How many unread emails do I have in my inbox right now? Reply with just the number."
Write-Host "  Unread emails: $unread"
Write-Host ""

if (-not $Safe) {
    Write-Host "FOCUS FOR TODAY" -ForegroundColor Yellow
    $focus = Ask-M365 "Based on my calendar and recent email, what are the 2-3 most important things I should focus on today? Reply as a short bulleted list, one line each."
    Write-Host $focus
    Write-Host ""
}

Write-Host "=======================================================" -ForegroundColor DarkGray
Write-Host "  Generated through an OpenAI-compatible API call." -ForegroundColor DarkGray
Write-Host "  No Azure app registration. No Graph SDK." -ForegroundColor DarkGray
Write-Host "=======================================================" -ForegroundColor DarkGray
Write-Host ""
