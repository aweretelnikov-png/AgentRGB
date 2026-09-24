// Стенд живого Pi. stdout print и stderr Pi не сохраняются.
import { spawn } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import { createWriteStream } from 'node:fs';
import { connect } from 'node:net';
import { resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';

const [scenario, cli] = process.argv.slice(2);
if (!['A', 'B', 'C', 'down'].includes(scenario) || !cli) throw new Error('Usage: node run.mjs A|B|C|down <Pi cli.js>');
const here = fileURLToPath(new URL('.', import.meta.url));
const root = resolve(here, '../..');
const directory = join(here, 'results', `${scenario}-${new Date().toISOString().replace(/[:.]/g, '-')}`);
const port = Number(process.env.AGENTRGB_PORT ?? '8765');
// Не спутать чужой процесс с Core стенда, особенно в опыте down.
await new Promise((resolveCheck, reject) => {
  const socket = connect({ host: '127.0.0.1', port });
  socket.setTimeout(300);
  socket.on('connect', () => { socket.destroy(); reject(new Error('Port already in use')); });
  socket.on('timeout', () => { socket.destroy(); reject(new Error('Port check timeout')); });
  socket.on('error', error => error.code === 'ECONNREFUSED' ? resolveCheck() : reject(error));
});
await mkdir(directory, { recursive: true });
const env = { ...process.env, PYTHONPATH: join(root, 'src'), AGENTRGB_PI_RESULTS: directory };
let core;
let coreClosed;
let coreLog;
try {
  if (scenario !== 'down') {
    coreLog = createWriteStream(join(directory, 'core.log'));
    core = spawn('python', ['-u', join(here, 'core-host.py')], { cwd: root, env, stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true });
    coreClosed = new Promise(resolveClose => core.on('close', code => resolveClose(code)));
    core.stdout.pipe(coreLog, { end: false });
    core.stderr.pipe(coreLog, { end: false });
    await new Promise((ready, reject) => {
      const timer = setTimeout(() => reject(new Error('Core startup timeout')), 5000);
      core.on('error', error => { clearTimeout(timer); reject(error); });
      core.on('exit', () => { clearTimeout(timer); reject(new Error('Core exited')); });
      core.stdout.on('data', chunk => {
        if (chunk.toString().includes('LISTEN ')) { clearTimeout(timer); ready(); }
      });
    });
  }
  const prompts = {
    A: 'Reply OK. Do not use tools.',
    down: 'Reply OK. Do not use tools.',
    B: 'Call ask_user_question exactly once to ask me to choose Yes or No for this harmless AgentRGB test. After my answer reply OK. Do not use other tools.',
    C: 'Run this harmless bash command exactly once: node -e "setTimeout(() => {}, 30000)". Then reply OK. Do not access files or use other tools.',
  };
  const interactive = ['B', 'C'].includes(scenario);
  const args = [resolve(cli), ...(interactive ? [] : ['--print']), '--no-session', '--no-extensions',
    '--no-skills', '--no-prompt-templates', '--no-themes', '--no-context-files', '--thinking', 'off',
    '--system-prompt', 'Harmless AgentRGB lifecycle experiment. Follow the request literally. Do not access other files.',
    '-e', join(root, 'integrations/pi/agentrgb.ts'),
    '-e', join(root, 'experiments/pi-events/pi-event-recorder.ts')];
  if (scenario === 'B') args.push('-e', join(process.env.USERPROFILE, '.pi/agent/npm/node_modules/@juicesharp/rpiv-ask-user-question/index.ts'), '--tools', 'ask_user_question');
  else if (scenario === 'C') args.push('--tools', 'bash');
  else args.push('--no-tools');
  args.push(prompts[scenario]);
  console.log(`Scenario ${scenario}; results: ${directory}`);
  if (scenario === 'B') console.log('Оставьте вопрос без ответа на несколько секунд, ответьте, дождитесь OK и введите /quit.');
  if (scenario === 'C') console.log('Во время работы нажмите Escape, дождитесь остановки и введите /quit.');
  const pi = spawn(process.execPath, args, { cwd: here, env, stdio: interactive ? 'inherit' : ['ignore', 'ignore', 'pipe'] });
  const diagnostics = new Set();
  pi.stderr?.on('data', chunk => {
    for (const [name, pattern] of [
      ['authentication-failed', /authentication failed|re-authenticate|No API key/i],
      ['extension-load-failed', /failed to load extension|cannot find module/i],
      ['recorder-failed', /AgentRGB recorder disabled/],
    ]) if (pattern.test(chunk.toString())) diagnostics.add(name);
  });
  let timedOut = false;
  const timer = interactive ? undefined : setTimeout(() => { timedOut = true; pi.kill(); }, 90000);
  const result = await new Promise(resolveExit => {
    pi.on('error', () => resolveExit({ launchFailed: true }));
    pi.on('close', (exitCode, signal) => resolveExit({ exitCode, signal }));
  });
  clearTimeout(timer);
  await delay(scenario === 'down' ? 0 : 2200);
  const summary = { scenario, ...result, timedOut, diagnostics: [...diagnostics], rawOutputSaved: false };
  await writeFile(join(directory, 'process.json'), JSON.stringify(summary, null, 2) + '\n');
  console.log(JSON.stringify(summary));
  process.exitCode = timedOut || result.launchFailed ? 1 : result.exitCode ?? 1;
} finally {
  if (core) {
    core.stdin.end();
    await coreClosed;
    await new Promise(resolveEnd => coreLog.end(resolveEnd));
  }
}
