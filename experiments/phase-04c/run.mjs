// One real Pi run through the unchanged extension and Core. No raw Pi output is saved.
import { spawn } from 'node:child_process';
import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises';
import { connect } from 'node:net';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';

const mode = process.argv[2];
if (!['fake', 'aula-f75'].includes(mode)) throw new Error('Usage: node run.mjs fake|aula-f75');
const here = fileURLToPath(new URL('.', import.meta.url));
const root = resolve(here, '../..');
const directory = join(here, 'results', `${mode}-${new Date().toISOString().replace(/[:.]/g, '-')}`);
const cli = join(process.env.APPDATA, 'npm/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js');
const MAX_SECONDS = 150;
const expected = ['run_started', 'run_waiting', 'run_resumed', 'run_ended'];
let sequence = 0;
let deviation;
let settled = false;
let uiRequested = false;
let core;
let pi;
let coreClose;
let piClose;
let timedOut = false;
let coreReady;
let coreReadyReject;
let coreReadyResolve;
const piTypes = new Set(['agent_start', 'ui_prompt_start', 'ui_prompt_end', 'agent_end', 'agent_settled']);

function lines(stream, consume) {
  let buffer = '';
  stream.on('data', chunk => {
    buffer += chunk.toString('utf8');
    for (;;) {
      const at = buffer.indexOf('\n');
      if (at < 0) break;
      const line = buffer.slice(0, at).replace(/\r$/, '');
      buffer = buffer.slice(at + 1);
      consume(line);
    }
  });
}

async function portFree() {
  await new Promise((ok, fail) => {
    const socket = connect({ host: '127.0.0.1', port: 8765 });
    socket.setTimeout(400);
    socket.once('connect', () => { socket.destroy(); fail(new Error('Port 8765 occupied')); });
    socket.once('timeout', () => { socket.destroy(); fail(new Error('Port 8765 check timed out')); });
    socket.once('error', error => error.code === 'ECONNREFUSED' ? ok() : fail(error));
  });
}

async function merge() {
  const rows = [];
  const corePath = join(directory, 'core.jsonl');
  for (const line of (await readFile(corePath, 'utf8')).split(/\r?\n/)) {
    if (line) rows.push(JSON.parse(line));
  }
  for (const name of await readdir(directory)) {
    if (!/^events-.*\.jsonl$/.test(name)) continue;
    for (const line of (await readFile(join(directory, name), 'utf8')).split(/\r?\n/)) {
      if (!line) continue;
      const event = JSON.parse(line);
      if (piTypes.has(event.type)) rows.push({ timestamp_utc: event.timestamp,
        name: 'pi_event', pi_event: event.type,
        stop_reason: event.type === 'agent_end' ? event.stopReason : undefined });
    }
  }
  rows.sort((a, b) => Date.parse(a.timestamp_utc) - Date.parse(b.timestamp_utc));
  await writeFile(join(directory, 'journal.jsonl'), rows.map(row => JSON.stringify(row)).join('\n') + '\n');
  return rows;
}

await portFree();
await mkdir(directory, { recursive: true });
const env = { ...process.env, PYTHONPATH: join(root, 'src'), AGENTRGB_PORT: '8765',
  AGENTRGB_PI_RESULTS: directory };
const prompt = 'Reply OK without using tools. This is a harmless AgentRGB lifecycle check.';
const args = [cli, ...(mode === 'fake' ? ['--mode', 'rpc'] : []), '--no-session',
  '--no-extensions', '--no-skills', '--no-prompt-templates', '--no-themes', '--no-context-files',
  '--no-tools', '--thinking', 'off', '--system-prompt',
  'Reply briefly. Do not access files or use tools.',
  '-e', join(root, 'integrations/pi/agentrgb.ts'),
  '-e', join(root, 'experiments/pi-events/pi-event-recorder.ts'),
  '-e', join(here, 'confirm-on-start.ts')];
if (mode === 'aula-f75') args.push(prompt);

const timer = setTimeout(() => {
  timedOut = true;
  deviation ??= 'overall_timeout';
  core?.stdin.end();
  pi?.kill();
}, MAX_SECONDS * 1000);

try {
  coreReady = new Promise((ok, fail) => { coreReadyResolve = ok; coreReadyReject = fail; });
  core = spawn('python', ['-u', join(here, 'core_host.py'), '--output', mode,
    '--journal', join(directory, 'core.jsonl')],
  { cwd: root, env, stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true });
  coreClose = new Promise(ok => core.once('close', ok));
  core.once('error', () => coreReadyReject(new Error('Core launch failed')));
  core.once('exit', () => coreReadyReject(new Error('Core exited before ready')));
  lines(core.stdout, line => {
    if (line.startsWith('LISTEN ')) coreReadyResolve();
    if (!line.startsWith('JOURNAL ')) return;
    const row = JSON.parse(line.slice(8));
    if (row.name === 'core_event') {
      if (row.result !== 'applied' || row.normalized_event !== expected[sequence++]) {
        deviation ??= 'unexpected_core_sequence';
      }
    } else if (row.name === 'output_unavailable' ||
               (row.name === 'heartbeat_stopped' && (row.output_error || sequence < expected.length))) {
      deviation ??= 'output_failure';
    }
    if (deviation) { core.stdin.end(); pi?.kill(); }
  });
  await Promise.race([coreReady, delay(5000).then(() => { throw new Error('Core startup timeout'); })]);
  console.log(`04C ${mode}: ${directory}`);
  if (mode === 'aula-f75') console.log('Подтвердите вопрос Pi, дождитесь OK, затем введите /quit. Лимит: 150 с / 3000 Direct frames.');
  pi = spawn(process.execPath, args, { cwd: here, env,
    stdio: mode === 'fake' ? ['pipe', 'pipe', 'pipe'] : 'inherit' });
  piClose = new Promise(ok => pi.once('close', (code, signal) => ok({ code, signal })));
  if (mode === 'fake') {
    // Parse RPC JSONL but retain only message types. Model output is discarded.
    lines(pi.stdout, line => {
      let row;
      try { row = JSON.parse(line); } catch { deviation ??= 'invalid_pi_rpc'; return; }
      if (row.type === 'extension_ui_request' && row.method === 'confirm') {
        uiRequested = true;
        delay(2500).then(() => pi.stdin.write(JSON.stringify({
          type: 'extension_ui_response', id: row.id, confirmed: true,
        }) + '\n')).catch(() => {});
      }
      if (row.type === 'agent_settled') settled = true;
    });
    lines(pi.stderr, () => {}); // Never persist authentication or model text.
    pi.stdin.write(JSON.stringify({ id: '04c-prompt', type: 'prompt', message: prompt }) + '\n');
    while (!settled && !deviation && pi.exitCode === null && !timedOut) await delay(100);
    if (settled) await delay(2300);
    pi.stdin.end();
    await Promise.race([piClose, delay(3000)]);
    if (pi.exitCode === null) pi.kill();
  }
  const piResult = await piClose;
  core.stdin.end();
  await coreClose;
  const rows = await merge();
  const piEvents = rows.filter(row => row.name === 'pi_event').map(row => row.pi_event);
  const coreEvents = rows.filter(row => row.name === 'core_event').map(row => row.normalized_event);
  const visible = rows.filter(row => row.name === 'core_event').map(row => row.visible_state);
  const idle = rows.some(row => row.name === 'core_tick' && row.visible_state === 'idle');
  const frames = rows.filter(row => row.name === 'direct_frame');
  const frameColors = frames.map(row => row.desired_rgb).filter((color, index, all) => index === 0 || color !== all[index - 1]);
  const closed = rows.filter(row => row.name === 'handle_closed');
  const workerStopped = rows.some(row => row.name === 'worker_stopped');
  const coreShutdown = rows.some(row => row.name === 'core_shutdown');
  const listenerClosed = rows.some(row => row.name === 'listener_closed');
  uiRequested ||= piEvents.includes('ui_prompt_start');
  settled ||= piEvents.includes('agent_settled');
  const completed = rows.some(row => row.name === 'core_event' && row.normalized_event === 'run_ended' && row.outcome === 'completed');
  const hardwarePassed = mode === 'fake' || (frames.length <= 3000 && closed.length === 1 && workerStopped &&
    JSON.stringify(frameColors) === JSON.stringify(['0000FF', 'FFFF00', '0000FF', '00FF00']));
  const pass = !deviation && !timedOut && piResult.code === 0 && uiRequested && settled && completed &&
    sequence === expected.length && idle && coreShutdown && listenerClosed && hardwarePassed &&
    JSON.stringify(coreEvents) === JSON.stringify(expected) &&
    JSON.stringify(visible) === JSON.stringify(['working', 'waiting', 'working', 'completed']) &&
    JSON.stringify(piEvents.filter(x => x !== 'agent_end')) ===
      JSON.stringify(['agent_start', 'ui_prompt_start', 'ui_prompt_end', 'agent_settled']);
  const summary = { mode, status: pass ? 'passed' : 'incomplete', deviation: deviation ?? null,
    timedOut, uiRequested, settled, completed, piResult, piEvents, coreEvents, visible, idle,
    frameCount: frames.length, frameColors, firstFrameUtc: frames[0]?.timestamp_utc ?? null,
    lastFrameUtc: frames.at(-1)?.timestamp_utc ?? null, handleClosed: closed.length === 1,
    workerStopped, coreShutdown, listenerClosed,
    maxSeconds: MAX_SECONDS, maxDirectFrames: mode === 'aula-f75' ? 3000 : 0 };
  await writeFile(join(directory, 'summary.json'), JSON.stringify(summary, null, 2) + '\n');
  console.log(JSON.stringify(summary));
  if (!pass) process.exitCode = 1;
} finally {
  clearTimeout(timer);
  if (pi && pi.exitCode === null) pi.kill();
  if (core && core.exitCode === null) {
    core.stdin.end();
    await Promise.race([coreClose, delay(2000)]);
    if (core.exitCode === null) core.kill();
  }
}
