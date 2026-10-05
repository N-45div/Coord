# Creates the four factory seats as headless Claude Code agents in Band Desktop.
# Approval stays at Band's default for Claude Code (Auto, Claude's safety checks on).
# Context mode "local_config" is required for a Claude subscription ("bare" never reads OAuth).
# The user's global CLAUDE.md is kept out by claudeMdExcludes in band-work/.claude/settings.local.json.
# Run with -DryRun first: it probes each runtime without creating anything.
param([switch]$DryRun, [string]$ContextMode = "local_config")

$band = "$env:LOCALAPPDATA\Band\band.exe"
$cwd = "C:/Users/DivijN/dark-factory/band-work"
$mandates = "C:/Users/DivijN/dark-factory/factory/mandates"
$seats = [ordered]@{
  Coordinator = "Plans, routes and tracks the band's work and keeps the requirements ledger. Never writes product code and never accepts work."
  Builder     = "Implements the product from the requirements, packages it and repairs rejected work. Never accepts its own work."
  Verifier    = "Writes an independent black-box test suite from the requirements and runs it against exact commits. Never reads product source."
  Gate        = "The only seat that accepts work. Reproduces every check on an exact commit, audits requirement coverage and code, and rejects with reproducers."
}

foreach ($name in $seats.Keys) {
  # The default session is a hash of the working directory; the seats share one, so each gets its own.
  $cmd = @("agent", "create", "--session", "factory-$($name.ToLower())",
           "--name", $name, "--description", $seats[$name],
           "--cwd", $cwd, "--transport", "claude-code-cli",
           "--runtime-model", "claude-opus-5-5", "--runtime-auth", "subscription",
           "--claude-context-mode", $ContextMode, "--json")
  # Band refuses --instructions-file together with --dry-run.
  if ($DryRun) { $cmd += "--dry-run" }
  else { $cmd += @("--instructions-file", "$mandates/$($name.ToLower()).md") }
  Write-Host "=== $name"
  & $band @cmd
}
