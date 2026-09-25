import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { randomUUID } from "node:crypto";
import { Agent, request } from "node:http";
import { createCoreSession } from "./core.ts";

export type LifecycleEvent = {
  schema_version: 1;
  source: "pi";
  source_instance_id: string;
  session_id: string;
  run_id: string;
  event_id: string;
  kind: "run_started" | "run_waiting" | "run_resumed" | "run_ended";
  timestamp: string;
  metadata: { outcome?: "completed" | "unknown" };
};

export const deliveryTimeoutMs = 200;

// Один HTTP socket сохраняет порядок даже при не ожидающих Promise UI hooks.
// Лимит действует от вызова send, включая ожидание socket; retries отсутствуют.
export function createDelivery(port = Number(process.env.AGENTRGB_PORT ?? "8765")) {
  const agent = new Agent({ keepAlive: false, maxSockets: 1 });
  let pending = 0;
  return async (event: LifecycleEvent): Promise<void> => {
    if (!Number.isInteger(port) || port < 1 || port > 65535 || pending >= 8) return;
    pending++;
    try {
      await new Promise<void>((resolve) => {
        let req: ReturnType<typeof request> | undefined;
        let timer: ReturnType<typeof setTimeout> | undefined;
        let done = false;
        const finish = () => {
          if (done) return;
          done = true;
          clearTimeout(timer);
          req?.destroy();
          resolve();
        };
        try {
          const body = JSON.stringify(event);
          timer = setTimeout(finish, deliveryTimeoutMs);
          req = request({ hostname: "127.0.0.1", port, path: "/v1/events", method: "POST", agent,
            headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) },
          }, (response) => {
            // Ответ не используется как команда; не читать и не буферизовать body.
            response.on("error", finish);
            response.destroy();
            finish();
          });
          req.on("error", finish);
          req.end(body);
        } catch { finish(); }
      });
    } finally { pending--; }
  };
}

export function createAdapter(send: (event: LifecycleEvent) => void | Promise<void>) {
  const instanceId = randomUUID();
  let runId: string | undefined;
  let sessionId: string | undefined;
  let candidate: "completed" | "unknown" = "unknown";
  let waiting = 0;

  const emit = (kind: LifecycleEvent["kind"], outcome?: "completed" | "unknown") => {
    const event: LifecycleEvent = {
      schema_version: 1, source: "pi", source_instance_id: instanceId,
      session_id: sessionId!, run_id: runId!, event_id: randomUUID(), kind,
      timestamp: new Date().toISOString(), metadata: outcome ? { outcome } : {},
    };
    try { return Promise.resolve(send(event)).catch(() => {}); } catch { return Promise.resolve(); }
  };

  return (type: string, event: any, ctx: any): Promise<void> | undefined => {
    try {
      if (type === "agent_start") {
        candidate = "unknown";
        if (runId) return;
        const id = ctx.sessionManager.getSessionId();
        if (typeof id !== "string" || !/^[A-Za-z0-9_-]{1,128}$/.test(id)) return;
        sessionId = id;
        runId = randomUUID();
        waiting = 0;
        return emit("run_started");
      }
      if (!runId) return;
      if (type === "ui_prompt_start") {
        if (waiting++ === 0) return emit("run_waiting");
      } else if (type === "ui_prompt_end") {
        if (waiting > 0 && --waiting === 0) return emit("run_resumed");
      } else if (type === "agent_end") {
        candidate = "unknown";
        const messages = event.messages;
        if (!Array.isArray(messages)) return;
        for (let index = messages.length - 1; index >= 0; index--) {
          const message = messages[index];
          if (message?.role === "assistant") {
            candidate = message.stopReason === "stop" ? "completed" : "unknown";
            break;
          }
        }
      } else if (type === "agent_settled") {
        const delivered = emit("run_ended", candidate);
        runId = undefined;
        sessionId = undefined;
        candidate = "unknown";
        waiting = 0;
        return delivered;
      }
    } catch { candidate = "unknown"; }
  };
}

export default function agentrgb(pi: ExtensionAPI) {
  const core = createCoreSession();
  let handle: ReturnType<typeof createAdapter> | undefined;
  pi.on("session_start", async (_event, ctx) => {
    await core.start(ctx);
    if (!handle && core.connected) handle = createAdapter(createDelivery());
  });
  pi.on("session_shutdown", () => core.shutdown());
  for (const type of ["agent_start", "agent_end", "agent_settled", "ui_prompt_start", "ui_prompt_end"] as const) {
    pi.on(type, (event, ctx) => { if (core.connected) return handle?.(type, event, ctx); });
  }
}
