[1mdiff --git a/run_api.py b/run_api.py[m
[1mindex 8ff0764..cc3a3fa 100644[m
[1m--- a/run_api.py[m
[1m+++ b/run_api.py[m
[36m@@ -1,6 +1,9 @@[m
 from __future__ import annotations[m
 [m
 import os[m
[32m+[m[32mimport re[m
[32m+[m[32mimport shutil[m
[32m+[m[32mimport subprocess[m
 [m
 import uvicorn[m
 [m
[36m@@ -15,6 +18,40 @@[m [mdef _required_env(name: str) -> str:[m
     return value.strip()[m
 [m
 [m
[32m+[m[32mdef _command_output(command: list[str]) -> str:[m
[32m+[m[32m    try:[m
[32m+[m[32m        completed = subprocess.run([m
[32m+[m[32m            command,[m
[32m+[m[32m            check=False,[m
[32m+[m[32m            capture_output=True,[m
[32m+[m[32m            text=True,[m
[32m+[m[32m            timeout=5,[m
[32m+[m[32m        )[m
[32m+[m[32m    except (OSError, subprocess.TimeoutExpired):[m
[32m+[m[32m        return ""[m
[32m+[m[32m    return "\n".join(part for part in (completed.stdout, completed.stderr) if part)[m
[32m+[m
[32m+[m
[32m+[m[32mdef _port_token_pattern(port: int) -> re.Pattern[str]:[m
[32m+[m[32m    return re.compile(rf"(?<![0-9]):{port}(?![0-9])")[m
[32m+[m
[32m+[m
[32m+[m[32mdef _is_api_port_listening(port: int) -> bool:[m
[32m+[m[32m    pattern = _port_token_pattern(port)[m
[32m+[m
[32m+[m[32m    if shutil.which("ss"):[m
[32m+[m[32m        output = _command_output(["ss", "-ltnp"])[m
[32m+[m[32m        if any("LISTEN" in line and pattern.search(line) for line in output.splitlines()):[m
[32m+[m[32m            return True[m
[32m+[m
[32m+[m[32m    if shutil.which("lsof"):[m
[32m+[m[32m        output = _command_output(["lsof", "-i", f":{port}"])[m
[32m+[m[32m        if any(("LISTEN" in line or "TCP" in line) and pattern.search(line) for line in output.splitlines()):[m
[32m+[m[32m            return True[m
[32m+[m
[32m+[m[32m    return False[m
[32m+[m
[32m+[m
 def main() -> None:[m
     """Launch the production dashboard.[m
 [m
[36m@@ -28,6 +65,13 @@[m [mdef main() -> None:[m
     setup_production_logging()[m
     host = _required_env("BOT_API_HOST")[m
     port = int(_required_env("BOT_API_PORT"))[m
[32m+[m[32m    if _is_api_port_listening(port):[m
[32m+[m[32m        print([m
[32m+[m[32m            f"BOT_API_PORT {port} is already listening; reusing existing server.",[m
[32m+[m[32m            flush=True,[m
[32m+[m[32m        )[m
[32m+[m[32m        return[m
[32m+[m
     uvicorn.run([m
         "app.dashboard.app:app",[m
         host=host,[m
