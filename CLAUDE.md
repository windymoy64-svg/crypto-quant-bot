# Quant Trading Platform Rules

## General

- Never reread the entire repository.
- Read only files needed for current task.
- Do not refactor completed modules unless necessary.
- Keep backward compatibility.
- Never break existing tests.

## Environment

OS: Windows 10
Python: 3.13

Never use:

- rg
- fd
- jq
- sed
- awk

Use only:

- python
- PowerShell
- Get-ChildItem
- Select-String

## Verification

Always run:

python -m compileall app tests

python -m pytest

before finishing.

## Sprint

Implement exactly one sprint.

Never continue automatically to next sprint.

Stop after verification.

Output:

- Files changed
- Summary
- Tests