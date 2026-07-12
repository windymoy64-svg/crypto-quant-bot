# Cline Rules for Crypto Quant Bot

## Production Context

Project path:

```bash
/opt/crypto-quant-bot
```

## Python Environment

Always use the project's virtual environment.

Never use:

```bash
python
pip
```

Always use:

```bash
./.venv/bin/python
./.venv/bin/pip
```

Before running any Python command, verify:

```bash
which python
```

It must point to:

```bash
/opt/crypto-quant-bot/.venv/bin/python
```

## Testing

Never run:

```bash
python -m pytest
```

Always run:

```bash
./.venv/bin/python -m pytest
```

Never pipe pytest output to:

```bash
| tail
```

Run the full command and wait until it exits.

## Shell Commands

Never assume the virtual environment is active.

Always invoke the interpreter explicitly from:

```bash
./.venv/bin/python
```