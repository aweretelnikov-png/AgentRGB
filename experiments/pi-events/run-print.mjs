// Реальный CLI Pi. Содержимое ответов и инструментов не сохраняется и не анализируется.
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { join, resolve } from 'node:path';
import { mkdir, writeFile } from 'node:fs/promises';

const [scenario, cli, mode = 'print'] = process.argv.slice(2);
const prompts = {
  A: 'Reply with OK. Do not use tools.',
  B: 'Use read exactly once to read fixture.txt in the current directory, then reply OK. Do not use any other tool.',
  F: 'Use read exactly once on missing-fixture-intentionally-absent.txt in the current directory. It does not exist. After the tool error, reply OK without retrying or using other tools.',
};
if (!cli || !prompts[scenario] || !['print', 'json'].includes(mode)) throw new Error('Usage: node run-print.mjs A|B|F <installed Pi cli.js> [print|json]');
const cwd = fileURLToPath(new URL('.', import.meta.url));
const result = join(cwd, 'results', `${scenario}-${mode === 'json' ? 'json-' : ''}${new Date().toISOString().replace(/[:.]/g, '-')}`);
await mkdir(result, { recursive: true });
const child = spawn(process.execPath, [resolve(cli), ...(mode === 'json' ? ['--mode', 'json'] : ['--print']), '--no-session', '--no-extensions',
  '--no-skills', '--no-prompt-templates', '--no-themes', '--no-context-files',
  '--system-prompt', 'This is a harmless lifecycle experiment. Follow the given request literally. Do not access any other files.',
  '--thinking', 'off', ...(scenario === 'A' ? ['--no-tools'] : ['--tools', 'read']),
  '-e', join(cwd, 'pi-event-recorder.ts'), prompts[scenario]], {
  cwd, env: { ...process.env, AGENTRGB_PI_RESULTS: result }, stdio: ['ignore', mode === 'json' ? 'pipe' : 'ignore', 'pipe'],
});
// Минимальная проверка JSON mode: только типы lifecycle, без копирования event.
const wireRows = [];
let wireBuffer = '';
let wireInvalid = false;
if (mode === 'json') {
  child.stdout.setEncoding('utf8');
  child.stdout.on('data', chunk => {
    if (wireInvalid) return;
    wireBuffer += chunk;
    if (wireBuffer.length > 1024 * 1024) { wireInvalid = true; wireBuffer = ''; return; }
    let newline;
    while ((newline = wireBuffer.indexOf('\n')) >= 0) {
      const line = wireBuffer.slice(0, newline);
      wireBuffer = wireBuffer.slice(newline + 1);
      try {
        const event = JSON.parse(line);
        if (!['session', 'agent_start', 'agent_end', 'agent_settled', 'turn_start', 'turn_end', 'tool_execution_start', 'tool_execution_end'].includes(event.type)) continue;
        if (wireRows.length >= 1024) { wireInvalid = true; return; }
        const row = { sequence: wireRows.length + 1, type: event.type };
        if (event.type === 'agent_end' && typeof event.willRetry === 'boolean') row.willRetry = event.willRetry;
        wireRows.push(row);
      } catch { wireInvalid = true; wireBuffer = ''; return; }
    }
  });
}
// Только категории известных ошибок запуска; текст stderr не сохраняется.
const diagnostics = new Set();
child.stderr.on('data', chunk => {
  const text = chunk.toString();
  for (const [category, pattern] of [
    ['authentication-failed', /authentication failed|re-authenticate|refresh.*token/i],
    ['api-key-unavailable', /No API key/i],
    ['model-unavailable', /model.*not found|no models|unknown model|no model selected/i],
    ['recorder-failed', /AgentRGB recorder disabled/],
    ['extension-load-failed', /failed to load extension|cannot find module/i],
  ]) if (pattern.test(text)) diagnostics.add(category);
});
let timedOut = false;
const timer = setTimeout(() => { timedOut = true; child.kill(); }, 90000);
const outcome = await new Promise(resolve => {
  child.on('error', () => resolve({ launchFailed: true }));
  child.on('close', (exitCode, signal) => resolve({ exitCode, signal }));
});
clearTimeout(timer);
const summary = { scenario, mode, ...outcome, timedOut, diagnostics: [...diagnostics], rawOutputSaved: false };
if (mode === 'json') {
  summary.wireIncomplete = wireInvalid || wireBuffer.trim().length > 0;
  await writeFile(join(result, 'wire-lifecycle.jsonl'), wireRows.map(row => JSON.stringify(row) + '\n').join(''));
}
await writeFile(join(result, 'process.json'), JSON.stringify(summary, null, 2) + '\n');
console.log(JSON.stringify(summary));
process.exitCode = timedOut || outcome.launchFailed ? 1 : (outcome.exitCode ?? 1);
