import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

// Только idle-контроль. Активный waiting проверяется установленным ask_user_question.
export default function idleProbe(pi: ExtensionAPI) {
  pi.registerCommand("pi-events-idle", {
    description: "Безвредный UI prompt вне активного запуска",
    handler: async (_args, ctx) => {
      if (ctx.mode !== "tui" || !ctx.isIdle()) return;
      await ctx.ui.confirm("AgentRGB: idle probe", "Подождите несколько секунд, затем выберите любой ответ.");
    },
  });
}
