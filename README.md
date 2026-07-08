# MAF AG-UI workflow HITL + CopilotKit hooks MRE

This is a minimal reproducible case for a contract mismatch between Microsoft
Agent Framework workflow human-in-the-loop (HITL) events and CopilotKit AG-UI
hooks.

The backend is deterministic and uses no LLM credentials. Any user message runs
a MAF workflow executor that immediately calls:

```python
await ctx.request_info("Approve or edit this deterministic workflow input", str)
```

MAF core supports this workflow pause/resume path. The issue is in the AG-UI
surface exposed to CopilotKit.

This MRE implements the **workflow `request_info` path only**. It does not
exercise the agent **`confirm_changes`** approval path (see
[Other MAF HITL surfaces](#other-maf-hitl-surfaces-not-in-this-mre) below).

## Versions captured in this repro

- `agent-framework-core==1.10.0`
- `agent-framework-ag-ui==1.0.0rc7`
- `@copilotkit/react-core==1.61.2`
- `@copilotkit/runtime==1.61.2`
- `@ag-ui/client==0.0.57`

`agent-framework-ag-ui` is pinned to the newest PyPI pre-release because the
AG-UI adapter package does not currently have a newer stable release. FastAPI is
locked to the newest version allowed by that adapter's dependency constraint.

The Python dependencies are pinned in `pyproject.toml` and `uv.lock`.

## Environment

No secrets or API keys are required for the default local setup.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MAF_AGUI_URL` | No | `http://127.0.0.1:8098/agui` | MAF AG-UI backend URL for the CopilotKit runtime proxy |

**Not needed:** OpenAI, Azure, or MAF credentials. See [OpenAI calls](#openai-calls) below.

To override the backend URL, copy the example env file:

```bash
cp frontend/.env.example frontend/.env.local   # optional
```

Hardcoded defaults:

| Service | URL |
|---------|-----|
| Backend | `http://127.0.0.1:8098` |
| Frontend | `http://localhost:3000` |

## Quick start (all services)

From the repo root:

```bash
chmod +x scripts/dev.sh
./scripts/dev.sh
```

This starts the backend and launches the frontend dev server.

## Run the backend

```bash
cd maf-copilotkit-agui-hitl-mre
uv run uvicorn hitl_mre.app:create_app --factory --host 127.0.0.1 --port 8094
```

The backend exposes a single AG-UI workflow endpoint at `/agui`.

## Run the CopilotKit frontend

```bash
cd maf-copilotkit-agui-hitl-mre/frontend
npm install
npm run dev
```

Open `http://localhost:3000` and send any chat message.

## Expected frontend behavior

After sending a chat message:

| UI area | What you see | Why |
|---------|--------------|-----|
| Sidebar | Stock `request_info` tool card (often "Running") | MAF emits `TOOL_CALL_*` events for the workflow pause; CopilotKit renders this with `DefaultToolCallRenderer`. |
| Left diagnostics — `useInterrupt` | Stays in "waiting" | MAF does not emit the standard AG-UI interrupt outcome (see [Bug summary](#bug-summary)). |
| Left diagnostics — `useHumanInTheLoop` | `human_review` executions stay at 0 | The frontend registers `human_review`; the workflow never calls that tool name. |

The most reliable resume path in this repro is to **reply with text in chat**
after the pause. The workflow `@response_handler` then yields
`Workflow resumed with human response: …`.

## Why this is not an LLM/tool-selection problem

The workflow executor directly calls `ctx.request_info`. There is no prompt,
model, or probabilistic tool selection in this repro.

## OpenAI calls

This repro does not mock OpenAI calls; it avoids them. The Python backend does
not install the `openai` package after locking the latest MAF dependencies, and
the workflow contains no model client. The frontend uses CopilotKit's runtime
proxy with `ExperimentalEmptyAdapter` and an AG-UI `HttpAgent`, so it forwards
to the local MAF AG-UI endpoint and does not invoke an OpenAI model. The
frontend lockfile may include OpenAI SDK packages transitively through
CopilotKit dependencies, but this repro does not instantiate or call them.

## Bug summary

MAF workflow HITL works in MAF core. CopilotKit 1.61 supports two interrupt
flows via `useInterrupt`:

1. **Standard (AG-UI spec):** `RUN_FINISHED` with
   `outcome.type === "interrupt"` and an `interrupts` array. Resume via
   `runAgent({ resume })` on the next run.
2. **Legacy:** `CUSTOM on_interrupt` event. Resume via
   `forwardedProps.command.resume`.

The MAF AG-UI workflow adapter currently emits a **third shape** that matches
neither contract cleanly:

| What CopilotKit expects | What MAF workflow adapter emits |
|-------------------------|----------------------------------|
| `RUN_FINISHED.outcome.type === "interrupt"` | `RUN_FINISHED` with top-level `interrupt` and `outcome: null` |
| Interrupt without blocking tool-call lifecycle | Full `request_info` tool call (`TOOL_CALL_START` → `ARGS` → `END`) with **no** matching `tool`-role result |
| Resume keyed by interrupt/request id | Partial support: `_extract_resume_payload` and `_resume_to_workflow_responses` exist, but UI paths often do not deliver the payload |

Because HITL is expressed **both** as an open assistant tool call and as a run
interrupt, CopilotKit cannot treat the run as cleanly interrupted while the
`request_info` tool call is still unresolved. That is the core structural
conflict this MRE demonstrates.

### Validated testing findings

These behaviors were confirmed against this stack:

**`useInterrupt`**

- Works when `RUN_FINISHED` is manually corrected to the standard interrupt
  shape; CopilotKit then sends the resume payload on the next `RUN_STARTED`.
- Does **not** work reliably on the stock MAF stream because of the malformed
  `RUN_FINISHED` and the concurrent open `request_info` tool call.
- AG-UI protocol validation also rejects `RUN_FINISHED` while tool calls (or
  open text messages) are still active — so interrupt + in-flight tool call is
  an inherent tension unless the adapter reconciles them (e.g. tool result or
  different event ordering).

**`useHumanInTheLoop`**

- The stock frontend registers the app-level tool `human_review`. MAF never
  calls that name, so the diagnostic hook does not render.
- MAF HITL surfaces arrive as **internal tool calls** instead:
  - **`request_info`** — workflow path (this MRE)
  - **`confirm_changes`** — agent / approval path (not this MRE)
- Wiring `useHumanInTheLoop` to those MAF tool names (or using
  `useRenderToolCall`) can show UI, but resume semantics differ per path.

**Workflow `request_info` resume paths**

| Action | Result |
|--------|--------|
| User sends a **text reply** in chat | **Works.** Adapter maps latest user text to the single pending request; `@response_handler` runs and yields output. |
| User clicks sidebar **approve/submit** without a structured resume | **Fails** on the next message with `No pending requests found in workflow context.` — the button action did not deliver `workflow.run(responses={request_id: …})`. |
| `useInterrupt` resolve with corrected events | **Can work** if resume payload reaches the adapter; stock MAF stream does not emit the events CopilotKit needs. |

**Agent `confirm_changes` (not in this MRE)**

- Submitting approval without a matching `tool`-role result for the paused call
  can produce: `BadRequestError: No tool output found for function call …`
- MAF has synthetic injection logic for `confirm_changes` in the agent adapter,
  but the frontend approval path must produce the message shape the adapter
  expects.

### Other MAF HITL surfaces (not in this MRE)

| Surface | MAF origin | FE appearance | In this repro? |
|---------|------------|---------------|----------------|
| `request_info` | `ctx.request_info(...)` in workflow | `request_info` tool card | Yes |
| `confirm_changes` | Agent tool approval / predictive state | `confirm_changes` tool card | No |
| `human_review` | CopilotKit app-level HITL tool | `useHumanInTheLoop` render | Registered, never called |

## Architecture (this repro)

```
User message
    → CopilotKit runtime (HttpAgent) → POST /agui
    → MAF workflow executor: ctx.request_info(...)
    → AG-UI stream: TOOL_CALL_* (request_info) + RUN_FINISHED (interrupt metadata)
    → CopilotKit sidebar: default tool card
    → CopilotKit diagnostics: useInterrupt waiting, human_review unused

User text reply (reliable path)
    → resume / latest-user-text coercion in adapter
    → workflow.run(responses={request_id: text})
    → @response_handler → yield_output("Workflow resumed with human response: …")
```
