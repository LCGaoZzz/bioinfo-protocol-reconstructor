#!/usr/bin/env python3
"""Isolated Omicos discovery, refresh, and model-facing Skill-load smoke."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


AGENT_ID = "dev_reconstruct_bioinfo_protocol"
SKILL_ID = "dev-reconstruct-bioinfo-protocol"


def _port_is_open(host: str, port: int) -> bool:
    with socket.socket() as client:
        client.settimeout(0.2)
        return client.connect_ex((host, port)) == 0


def _json_request(url: str, *, payload: dict[str, Any] | None = None) -> Any:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST" if payload is not None else "GET",
        headers={"Content-Type": "application/json"} if payload is not None else {},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _chat_request(url: str, payload: dict[str, Any]) -> tuple[int, str]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-agent-session-id": "reconstruct_smoke_session",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.status, response.read().decode("utf-8", errors="replace")


def _items(value: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(value, dict) and isinstance(value.get(key), list):
        return [item for item in value[key] if isinstance(item, dict)]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _terminate(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _tail(path: Path, limit: int = 4000) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[-limit:]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--core", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--core-port", type=int, default=15055)
    parser.add_argument("--probe-port", type=int, default=18080)
    parser.add_argument(
        "--mode",
        choices=("override-e2e", "workspace-gate"),
        default="override-e2e",
        help="workspace-gate tests only the documented workspace-extension flag",
    )
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    core = args.core.resolve()
    if not workspace.is_dir() or not core.is_file():
        parser.error("workspace directory and core executable must exist")
    for port in (args.core_port, args.probe_port):
        if _port_is_open(args.host, port):
            parser.error(f"refusing to use occupied port {port}")

    probe_script = Path(__file__).with_name("fake_openai_skill_probe.py")
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    core_process: subprocess.Popen[bytes] | None = None
    probe_process: subprocess.Popen[bytes] | None = None

    with tempfile.TemporaryDirectory(prefix="omicos-reconstruct-smoke-") as temp_value:
        temp = Path(temp_value)
        data_dir = temp / "data"
        data_dir.mkdir()
        capture = temp / "capture.json"
        core_stdout = temp / "core.stdout.log"
        core_stderr = temp / "core.stderr.log"
        probe_stdout = temp / "probe.stdout.log"
        probe_stderr = temp / "probe.stderr.log"
        environment = os.environ.copy()
        environment.update(
            {
                "OMICOS_ENABLE_WORKSPACE_EXTENSIONS": "1",
                "OMICOS_LOCAL_HOME": str(data_dir),
                "OMICOS_RUNTIME_HOME": str(data_dir),
                "OMICOS_AGENTS_CACHE_DIR": str(temp / "agent-cache"),
                "OMICOS_SKILLS_CACHE_DIR": str(temp / "skill-cache"),
                "OMICOS_AGENTS_OFFLINE": "1",
                "OMICOS_SKILLS_OFFLINE": "1",
                "OMICOS_LLM_PROVIDER": "custom_openai",
                "OMICOS_LLM_MODEL": "probe-model",
                "CUSTOM_OPENAI_API_BASE": f"http://{args.host}:{args.probe_port}/v1",
                "CUSTOM_OPENAI_API_KEY": "sk-local-probe-placeholder",
            }
        )
        if args.mode == "override-e2e":
            environment.update(
                {
                    "OMICOS_TEMPLATES_DIR": str(workspace),
                    "OMICOS_SKILL_ROOTS": "skills",
                }
            )
        else:
            environment.pop("OMICOS_TEMPLATES_DIR", None)
            environment.pop("OMICOS_SKILL_ROOTS", None)
        try:
            with (
                probe_stdout.open("wb") as probe_out,
                probe_stderr.open("wb") as probe_err,
                core_stdout.open("wb") as core_out,
                core_stderr.open("wb") as core_err,
            ):
                probe_process = subprocess.Popen(
                    [
                        sys.executable,
                        "-B",
                        str(probe_script),
                        "--host",
                        args.host,
                        "--port",
                        str(args.probe_port),
                        "--capture",
                        str(capture),
                    ],
                    cwd=workspace,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=probe_out,
                    stderr=probe_err,
                    creationflags=creationflags,
                )
                core_process = subprocess.Popen(
                    [
                        str(core),
                        "serve",
                        "--host",
                        args.host,
                        "--port",
                        str(args.core_port),
                        "--data-dir",
                        str(data_dir),
                        "--no-browser",
                    ],
                    cwd=workspace,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=core_out,
                    stderr=core_err,
                    creationflags=creationflags,
                )

                base = f"http://{args.host}:{args.core_port}"
                deadline = time.monotonic() + 35
                agents_before: Any = None
                while time.monotonic() < deadline:
                    if core_process.poll() is not None:
                        raise RuntimeError(f"core exited {core_process.returncode}")
                    try:
                        agents_before = _json_request(f"{base}/api/agents")
                        break
                    except (OSError, urllib.error.URLError, json.JSONDecodeError):
                        time.sleep(0.5)
                if agents_before is None:
                    raise RuntimeError("isolated core did not become ready")

                skills_before = _json_request(f"{base}/api/skills")
                agents = _items(agents_before, "agents")
                skills = _items(skills_before, "skills")
                agent = next((item for item in agents if item.get("id") == AGENT_ID), None)
                skill = next((item for item in skills if item.get("id") == SKILL_ID), None)
                if args.mode == "workspace-gate":
                    refresh_agents = _json_request(f"{base}/api/agents/refresh", payload={})
                    refresh_skills = _json_request(f"{base}/api/skills/refresh", payload={})
                    agents_after = _items(_json_request(f"{base}/api/agents"), "agents")
                    skills_after = _items(_json_request(f"{base}/api/skills"), "skills")
                    result = {
                        "core_version": subprocess.check_output(
                            [str(core), "--version"],
                            text=True,
                            creationflags=creationflags,
                        ).strip(),
                        "mode": args.mode,
                        "agent_before": agent is not None,
                        "skill_before": skill is not None,
                        "agent_refresh_skipped": refresh_agents.get("skipped")
                        if isinstance(refresh_agents, dict)
                        else None,
                        "skill_refresh_skipped": refresh_skills.get("skipped")
                        if isinstance(refresh_skills, dict)
                        else None,
                        "agent_after": any(
                            item.get("id") == AGENT_ID for item in agents_after
                        ),
                        "skill_after": any(
                            item.get("id") == SKILL_ID for item in skills_after
                        ),
                        "agent_count_before": len(agents),
                        "skill_count_before": len(skills),
                        "agent_count_after": len(agents_after),
                        "skill_count_after": len(skills_after),
                    }
                    print(
                        json.dumps(result, ensure_ascii=False, indent=2)
                    )
                    return 0 if all(
                        result[key]
                        for key in (
                            "agent_before",
                            "skill_before",
                            "agent_after",
                            "skill_after",
                        )
                    ) else 1
                tools_value = _json_request(f"{base}/api/agents/{AGENT_ID}/tools")
                tools = _items(tools_value, "tools")
                tool_names = [str(item.get("name", "")) for item in tools]

                refresh_agents = _json_request(f"{base}/api/agents/refresh", payload={})
                refresh_skills = _json_request(f"{base}/api/skills/refresh", payload={})
                agents_after = _items(_json_request(f"{base}/api/agents"), "agents")
                skills_after = _items(_json_request(f"{base}/api/skills"), "skills")

                status, chat = _chat_request(
                    f"{base}/api/agent/chat/stream",
                    {
                        "message": (
                            "Load the declared reconstruction skill, then read its evidence contract "
                            "resource. Return only the probe marker when done."
                        ),
                        "config": {
                            "provider": "custom_openai",
                            "model": "probe-model",
                            "workspace": str(workspace),
                            "agent": AGENT_ID,
                            "permission_mode": "read_only",
                            "user_plan_code": "community",
                            "max_tool_iterations": 8,
                        },
                    },
                )
                captures = json.loads(capture.read_text(encoding="utf-8"))
                result = {
                    "core_version": subprocess.check_output(
                        [str(core), "--version"], text=True, creationflags=creationflags
                    ).strip(),
                    "agent_before": agent is not None,
                    "skill_before": skill is not None,
                    "declared_toolsets": agent.get("toolsets", []) if agent else [],
                    "skill_tool_present": "skill" in tool_names,
                    "skill_resource_tool_present": "skill_resource" in tool_names,
                    "agent_refresh_skipped": refresh_agents.get("skipped")
                    if isinstance(refresh_agents, dict)
                    else None,
                    "skill_refresh_skipped": refresh_skills.get("skipped")
                    if isinstance(refresh_skills, dict)
                    else None,
                    "agent_after": any(item.get("id") == AGENT_ID for item in agents_after),
                    "skill_after": any(item.get("id") == SKILL_ID for item in skills_after),
                    "chat_http_status": status,
                    "chat_marker": "MODEL_LOAD_PROBE_OK" in chat,
                    "chat_error": '"type":"error"' in chat.replace(" ", ""),
                    "probe_request_count": len(captures),
                    "request1_agent_body_observed": captures[0][
                        "agent_body_observed"
                    ],
                    "request1_has_skill_tool": "skill" in captures[0]["tool_names"],
                    "request1_has_resource_tool": "skill_resource" in captures[0]["tool_names"],
                    "request2_skill_body_observed": captures[1]["skill_body_observed"],
                    "request3_evidence_resource_observed": captures[2][
                        "evidence_resource_observed"
                    ],
                }
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0 if all(
                    result[key]
                    for key in (
                        "agent_before",
                        "skill_before",
                        "skill_tool_present",
                        "skill_resource_tool_present",
                        "agent_after",
                        "skill_after",
                        "chat_marker",
                        "request1_agent_body_observed",
                        "request1_has_skill_tool",
                        "request1_has_resource_tool",
                        "request2_skill_body_observed",
                        "request3_evidence_resource_observed",
                    )
                ) and not result["chat_error"] else 1
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "error": str(exc),
                        "core_stdout_tail": _tail(core_stdout),
                        "core_stderr_tail": _tail(core_stderr),
                        "probe_stdout_tail": _tail(probe_stdout),
                        "probe_stderr_tail": _tail(probe_stderr),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                file=sys.stderr,
            )
            return 2
        finally:
            _terminate(core_process)
            _terminate(probe_process)
            # Windows can retain redirected-log handles briefly after process
            # exit; let them drain before TemporaryDirectory removes the tree.
            time.sleep(1.0)


if __name__ == "__main__":
    raise SystemExit(main())
