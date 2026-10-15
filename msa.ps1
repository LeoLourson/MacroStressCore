# Scripts in ops/: local_stack.py (up/down/status/logs), rehearse.py (dress rehearsal),
#   init_env.py, check_services.py, load_portfolio.py, web_build.py.
# Linux/macOS equivalent: uv run --frozen python ops/local_stack.py up [deepseek|local|mock] | down | status | logs [name]
#   and uv run --frozen python ops/rehearse.py [EVENT ...]
# Native stack on Windows without Docker: PostgreSQL + the API with the browser app.
#   .\msa.ps1 up [deepseek|local|mock] | down | status | logs [name] | rehearse [RECYCLING-FEE MORTGAGE-DOWN-PAYMENT]
#   deepseek — DeepSeek API (DEEPSEEK_API_KEY), local — LM Studio on 127.0.0.1:1234, mock — no LLM
param(
    [Parameter(Position = 0)]
    [ValidateSet("up", "down", "status", "logs", "rehearse")]
    [string]$Command = "status",
    [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
    [string[]]$Rest = @()
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$env:PYTHONIOENCODING = "utf-8"
$script = if ($Command -eq "rehearse") { "ops/rehearse.py" } else { "ops/local_stack.py" }
# @() keeps a single argument an array: splatting a bare string passes its characters.
$arguments = @(if ($Command -eq "rehearse") { $Rest } else { @($Command) + $Rest })
uv run --frozen python $script @arguments
exit $LASTEXITCODE
