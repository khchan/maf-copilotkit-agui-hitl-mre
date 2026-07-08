import {
  CopilotRuntime,
  ExperimentalEmptyAdapter,
  copilotRuntimeNextJSAppRouterEndpoint,
} from "@copilotkit/runtime";
import { HttpAgent } from "@ag-ui/client";
import { NextRequest } from "next/server";

const AGENT_ID = "maf-hitl";
const MAF_AGUI_URL = process.env.MAF_AGUI_URL ?? "http://127.0.0.1:8094/agui";

const runtime = new CopilotRuntime({
  agents: {
    [AGENT_ID]: new HttpAgent({ url: MAF_AGUI_URL }),
  },
});

const serviceAdapter = new ExperimentalEmptyAdapter();

const logIncomingMessages = async (request: Request) => {

  try {
    const requestBody = await request.clone().text();
    if (!requestBody) {
      console.log(`Incoming request body is empty`);
      return;
    }

    const parsedBody: unknown = JSON.parse(requestBody);
    if (typeof parsedBody === 'object' && parsedBody && 'messages' in parsedBody) {
      console.log(`Incoming messages: %o`, (parsedBody as { messages: unknown }).messages);
      return;
    }

    console.log(`Incoming request payload: %o`, parsedBody);
  } catch (error) {
    console.log(`Failed to log incoming messages: %o`, error instanceof Error ? error.message : 'Unknown error');
  }
};

export const POST = async (req: NextRequest) => {
  logIncomingMessages(req);
  const { handleRequest } = copilotRuntimeNextJSAppRouterEndpoint({
    runtime,
    serviceAdapter,
    endpoint: "/api/copilotkit",
  });

  return handleRequest(req);
};
