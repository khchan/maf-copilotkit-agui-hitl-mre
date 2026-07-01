"use client";

import {
  CopilotChat,
  CopilotKit,
  useHumanInTheLoop,
  useInterrupt,
} from "@copilotkit/react-core/v2";
import { useState } from "react";

const AGENT_ID = "maf-hitl";

function HookDiagnostics() {
  const [humanToolExecutions, setHumanToolExecutions] = useState(0);

  const interruptElement = useInterrupt({
    agentId: AGENT_ID,
    renderInChat: false,
    render: ({ event, resolve }) => (
      <section className="diagnostic success" data-testid="interrupt-rendered">
        <h2>useInterrupt rendered</h2>
        <pre>{JSON.stringify(event.value, null, 2)}</pre>
        <button onClick={() => resolve("approved from useInterrupt")}>
          Resume
        </button>
      </section>
    ),
  });

  useHumanInTheLoop({
    agentId: AGENT_ID,
    name: "human_review",
    description:
      "A normal CopilotKit app-level HITL tool. The MAF workflow never calls this tool name.",
    render: (props) => {
      if (props.status === "executing") {
        return (
          <section className="diagnostic success" data-testid="human-review-rendered">
            <h2>useHumanInTheLoop human_review rendered</h2>
            <pre>{JSON.stringify(props.args, null, 2)}</pre>
            <button
              onClick={() => {
                setHumanToolExecutions((count) => count + 1);
                void props.respond("approved from human_review");
              }}
            >
              Respond
            </button>
          </section>
        );
      }

      return (
        <section className="diagnostic">
          <h2>human_review status</h2>
          <p>{props.status}</p>
        </section>
      );
    },
  });

  return (
    <aside className="panel">
      <h1>Hook diagnostics</h1>
      <p>
        Send any chat message. The MAF workflow deterministically calls
        <code> ctx.request_info(...)</code>.
      </p>
      <div className="diagnostic" data-testid="interrupt-missing">
        <h2>useInterrupt</h2>
        {interruptElement ?? (
          <p>
            Waiting for <code>CUSTOM on_interrupt</code>. MAF AG-UI emits
            <code> CUSTOM function_approval_request</code> instead.
          </p>
        )}
      </div>
      <div className="diagnostic" data-testid="human-review-missing">
        <h2>useHumanInTheLoop</h2>
        <p>
          <code>human_review</code> executions: {humanToolExecutions}
        </p>
        <p>
          This normal app-level frontend tool is not called by the MAF workflow.
          MAF emits internal <code>request_info</code> and
          <code> confirm_changes</code> tool names.
        </p>
      </div>
    </aside>
  );
}

export default function Page() {
  return (
    <CopilotKit runtimeUrl="/api/copilotkit" agent={AGENT_ID}>
      <main className="shell">
        <HookDiagnostics />
        <section className="chat">
          <CopilotChat
            agentId={AGENT_ID}
            labels={{
              chatInputPlaceholder:
                "Type anything to trigger the deterministic MAF workflow pause",
            }}
          />
        </section>
      </main>
    </CopilotKit>
  );
}
