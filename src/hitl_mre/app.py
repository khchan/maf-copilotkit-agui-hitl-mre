from agent_framework import (
    AgentResponse,
    AgentExecutorRequest,
    Content,
    Executor,
    Message,
    Workflow,
    WorkflowBuilder,
    WorkflowContext,
    handler,
    response_handler,
)
from agent_framework.ag_ui import add_agent_framework_fastapi_endpoint
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
    MAF workflow request_info event, which the AG-UI workflow bridge converts to a
    request_info tool call.
    """

    def __init__(self) -> None:
        super().__init__(id="deterministic-human-input")

    @handler
    async def ask_for_human_input(self, messages: list[Message], ctx: WorkflowContext) -> None:
        user_text = _extract_latest_user_text(messages)
        print(f"Requesting human input for: {user_text}")
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
        print(f"Human input received: {response}")
        # The following is needed if the human sends a response directly in the chat, 
        # otherwise you will get the error:
        # Cannot send 'RUN_FINISHED' while text messages are still active:
        await ctx.send_message(
                AgentExecutorRequest(messages=[Message("user", [response])], should_respond=True),
                target_id=self.id,
            )
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


def create_app() -> FastAPI:
    app = FastAPI(title="MAF CopilotKit AG-UI HITL MRE")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    add_agent_framework_fastapi_endpoint(
        app=app,
        agent=create_workflow(),
        path="/agui",
    )

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({"ok": True, "agentId": AGENT_ID})

    return app


def main() -> None:
    import uvicorn

    uvicorn.run("hitl_mre.app:create_app", factory=True, host="127.0.0.1", port=8094, log_level="info")


if __name__ == "__main__":
    main()
