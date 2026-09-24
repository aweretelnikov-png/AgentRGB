import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { setTimeout as delay } from "node:timers/promises";

// Load after integrations/pi/agentrgb.ts: its agent_start handler opens the run.
export default function confirmOnStart(pi: ExtensionAPI) {
  let asked = false;
  pi.on("agent_start", async (_event, ctx) => {
    if (asked || !ctx.hasUI) return;
    asked = true;
    await delay(2000); // Leave visible working time before Pi opens its real UI prompt.
    await ctx.ui.confirm("AgentRGB 04C", "Подтвердите продолжение безопасного теста подсветки.");
  });
}
