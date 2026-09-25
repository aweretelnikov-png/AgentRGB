import { spawn } from "node:child_process";
import { request } from "node:http";
import { setTimeout as delay } from "node:timers/promises";

export const startupTimeoutMs = 5000;
export const healthTimeoutMs = 300;
export const pollIntervalMs = 100;
export const shutdownTimeoutMs = 1500;
export const readyLine = "AGENTRGB_READY\n";

// Только loopback, без proxy/redirect, с ограничением времени и размера ответа.
export function probeHealth(port: number, timeout = healthTimeoutMs): Promise<boolean> {
  return new Promise(resolve => {
    let req: ReturnType<typeof request> | undefined;
    let done = false;
    const finish = (ok = false) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      req?.destroy();
      resolve(ok);
    };
    const timer = setTimeout(finish, timeout);
    try {
      req = request({ hostname: "127.0.0.1", port, path: "/health", agent: false }, response => {
        let body = "";
        response.on("error", () => finish());
        response.on("aborted", () => finish());
        response.on("data", chunk => {
          body += chunk.toString();
          if (body.length > 1024) finish();
        });
        response.on("end", () => {
          try {
            const value = JSON.parse(body);
            finish(response.statusCode === 200 && value.status === "ok" && value.service === "agentrgb");
          } catch { finish(); }
        });
      });
      req.on("error", () => finish());
      req.end();
    } catch { finish(); }
  });
}

// Приватные stdio pipes подтверждают владение и дают штатный shutdown на Windows.
export function spawnCore(spawnProcess = spawn) {
  const child = spawnProcess("agentrgb", ["start", "--output", "aula-f75"], {
    shell: false, windowsHide: true, stdio: ["pipe", "pipe", "ignore"],
    env: { ...process.env, AGENTRGB_PARENT_STDIO: "1" },
  });
  const state = { ready: false, exited: false, missing: false, stop };
  let stopping: Promise<void> | undefined;
  let buffer = "";
  let resolveExit: () => void;
  const closed = new Promise<void>(resolve => { resolveExit = resolve; });
  child.on("error", (error: NodeJS.ErrnoException) => {
    state.missing = error.code === "ENOENT";
    state.exited = true;
    resolveExit();
  });
  child.once("exit", () => { state.exited = true; });
  child.once("close", () => { state.exited = true; resolveExit(); });
  child.stdin?.on("error", () => {});
  child.stdout?.on("error", () => {});
  child.stdout?.on("data", chunk => {
    if (state.ready || buffer.length > readyLine.length) return;
    buffer += chunk.toString().replace(/\r/g, "");
    if (buffer === readyLine) state.ready = true;
  });
  function waitForExit() {
    return new Promise<void>(resolve => {
      const timer = setTimeout(resolve, shutdownTimeoutMs);
      closed.then(() => { clearTimeout(timer); resolve(); });
    });
  }
  function stop() {
    return stopping ??= (async () => {
      try {
        if (state.exited) return;
        child.stdin?.end();
        await waitForExit();
        if (!state.exited) {
          // Windows console entry point может иметь дочерний python.exe.
          if (process.platform === "win32" && child.pid) {
            const killer = spawnProcess("taskkill", ["/PID", String(child.pid), "/T", "/F"],
              { shell: false, windowsHide: true, stdio: "ignore" });
            killer.on("error", () => {});
            killer.unref();
          } else {
            child.kill("SIGKILL");
          }
          await waitForExit();
        }
      } catch { /* Best-effort cleanup только собственного child. */ }
      finally {
        child.stdin?.destroy();
        child.stdout?.destroy();
        child.unref();
      }
    })();
  }
  return state;
}

export function createCoreSession({
  port = Number(process.env.AGENTRGB_PORT ?? "8765"),
  health = (timeout: number) => probeHealth(port, timeout),
  launch = spawnCore,
  wait = (ms: number) => delay(ms),
  now = () => performance.now(),
} = {}) {
  let child: ReturnType<typeof spawnCore> | undefined;
  let connected = false;
  let ownsCore = false;
  let stopped = false;
  let warned = false;
  let starting: Promise<void> | undefined;
  let stopping: Promise<void> | undefined;

  function warn(ctx: any, message: string) {
    if (warned || stopped) return;
    warned = true;
    try { if (ctx?.hasUI) ctx.ui.notify(message, "warning"); } catch { /* Pi продолжает работу. */ }
  }
  async function start(ctx: any) {
    if (stopped) return;
    return starting ??= (async () => {
      try {
        if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error();
        if (await health(healthTimeoutMs)) { connected = !stopped; return; }
        if (stopped) return;
        child = launch();
        const deadline = now() + startupTimeoutMs;
        while (!stopped && now() < deadline) {
          const healthy = await health(Math.min(healthTimeoutMs, deadline - now()));
          if (stopped) break;
          if (healthy && (child.ready || child.exited)) {
            connected = true;
            ownsCore = child.ready && !child.exited;
            return;
          }
          if (child.missing) {
            warn(ctx, "AgentRGB Core not found. Install AgentRGB first.");
            break;
          }
          await wait(Math.min(pollIntervalMs, Math.max(0, deadline - now())));
        }
        warn(ctx, "AgentRGB Core unavailable. Integration disabled for this session.");
      } catch (error) {
        warn(ctx, (error as NodeJS.ErrnoException)?.code === "ENOENT"
          ? "AgentRGB Core not found. Install AgentRGB first."
          : "AgentRGB Core unavailable. Integration disabled for this session.");
      } finally {
        if (!connected) {
          ownsCore = false;
          try { await child?.stop(); } catch { /* Не ломать Pi. */ }
        }
      }
    })();
  }
  function shutdown() {
    stopped = true;
    connected = false;
    return stopping ??= (async () => {
      await starting;
      try { await child?.stop(); } catch { /* Никогда не останавливать external Core. */ }
      ownsCore = false;
    })();
  }
  return {
    start, shutdown,
    get connected() { return connected && !stopped && (!ownsCore || !child?.exited); },
    get ownsCore() { return ownsCore && !child?.exited; },
  };
}
