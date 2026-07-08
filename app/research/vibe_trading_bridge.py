from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class ResearchResult:
    command: list[str]
    return_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.return_code == 0


class VibeTradingBridge:
    """Optional bridge for Vibe-Trading research runs.

    This bridge is intentionally separate from signal execution. It may help
    with research and backtest prompts, but the live trading path still reads
    deterministic JSON signals from this project.
    """

    def __init__(self, executable: str = "vibe-trading", timeout_seconds: int = 600) -> None:
        self.executable = executable
        self.timeout_seconds = timeout_seconds

    def is_available(self) -> bool:
        return shutil.which(self.executable) is not None

    def run_research(self, prompt: str) -> ResearchResult:
        if not prompt.strip():
            raise ValueError("prompt cannot be empty")
        if not self.is_available():
            raise RuntimeError(
                "vibe-trading CLI is not installed. Install optional research dependencies first."
            )

        command = [self.executable, "run", "-p", prompt]
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            encoding="utf-8",
            timeout=self.timeout_seconds,
        )
        return ResearchResult(
            command=command,
            return_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
