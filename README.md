# MAF AG-UI workflow HITL + CopilotKit hooks MRE

This is a minimal reproducible case for a contract mismatch between Microsoft
Agent Framework workflow human-in-the-loop events and CopilotKit AG-UI hooks.

The backend is deterministic and uses no LLM credentials. Any user message runs
a MAF workflow executor that immediately calls:

```python
await ctx.request_info("Approve or edit this deterministic workflow input", str)
```

MAF core supports this workflow pause/resume path. The issue is in the AG-UI
surface exposed to CopilotKit.

## Versions captured in this repro

- `agent-framework-core==1.0.0b260212`
- `agent-framework-ag-ui==1.0.0b260212`
- `@copilotkit/react-core==1.57.1`
- `@copilotkit/runtime==1.57.1`
- `@ag-ui/client==0.0.53`

The Python dependencies are pinned in `pyproject.toml` and `uv.lock`.

## Run the backend

```bash
cd maf-copilotkit-agui-hitl-mre
uv run uvicorn hitl_mre.app:create_app --factory --host 127.0.0.1 --port 8098
```

## Run the automated AG-UI contract probe

In a second shell:

```bash
cd maf-copilotkit-agui-hitl-mre
uv run python scripts/probe_agui_contract.py
```

Expected result:

- The first MAF AG-UI run emits `CUSTOM function_approval_request`.
- It does not emit `CUSTOM on_interrupt`, which is what CopilotKit
  `useInterrupt` listens for.
- A CopilotKit-shaped resume payload in
  `forwardedProps.command.resume` does not resume the workflow.
- The same workflow resumes when exercised directly through `WorkflowAgent`,
  proving the workflow itself is valid.
- A MAF-specific `function_approvals` response through AG-UI also fails in this
  repro with a stream close/server-side `Workflow is already running` error,
  which points at the MAF AG-UI workflow bridge rather than CopilotKit alone.

The probe uses separate backend endpoints, `/agui-control` and
`/agui-mismatch`, so each AG-UI path has an isolated in-memory `WorkflowAgent`.

## Run the CopilotKit frontend

```bash
cd maf-copilotkit-agui-hitl-mre/frontend
npm install
npm run dev
```

Open `http://localhost:3000` and send any chat message.

Expected frontend behavior:

- The `useInterrupt` diagnostic stays in the waiting state because the MAF
  adapter emits `function_approval_request`, not `on_interrupt`.
- The normal app-level `useHumanInTheLoop` tool named `human_review` is not
  invoked, because the MAF workflow emits internal `request_info` /
  `confirm_changes` tool calls instead of the app-level tool name.

## Why this is not an LLM/tool-selection problem

The workflow executor directly calls `ctx.request_info`. There is no prompt,
model, or probabilistic tool selection in this repro.

## Bug summary

MAF workflow HITL works in MAF core. CopilotKit `useInterrupt` expects this
AG-UI contract:

- receive `CUSTOM on_interrupt`
- resume with `forwardedProps.command.resume`

The MAF AG-UI adapter currently emits:

- `CUSTOM function_approval_request`
- synthetic `confirm_changes` tool call
- resume via message-level function approval/tool result conventions

Those two contracts are not bridged. In this deterministic workflow repro, even
a MAF-specific AG-UI `function_approvals` response does not complete the
workflow because the underlying workflow is still considered running.
