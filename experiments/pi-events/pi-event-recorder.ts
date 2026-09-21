import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { mkdir, appendFile } from "node:fs/promises";
import { join } from "node:path";

// Только поля разрешённого списка. Не перечислять свойства event/context.
export const events = [
  "session_start", "session_shutdown", "input", "before_agent_start",
  "agent_start", "agent_end", "agent_settled", "ui_prompt_start", "ui_prompt_end",
  "turn_start", "turn_end", "tool_call", "tool_result",
  "session_before_compact", "session_compact", "session_compact_failed",
] as const;

function safe<T>(read: () => T): T | undefined {
  try { return read(); } catch { return undefined; }
}

// StopReason из установленного Pi 0.85.1. Не сохранять произвольную строку.
const stopReasons = new Set(["pending", "stop", "length", "toolUse", "error", "aborted", "deferred"]);
function assistantStopReason(message: any): string | undefined {
  if (message?.role !== "assistant") return undefined;
  const value = message.stopReason;
  return typeof value === "string" && stopReasons.has(value) ? value : undefined;
}

function finalAssistantStopReason(messages: any): string | undefined {
  if (!Array.isArray(messages)) return undefined;
  for (let index = messages.length - 1; index >= 0; index--) {
    const message = messages[index];
    // Если причина последнего assistant отсутствует/неизвестна, не подменять её ранней.
    if (message?.role === "assistant") return assistantStopReason(message);
  }
  return undefined;
}

export function project(event: any, ctx: any, sequence: number) {
  const row: Record<string, unknown> = {
    sequence, timestamp: new Date().toISOString(), type: event.type,
    mode: safe(() => ctx.mode), isIdle: safe(() => ctx.isIdle()),
    hasPendingMessages: safe(() => ctx.hasPendingMessages()),
    sessionId: safe(() => ctx.sessionManager.getSessionId()),
  };
  if (event.type === "input") row.source = event.source;
  if (event.type === "agent_end" && typeof event.willRetry === "boolean") row.willRetry = event.willRetry;
  if (event.type === "agent_end") row.stopReason = safe(() => finalAssistantStopReason(event.messages));
  if (event.type === "turn_end") row.stopReason = safe(() => assistantStopReason(event.message));
  if (event.type === "ui_prompt_start") row.kind = event.kind;
  if (event.type === "turn_start" || event.type === "turn_end") row.turnIndex = event.turnIndex;
  if (event.type === "tool_call" || event.type === "tool_result") {
    row.toolCallId = event.toolCallId;
    row.toolName = event.toolName;
    if (typeof event.isError === "boolean") row.isError = event.isError;
  }
  if (["session_before_compact", "session_compact", "session_compact_failed"].includes(event.type)) {
    row.reason = event.reason;
    row.willRetry = event.willRetry;
    if (typeof event.aborted === "boolean") row.aborted = event.aborted;
  }
  return row;
}

export default function recorder(pi: ExtensionAPI) {
  // Каталог задаёт запускающий процесс; без него расширение ничего не пишет.
  const directory = process.env.AGENTRGB_PI_RESULTS;
  if (!directory) return;
  let sequence = 0;
  let pending = 0;
  let failed = false;
  const fail = () => {
    if (!failed) {
      failed = true;
      // Без текста исключения: он может содержать путь или другие данные.
      try { process.stderr.write("AgentRGB recorder disabled; trace incomplete.\n"); } catch {}
    }
  };
  // Файл уникален для процесса, не смешиваем разные наблюдения.
  const file = join(directory, `events-${Date.now()}-${process.pid}.jsonl`);
  let tail = mkdir(directory, { recursive: true }).then(() => {}).catch(fail);
  for (const type of events) {
    pi.on(type as any, ((event: any, ctx: any) => {
      try {
        if (failed) return;
        if (pending >= 1024) { fail(); return; }
        const line = JSON.stringify(project(event, ctx, ++sequence)) + "\n";
        pending++;
        tail = tail.then(async () => {
          if (!failed) await appendFile(file, line, { encoding: "utf8", mode: 0o600 });
        }).catch(fail).finally(() => { pending--; });
        // Только при штатном teardown ждём уже поставленные записи, максимум 500 мс.
        if (type === "session_shutdown") {
          return new Promise<void>((resolve) => {
            const timer = setTimeout(() => { fail(); resolve(); }, 500);
            tail.then(() => { clearTimeout(timer); resolve(); });
          });
        }
      } catch { fail(); }
      // Не возвращать решения, сообщения или модифицированные события.
    }) as any);
  }
}
