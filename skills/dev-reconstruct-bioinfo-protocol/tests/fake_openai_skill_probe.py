#!/usr/bin/env python3
"""Deterministic OpenAI-compatible server for the local Skill loading smoke.

Request 1 also confirms that Omicos injected the selected Agent body, then asks
Omicos to call ``skill``. Request 2 asks it to read one packaged reference
through ``skill_resource``. Request 3 returns a final marker. The capture file
records only bounded booleans and tool names, not full prompts.
"""

from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


class ProbeState:
    def __init__(self, capture_path: Path) -> None:
        self.capture_path = capture_path
        self.lock = threading.Lock()
        self.request_count = 0
        self.captures: list[dict[str, Any]] = []

    def capture(self, body: dict[str, Any]) -> int:
        with self.lock:
            self.request_count += 1
            index = self.request_count
            serialized_messages = json.dumps(body.get("messages", []), ensure_ascii=False)
            tool_names = [
                item.get("function", {}).get("name")
                for item in body.get("tools", [])
                if isinstance(item, dict)
            ]
            self.captures.append(
                {
                    "request_index": index,
                    "tool_names": tool_names,
                    "agent_body_observed": (
                        "# Role and objective" in serialized_messages
                        and "traceable chain from the paper's" in serialized_messages
                        and "# Completion conditions" in serialized_messages
                    ),
                    "skill_body_observed": (
                        "BEGIN SKILL" in serialized_messages
                        and "dev-reconstruct-bioinfo-protocol" in serialized_messages
                        and "Required project artifacts" in serialized_messages
                    ),
                    "evidence_resource_observed": (
                        "Evidence and traceability contract" in serialized_messages
                        and "Deterministic status derivation" in serialized_messages
                    ),
                }
            )
            self.capture_path.write_text(
                json.dumps(self.captures, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            return index


def _tool_call(call_id: str, name: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": call_id,
                                "type": "function",
                                "function": {
                                    "name": name,
                                    "arguments": json.dumps(arguments, ensure_ascii=False),
                                },
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        },
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
    ]


class ProbeHandler(BaseHTTPRequestHandler):
    server_version = "OmicosSkillProbe/1.0"

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        size = int(self.headers.get("Content-Length", "0"))
        try:
            body = json.loads(self.rfile.read(size).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_error(400)
            return

        state: ProbeState = self.server.state  # type: ignore[attr-defined]
        request_index = state.capture(body)
        if request_index == 1:
            events = _tool_call(
                "probe_skill",
                "skill",
                {"name": "dev-reconstruct-bioinfo-protocol", "args": "model-facing load smoke"},
            )
        elif request_index == 2:
            events = _tool_call(
                "probe_resource",
                "skill_resource",
                {
                    "name": "dev-reconstruct-bioinfo-protocol",
                    "path": "references/evidence-contract.md",
                    "max_bytes": 65536,
                },
            )
        else:
            events = [
                {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": "MODEL_LOAD_PROBE_OK"},
                            "finish_reason": None,
                        }
                    ]
                },
                {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
            ]

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        for event in events:
            self.wfile.write(f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8"))
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def log_message(self, _format: str, *_args: Any) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--capture", type=Path, required=True)
    args = parser.parse_args()
    args.capture.parent.mkdir(parents=True, exist_ok=True)
    state = ProbeState(args.capture)
    server = ThreadingHTTPServer((args.host, args.port), ProbeHandler)
    server.state = state  # type: ignore[attr-defined]
    print(f"PROBE_LISTENING=http://{args.host}:{args.port}/v1", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
