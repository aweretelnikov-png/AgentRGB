import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import recorder, { events, project } from './pi-event-recorder.ts';

const ctx = { mode: 'tui', isIdle: () => false, hasPendingMessages: () => false,
  sessionManager: { getSessionId: () => 'test-session-id' } };

test('privacy: inaccessible optional message metadata does not break projection', () => {
  for (const type of events) {
    const event = { type, source: 'interactive', kind: 'confirm', toolName: 'read', toolCallId: 'id', isError: false };
    for (const key of ['text', 'prompt', 'systemPrompt', 'images', 'messages', 'message', 'toolResults', 'input', 'content', 'title', 'errorMessage', 'compactionEntry', 'preparation', 'branchEntries']) {
      Object.defineProperty(event, key, { get() { throw new Error('Forbidden payload read'); } });
    }
    const row = project(event, ctx, 1);
    assert.equal(row.type, type);
    assert.equal(JSON.stringify(row).includes('Forbidden'), false);
  }
  assert.doesNotThrow(() => project({ type: 'agent_end' }, {}, 1));
});

test('ordered writes and shutdown flush; no handler decisions', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'pi-recorder-'));
  const previous = process.env.AGENTRGB_PI_RESULTS;
  try {
    process.env.AGENTRGB_PI_RESULTS = dir;
    const handlers = new Map();
    recorder({ on: (type, callback) => handlers.set(type, callback) });
    for (const type of ['agent_start', 'tool_call', 'agent_end', 'agent_settled']) {
      assert.equal(handlers.get(type)({ type }, ctx), undefined);
    }
    await handlers.get('session_shutdown')({ type: 'session_shutdown' }, ctx);
    const rows = (await readFile(join(dir, (await readdir(dir))[0]), 'utf8')).trim().split('\n').map(JSON.parse);
    assert.deepEqual(rows.map(x => x.sequence), [1, 2, 3, 4, 5]);
    assert.deepEqual(rows.map(x => x.type), ['agent_start', 'tool_call', 'agent_end', 'agent_settled', 'session_shutdown']);
  } finally {
    if (previous === undefined) delete process.env.AGENTRGB_PI_RESULTS; else process.env.AGENTRGB_PI_RESULTS = previous;
    await rm(dir, { recursive: true });
  }
});

test('filesystem failure does not reject or stop the source', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'pi-recorder-'));
  const previous = process.env.AGENTRGB_PI_RESULTS;
  try {
    const file = join(dir, 'not-a-directory');
    await writeFile(file, 'fixture');
    process.env.AGENTRGB_PI_RESULTS = file;
    const handlers = new Map();
    recorder({ on: (type, callback) => handlers.set(type, callback) });
    assert.equal(handlers.get('agent_start')({ type: 'agent_start' }, ctx), undefined);
    await assert.doesNotReject(async () => handlers.get('session_shutdown')({ type: 'session_shutdown' }, ctx));
  } finally {
    if (previous === undefined) delete process.env.AGENTRGB_PI_RESULTS; else process.env.AGENTRGB_PI_RESULTS = previous;
    await rm(dir, { recursive: true });
  }
});

test('JSONL saves only stopReason from messages, never their payload', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'pi-recorder-privacy-'));
  const previous = process.env.AGENTRGB_PI_RESULTS;
  let forbiddenReads = 0;
  const assistant = (stopReason) => {
    const message = { role: 'assistant', stopReason };
    for (const key of ['content', 'thinking', 'text', 'errorMessage', 'toJSON']) {
      Object.defineProperty(message, key, { enumerable: true, get() {
        forbiddenReads++;
        throw new Error('PRIVATE_PAYLOAD_SENTINEL');
      } });
    }
    return message;
  };
  try {
    process.env.AGENTRGB_PI_RESULTS = dir;
    const handlers = new Map();
    recorder({ on: (type, callback) => handlers.set(type, callback) });
    handlers.get('turn_end')({ type: 'turn_end', message: assistant('toolUse'), toolResults: ['PRIVATE_TOOL_RESULT'] }, ctx);
    handlers.get('turn_end')({ type: 'turn_end', message: assistant('aborted') }, ctx);
    handlers.get('agent_end')({ type: 'agent_end', messages: [
      { role: 'user', content: 'PRIVATE_USER_REQUEST' },
      assistant('toolUse'), assistant('aborted'),
      { role: 'toolResult', content: 'PRIVATE_TOOL_RESULT' },
    ] }, ctx);
    await handlers.get('session_shutdown')({ type: 'session_shutdown' }, ctx);
    const raw = await readFile(join(dir, (await readdir(dir))[0]), 'utf8');
    const rows = raw.trim().split('\n').map(JSON.parse);
    assert.deepEqual(rows.slice(0, 3).map(row => row.stopReason), ['toolUse', 'aborted', 'aborted']);
    assert.equal(forbiddenReads, 0);
    for (const text of ['PRIVATE_', 'content', 'thinking', 'messages', 'role', 'errorMessage', 'toolResults']) {
      assert.equal(raw.includes(text), false, text);
    }
  } finally {
    if (previous === undefined) delete process.env.AGENTRGB_PI_RESULTS; else process.env.AGENTRGB_PI_RESULTS = previous;
    await rm(dir, { recursive: true });
  }
});

test('missing or unknown last stopReason never falls back to an earlier normal outcome', () => {
  for (const stopReason of [undefined, 'PRIVATE_UNKNOWN_VALUE']) {
    const row = project({ type: 'agent_end', messages: [
      { role: 'assistant', stopReason: 'stop' }, { role: 'assistant', stopReason },
    ] }, ctx, 1);
    assert.equal(row.stopReason, undefined);
    assert.equal(JSON.stringify(row).includes('PRIVATE_'), false);
  }
  assert.equal(project({ type: 'agent_end', messages: [{ role: 'user', stopReason: 'stop' }] }, ctx, 1).stopReason, undefined);
});
