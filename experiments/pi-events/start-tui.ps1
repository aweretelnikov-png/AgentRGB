param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('A','B','D','D-idle','E','F','G')]
    [string]$Scenario
)
$ErrorActionPreference = 'Stop'
$previousResults = $env:AGENTRGB_PI_RESULTS
$resultDirectory = Join-Path $PSScriptRoot ('results/' + $Scenario + '-tui-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
$piArgs = @('--no-session', '--no-extensions', '--no-skills', '--no-prompt-templates', '--no-themes', '--no-context-files',
    '--system-prompt', 'Harmless AgentRGB lifecycle experiment. Follow the test request literally. Do not access other files.',
    '-e', (Join-Path $PSScriptRoot 'pi-event-recorder.ts'))
switch ($Scenario) {
    'A' { $piArgs += '--no-tools' }
    'D' {
        $questionExtension = Join-Path $env:USERPROFILE '.pi/agent/npm/node_modules/@juicesharp/rpiv-ask-user-question/index.ts'
        if (!(Test-Path -LiteralPath $questionExtension)) { throw 'Installed ask_user_question extension not found.' }
        $piArgs += @('-e', $questionExtension, '--tools', 'ask_user_question')
    }
    'D-idle' { $piArgs += @('-e', (Join-Path $PSScriptRoot 'pi-wait-probe.ts'), '--no-tools') }
    'E' { $piArgs += @('--tools', 'bash') }
    'G' { $piArgs += @('--tools', 'bash') }
    default { $piArgs += @('--tools', 'read') }
}
New-Item -ItemType Directory -Path $resultDirectory | Out-Null
Push-Location $PSScriptRoot
try {
    $env:AGENTRGB_PI_RESULTS = $resultDirectory
    & pi @piArgs
} finally {
    $env:AGENTRGB_PI_RESULTS = $previousResults
    Pop-Location
}
