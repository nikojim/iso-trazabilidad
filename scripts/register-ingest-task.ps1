<#
.SYNOPSIS
    Registra en el Programador de tareas de Windows la ingesta incremental periódica de ISO Trace.

.DESCRIPTION
    Crea (o reemplaza) dos tareas del usuario actual:
      - "ISO Trace - ingesta incremental": `iso-trace ingest --incremental` sobre la raíz
        completa de documentos, cada -IntervalMinutes minutos.
      - "ISO Trace - reintento semanal": lo mismo con --retry-failed, los domingos a -RetryAt.
    Se ejecutan desde la carpeta del proyecto, así que leen su .env (ISO_DOCUMENTS_DIR,
    ISO_DATABASE_URL...). Si una corrida sigue en curso, la siguiente no se inicia.
    Corren sin ventana (conhost --headless) y solo con la sesión del usuario iniciada, que es
    lo que necesitan OneDrive y las unidades de red mapeadas.

.EXAMPLE
    .\scripts\register-ingest-task.ps1
.EXAMPLE
    .\scripts\register-ingest-task.ps1 -IntervalMinutes 60 -NoWeeklyRetry
.EXAMPLE
    .\scripts\register-ingest-task.ps1 -Unregister
#>
[CmdletBinding()]
param(
    [ValidateRange(5, 1440)]
    [int]$IntervalMinutes = 30,
    [string]$RetryAt = "03:15",
    [switch]$NoWeeklyRetry,
    [switch]$Unregister,
    [string]$ProjectDir = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"
$TaskPath = "\ISO Trace\"
$IngestTask = "ISO Trace - ingesta incremental"
$RetryTask = "ISO Trace - reintento semanal"

if ($Unregister) {
    foreach ($name in $IngestTask, $RetryTask) {
        if (Get-ScheduledTask -TaskPath $TaskPath -TaskName $name -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskPath $TaskPath -TaskName $name -Confirm:$false
            Write-Host "Eliminada: $name"
        }
    }
    return
}

if (-not (Test-Path (Join-Path $ProjectDir "pyproject.toml"))) {
    throw "$ProjectDir no es la carpeta del proyecto (falta pyproject.toml); indicarla con -ProjectDir"
}
$uv = (Get-Command uv -ErrorAction Stop).Source

function New-IngestAction([string]$Arguments) {
    # conhost --headless evita que se abra una consola en cada corrida.
    New-ScheduledTaskAction -Execute "conhost.exe" `
        -Argument "--headless `"$uv`" run iso-trace ingest $Arguments" `
        -WorkingDirectory $ProjectDir
}

$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

$every = New-ScheduledTaskTrigger -Once -At (Get-Date).Date `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
Register-ScheduledTask -TaskPath $TaskPath -TaskName $IngestTask -Force `
    -Action (New-IngestAction "--incremental") -Trigger $every `
    -Principal $principal -Settings $settings `
    -Description "Ingesta incremental de ISO Trace (solo archivos nuevos o modificados)" | Out-Null
Write-Host "Registrada: $IngestTask (cada $IntervalMinutes min, desde $ProjectDir)"

if ($NoWeeklyRetry) {
    if (Get-ScheduledTask -TaskPath $TaskPath -TaskName $RetryTask -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskPath $TaskPath -TaskName $RetryTask -Confirm:$false
    }
} else {
    $weekly = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At $RetryAt
    Register-ScheduledTask -TaskPath $TaskPath -TaskName $RetryTask -Force `
        -Action (New-IngestAction "--incremental --retry-failed") -Trigger $weekly `
        -Principal $principal -Settings $settings `
        -Description "Reintenta los documentos de ISO Trace que fallaron o quedaron a revisar" | Out-Null
    Write-Host "Registrada: $RetryTask (domingos $RetryAt)"
}

Write-Host "Resultado de cada corrida: uv run iso-trace runs list (o los logs en ISO_LOG_DIR)."
