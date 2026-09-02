"""Append structured pipeline run logs to ``pipeline_logs.json`` in the repo root."""

from __future__ import annotations

import json
import platform
import socket
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "pipeline_logs.json"


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_log(path: Path | None = None) -> dict[str, Any]:
    path = path or LOG_PATH
    if not path.exists():
        return {"version": 1, "description": "Pipeline run logs (profiles: smoke, wave, rescore, full)", "runs": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_log(data: dict[str, Any], path: Path | None = None) -> Path:
    path = path or LOG_PATH
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def start_run(wave: int, *, label: str = "rescore") -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "label": label,
        "wave": wave,
        "started_at": _now_iso(),
        "finished_at": None,
        "host": socket.gethostname(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "steps": [],
        "summary": {},
    }


def append_step(run: dict[str, Any], name: str, cmd: list[str], exit_code: int, *, extra: dict[str, Any] | None = None) -> None:
    step: dict[str, Any] = {
        "name": name,
        "command": cmd,
        "exit_code": exit_code,
        "status": "ok" if exit_code == 0 else f"exit_{exit_code}",
        "finished_at": _now_iso(),
    }
    if extra:
        step["extra"] = extra
    run["steps"].append(step)


def finish_run(run: dict[str, Any], *, summary: dict[str, Any] | None = None) -> dict[str, Any]:
    run["finished_at"] = _now_iso()
    if summary:
        run["summary"] = summary
    data = load_log()
    data.setdefault("runs", []).append(run)
    save_log(data)
    return run


def capture_json_stdout(cmd: list[str], cwd: Path | None = None) -> tuple[int, dict[str, Any] | None, str]:
    import subprocess

    result = subprocess.run(cmd, cwd=cwd or ROOT, capture_output=True, text=True)
    parsed: dict[str, Any] | None = None
    if result.stdout.strip():
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError:
            parsed = {"raw_stdout": result.stdout[-4000:]}
    if result.stderr.strip() and parsed is not None:
        parsed["stderr"] = result.stderr[-2000:]
    elif result.stderr.strip():
        parsed = {"stderr": result.stderr[-2000:]}
    return result.returncode, parsed, result.stdout + result.stderr
