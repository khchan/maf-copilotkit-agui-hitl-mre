from __future__ import annotations

import argparse
import json
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from agent_framework import Content, Message
from hitl_mre.app import create_workflow


DEFAULT_URL = "http://127.0.0.1:8098/agui"
RESUMED_PREFIX = "Workflow resumed with human response:"


@dataclass(frozen=True)
class RunResult:
    events: list[dict[str, Any]]
    raw_text: str

    @property
    def event_types(self) -> list[str]:
        return [str(event.get("type")) for event in self.events]

    @property
    def custom_names(self) -> list[str]:
        return [str(event.get("name")) for event in self.events if event.get("type") == "CUSTOM"]

    @property
    def latest_snapshot_messages(self) -> list[dict[str, Any]]:
        for event in reversed(self.events):
            if event.get("type") == "MESSAGES_SNAPSHOT":
                messages = event.get("messages")
                if isinstance(messages, list):
                    return messages
        return []

    @property
    def text(self) -> str:
        return "\n".join(json.dumps(event, sort_keys=True) for event in self.events)


def _parse_sse(text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line.removeprefix("data:").strip()
        if not payload:
            continue
        events.append(json.loads(payload))
    return events


def _post_run(url: str, body: dict[str, Any]) -> RunResult:
    chunks: list[str] = []
    with httpx.Client(timeout=30.0) as client:
        try:
            with client.stream(
                "POST",
                url,
                json=body,
                headers={"accept": "text/event-stream"},
            ) as response:
                response.raise_for_status()
                for chunk in response.iter_text():
                    chunks.append(chunk)
        except httpx.RemoteProtocolError as exc:
            raw_text = "".join(chunks)
            events = _parse_sse(raw_text)
            events.append({"type": "STREAM_CLOSED", "error": str(exc)})
            return RunResult(events=events, raw_text=raw_text)

    raw_text = "".join(chunks)
    return RunResult(events=_parse_sse(raw_text), raw_text=raw_text)


def _user_message(content: str) -> dict[str, Any]:
    return {"id": str(uuid.uuid4()), "role": "user", "content": content}


def _base_body(thread_id: str, run_id: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "threadId": thread_id,
        "runId": run_id,
        "messages": messages,
        "state": {},
        "tools": [],
        "context": [],
    }


def _find_request_info_call(snapshot_messages: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    for message in snapshot_messages:
        for tool_call in message.get("toolCalls") or message.get("tool_calls") or []:
            function = tool_call.get("function") or {}
            if function.get("name") == "request_info":
                return str(tool_call["id"]), tool_call
    raise AssertionError("No request_info tool call found in MAF AG-UI snapshot")


def _has_resumed_text(result: RunResult) -> bool:
    return RESUMED_PREFIX in result.text


def _sibling_endpoint(url: str, path: str) -> str:
    trimmed = url.rstrip("/")
    if trimmed.endswith("/agui"):
        return f"{trimmed.removesuffix('/agui')}{path}"
    return trimmed


async def _verify_direct_workflow_control() -> str:
    workflow = create_workflow()
    request_id: str | None = None
    input_message = Message(
        role="user",
        contents=[Content.from_text(text="direct MAF workflow control")],
    )
    async for event in workflow.run([input_message], stream=True):
        if event.type == "request_info":
            request_id = event.request_id

    if request_id is None:
        raise AssertionError("Direct MAF Workflow did not emit request_info")

    outputs: list[str] = []
    async for event in workflow.run(
        responses={request_id: "approved via direct MAF workflow control"},
        stream=True,
    ):
        if event.type == "output":
            for message in event.data.messages:
                for content in message.contents:
                    if content.type == "text":
                        outputs.append(str(content.text))

    return "\n".join(outputs)


def run_probe(url: str) -> int:
    control_url = _sibling_endpoint(url, "/agui-control")
    mismatch_url = _sibling_endpoint(url, "/agui-mismatch")

    def start_paused_run(
        run_url: str,
        label: str,
    ) -> tuple[str, RunResult, list[dict[str, Any]], str, dict[str, Any]]:
        thread_id = f"thread-{uuid.uuid4()}"
        body = _base_body(
            thread_id=thread_id,
            run_id=f"run-{uuid.uuid4()}",
            messages=[_user_message(f"{label}: start deterministic MAF workflow")],
        )
        result = _post_run(run_url, body)
        snapshot_messages = result.latest_snapshot_messages
        request_call_id, request_call = _find_request_info_call(snapshot_messages)
        return thread_id, result, snapshot_messages, request_call_id, request_call

    import asyncio

    direct_control_text = asyncio.run(_verify_direct_workflow_control())

    mismatch_thread_id, first, mismatch_snapshot, mismatch_call_id, mismatch_call = start_paused_run(
        mismatch_url,
        "copilotkit-resume-mismatch",
    )

    assertions: list[tuple[str, bool]] = [
        (
            "Control: direct MAF Workflow request_info resumes without AG-UI",
            RESUMED_PREFIX in direct_control_text,
        ),
        (
            "MAF AG-UI emits a request_info tool call",
            "request_info" in first.raw_text,
        ),
        (
            "MAF AG-UI does not emit CopilotKit useInterrupt CUSTOM on_interrupt",
            "on_interrupt" not in first.custom_names,
        ),
        (
            "MAF AG-UI emits no CopilotKit interrupt custom event",
            len(first.custom_names) == 0,
        ),
        (
            "First run stops without final resumed workflow text",
            not _has_resumed_text(first),
        ),
    ]

    copilotkit_resume_body = _base_body(
        thread_id=mismatch_thread_id,
        run_id=f"run-{uuid.uuid4()}",
        messages=mismatch_snapshot,
    )
    copilotkit_resume_body["forwardedProps"] = {
        "command": {
            "resume": "approved via CopilotKit useInterrupt shape",
            "interruptEvent": {
                "requestId": mismatch_call_id,
                "toolCall": mismatch_call,
            },
        },
    }
    copilotkit_resume = _post_run(mismatch_url, copilotkit_resume_body)
    assertions.extend(
        [
            (
                "CopilotKit-shaped forwardedProps.command.resume does not resume the MAF workflow",
                not _has_resumed_text(copilotkit_resume),
            ),
            (
                "CopilotKit-shaped resume yields RUN_ERROR/STREAM_CLOSED or another non-resumed run",
                "RUN_ERROR" in copilotkit_resume.event_types
                or "STREAM_CLOSED" in copilotkit_resume.event_types
                or not _has_resumed_text(copilotkit_resume),
            ),
        ]
    )

    agui_control_thread_id, agui_control_first, _snapshot, agui_control_call_id, _call = start_paused_run(
        control_url,
        "maf-agui-function-approval",
    )
    maf_agui_resume_body = _base_body(
        thread_id=agui_control_thread_id,
        run_id=f"run-{uuid.uuid4()}",
        messages=[
            {
                "id": str(uuid.uuid4()),
                "role": "user",
                "function_approvals": [
                    {
                        "id": agui_control_call_id,
                        "call_id": agui_control_call_id,
                        "name": "request_info",
                        "approved": True,
                        "arguments": {
                            "request_id": agui_control_call_id,
                            "data": "approved via MAF AG-UI function_approvals shape",
                        },
                    }
                ],
            },
        ],
    )
    maf_agui_resume = _post_run(control_url, maf_agui_resume_body)
    assertions.append(
        (
            "Additional: MAF-specific AG-UI function_approvals response finishes without resumed output",
            not _has_resumed_text(maf_agui_resume)
            and "RUN_FINISHED" in maf_agui_resume.event_types,
        )
    )

    print("\nDirect MAF Workflow control text:", direct_control_text)
    print("\nFirst run custom events:", first.custom_names)
    print("First run event types:", first.event_types)
    print("request_info toolCallId:", mismatch_call_id)
    print("\nCopilotKit-shaped resume event types:", copilotkit_resume.event_types)
    if "RUN_ERROR" in copilotkit_resume.event_types:
        print("CopilotKit-shaped resume produced RUN_ERROR, as expected for this mismatch.")
    print("\nMAF AG-UI function_approvals first custom events:", agui_control_first.custom_names)
    print("MAF AG-UI function_approvals resume event types:", maf_agui_resume.event_types)

    failed = False
    print("\nAssertions:")
    for description, passed in assertions:
        status = "PASS" if passed else "FAIL"
        print(f"  {status} {description}")
        failed = failed or not passed

    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    args = parser.parse_args()
    raise SystemExit(run_probe(args.url))


if __name__ == "__main__":
    main()
