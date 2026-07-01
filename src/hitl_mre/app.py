from agent_framework import (
    AgentResponse,
    Content,
    Executor,
    Message,
    Workflow,
    WorkflowAgent,
    WorkflowBuilder,
    WorkflowContext,
    handler,
    response_handler,
)
from agent_framework.ag_ui import AgentFrameworkAgent, add_agent_framework_fastapi_endpoint
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse


AGENT_ID = "maf-hitl"
RESUMED_PREFIX = "Workflow resumed with human response:"


def _extract_latest_user_text(messages: list[Message]) -> str:
    for message in reversed(messages):
        role = message.role.value if hasattr(message.role, "value") else str(message.role)
        if role != "user":
            continue
        for content in message.contents or []:
            if content.type == "text":
                return str(content.text)
    return "(no user text)"


class DeterministicHumanInputExecutor(Executor):
    """Workflow executor that always pauses for external human input.

    This avoids model credentials and nondeterminism. Any user message causes a
    MAF workflow request_info event, which WorkflowAgent converts to a
    request_info function call plus function_approval_request content.
    """

    def __init__(self) -> None:
        super().__init__(id="deterministic-human-input")

    @handler
    async def ask_for_human_input(self, messages: list[Message], ctx: WorkflowContext) -> None:
        user_text = _extract_latest_user_text(messages)
        await ctx.request_info(
            f"Approve or edit this deterministic workflow input: {user_text}",
            str,
        )

    @response_handler
    async def handle_human_input(
        self,
        original_request: str,
        response: str,
        ctx: WorkflowContext,
    ) -> None:
        del original_request
        await ctx.yield_output(
            AgentResponse(
                messages=[
                    Message(
                        role="assistant",
                        contents=[
                            Content.from_text(text=f"{RESUMED_PREFIX} {response}"),
                        ],
                    )
                ]
            )
        )


def create_workflow() -> Workflow:
    return WorkflowBuilder(start_executor=DeterministicHumanInputExecutor()).build()


def create_workflow_agent() -> WorkflowAgent:
    workflow = create_workflow()
    return WorkflowAgent(workflow=workflow, name="Deterministic MAF HITL Workflow")


def create_app() -> FastAPI:
    app = FastAPI(title="MAF CopilotKit AG-UI HITL MRE")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def register_fresh_agent(path: str) -> None:
        add_agent_framework_fastapi_endpoint(
            app=app,
            agent=AgentFrameworkAgent(agent=create_workflow_agent()),
            path=path,
        )

    register_fresh_agent("/agui")
    register_fresh_agent("/agui-control")
    register_fresh_agent("/agui-mismatch")

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({"ok": True, "agentId": AGENT_ID})

    @app.get("/expected")
    async def expected() -> JSONResponse:
        return JSONResponse(
            {
                "actualMafAguiInterruptEvent": "CUSTOM function_approval_request",
                "copilotKitUseInterruptExpectedEvent": "CUSTOM on_interrupt",
                "copilotKitUseInterruptResumeLocation": "forwardedProps.command.resume",
                "mafAguiResumeLocation": "messages[] role=tool content={\"accepted\": true, ...}",
            }
        )

    return app


def main() -> None:
    import uvicorn

    uvicorn.run("hitl_mre.app:create_app", factory=True, host="127.0.0.1", port=8098)


if __name__ == "__main__":
    main()
