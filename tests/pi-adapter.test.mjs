import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { createServer as createTcpServer } from 'node:net';
import { performance } from 'node:perf_hooks';
import extension, { createAdapter, createDelivery, deliveryTimeoutMs } from '../integrations/pi/agentrgb.ts';

const ctx = { sessionManager: { getSessionId: () => 'test-session' } };
function fixture() {
  const rows = [];
  const handle = createAdapter(row => { rows.push(row); });
  const fire = (type, event = {}) => handle(type, event, ctx);
  return { rows, fire };
}
const end = reason => ({ messages: [{ role: 'assistant', stopReason: reason }] });

test('logical run UUID survives repeated starts, changes after settled', () => {
  const { rows, fire } = fixture();
  fire('agent_start'); fire('agent_start');
  assert.equal(rows.length, 1);
  assert.match(rows[0].run_id, /^[a-f0-9-]{36}$/);
  assert.notEqual(rows[0].run_id, ctx.sessionManager.getSessionId());
  fire('agent_settled'); fire('agent_start');
  assert.notEqual(rows[0].run_id, rows[2].run_id);
  assert.equal(rows[0].source_instance_id, rows[2].source_instance_id);
  assert.equal(new Set(rows.map(x => x.event_id)).size, 3);
  const other = fixture(); other.fire('agent_start');
  assert.notEqual(rows[0].source_instance_id, other.rows[0].source_instance_id);
});

test('waiting only inside run, balanced nested prompts, late end ignored', () => {
  const { rows, fire } = fixture();
  fire('ui_prompt_start'); fire('ui_prompt_end'); fire('ui_prompt_end');
  assert.equal(rows.length, 0);
  fire('agent_start'); fire('ui_prompt_end');
  fire('ui_prompt_start'); fire('ui_prompt_start'); fire('ui_prompt_end');
  assert.equal(rows.at(-1).kind, 'run_waiting');
  fire('ui_prompt_end'); fire('agent_settled'); fire('ui_prompt_end');
  assert.deepEqual(rows.map(x => x.kind), ['run_started', 'run_waiting', 'run_resumed', 'run_ended']);
});

test('only final assistant stop followed by settled produces completed', () => {
  for (const reason of ['stop', 'aborted', 'error', 'unknown', undefined, 'length', 'toolUse', 'pending', 'deferred']) {
    const { rows, fire } = fixture();
    fire('agent_start');
    fire('agent_end', { messages: [{ role: 'assistant', stopReason: 'stop' }, ...end(reason).messages, { role: 'toolResult' }] });
    assert.equal(rows.length, 1);
    fire('agent_settled');
    assert.equal(rows.at(-1).metadata.outcome, reason === 'stop' ? 'completed' : 'unknown');
  }
});

test('new low-level start and each agent_end discard previous candidate', () => {
  for (const suffix of ['restart', 'empty', 'missing', 'unknown']) {
    const { rows, fire } = fixture();
    fire('agent_start'); fire('agent_end', end('stop'));
    if (suffix === 'restart') fire('agent_start');
    else fire('agent_end', suffix === 'empty' ? { messages: [] } : suffix === 'missing' ? {} : end('error'));
    fire('agent_settled');
    assert.equal(rows.at(-1).metadata.outcome, 'unknown');
  }
});

test('private getters are never read or serialized', () => {
  let reads = 0;
  const privateFields = ['content', 'thinking', 'errorMessage', 'prompt', 'response', 'arguments', 'toolResults', 'fileName', 'systemPrompt', 'toJSON'];
  const message = { role: 'assistant', stopReason: 'stop' };
  const event = { messages: [message], privateSentinel: 'PRIVATE_SENTINEL' };
  for (const object of [message, event, ctx]) {
    for (const key of privateFields) Object.defineProperty(object, key, {
      configurable: true, get() { reads++; throw new Error('PRIVATE_SENTINEL'); },
    });
  }
  const { rows, fire } = fixture();
  fire('agent_start', event); fire('ui_prompt_start', event); fire('ui_prompt_end', event);
  fire('agent_end', event); fire('agent_settled', event);
  assert.equal(reads, 0);
  assert.equal(JSON.stringify(rows).includes('PRIVATE_SENTINEL'), false);
  for (const row of rows) assert.deepEqual(Object.keys(row).sort(), [
    'schema_version', 'source', 'source_instance_id', 'session_id', 'run_id', 'event_id', 'kind', 'timestamp', 'metadata',
  ].sort());
});

test('failed metadata read clears candidate and failed sender cannot escape', async () => {
  const { rows, fire } = fixture();
  fire('agent_start'); fire('agent_end', end('stop'));
  fire('agent_end', { get messages() { throw new Error('fixture'); } });
  fire('agent_settled');
  assert.equal(rows.at(-1).metadata.outcome, 'unknown');
  for (const sender of [() => { throw new Error('sync'); }, async () => { throw new Error('async'); }]) {
    const handle = createAdapter(sender);
    await assert.doesNotReject(async () => handle('agent_start', {}, ctx));
    await assert.doesNotReject(async () => handle('agent_settled', {}, ctx));
  }
});

async function listening(server, fn) {
  const sockets = new Set();
  server.on('connection', socket => {
    sockets.add(socket);
    socket.on('close', () => sockets.delete(socket));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try { await fn(server.address().port); }
  finally {
    for (const socket of sockets) socket.destroy();
    await new Promise(resolve => server.close(resolve));
  }
}

test('real delivery ordered and contains only normalized JSON', async () => {
  const received = [];
  await listening(createServer((req, res) => {
    let body = '';
    req.on('data', chunk => body += chunk);
    req.on('end', () => { received.push(JSON.parse(body)); res.writeHead(200).end('{}'); });
  }), async port => {
    const handle = createAdapter(createDelivery(port));
    await Promise.all(['agent_start', 'ui_prompt_start', 'ui_prompt_end', 'agent_settled'].map(t => handle(t, {}, ctx)));
    assert.deepEqual(received.map(e => e.kind), ['run_started', 'run_waiting', 'run_resumed', 'run_ended']);
  });
});

test('down, hanging, error and invalid response do not break handlers', async () => {
  let closedPort;
  await listening(createServer(), async port => { closedPort = port; });
  const row = fixture(); row.fire('agent_start');
  await createDelivery(closedPort)(row.rows[0]);
  for (const mode of ['hang', 'error', 'invalid']) {
    const server = mode === 'invalid'
      ? createTcpServer(socket => { socket.end('INVALID HTTP\r\n\r\n'); })
      : createServer((_req, res) => { if (mode === 'error') res.writeHead(500).end('invalid json'); });
    await listening(server, async port => {
      const handle = createAdapter(createDelivery(port));
      const started = performance.now();
      await handle('agent_start', {}, ctx);
      assert.ok(performance.now() - started < deliveryTimeoutMs + 120, mode);
      await handle('agent_end', end('stop'), ctx);
      await handle('agent_settled', {}, ctx);
    });
  }
});

test('extension registers lifecycle hooks only', () => {
  const names = [];
  extension({ on(type) { names.push(type); } });
  assert.deepEqual(names, ['agent_start', 'agent_end', 'agent_settled', 'ui_prompt_start', 'ui_prompt_end']);
});

test('burst against hanging Core has one deadline, no accumulated waits', async () => {
  await listening(createServer(() => {}), async port => {
    const send = createDelivery(port);
    const { rows, fire } = fixture(); fire('agent_start');
    const started = performance.now();
    await Promise.all(Array.from({ length: 100 }, () => send(rows[0])));
    assert.ok(performance.now() - started < deliveryTimeoutMs + 150);
  });
});
