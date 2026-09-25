import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';
import { createServer } from 'node:http';
import { performance } from 'node:perf_hooks';
import extension from '../integrations/pi/agentrgb.ts';
import { createCoreSession, spawnCore, probeHealth, startupTimeoutMs, readyLine } from '../integrations/pi/core.ts';

function fixture(answers = [false, true], props = {}) {
  let clock = 0, launches = 0, stops = 0, probes = 0;
  const notifications = [];
  const child = { ready: true, exited: false, missing: false,
    stop: async () => { if (!child.exited) stops++; child.exited = true; }, ...props };
  const options = {
    health: async () => { probes++; return answers.length > 1 ? answers.shift() : answers[0]; },
    launch: () => { launches++; return child; },
    wait: async ms => { clock += ms; }, now: () => clock,
  };
  const ctx = { hasUI: true, ui: { notify: text => notifications.push(text) } };
  return { child, options, ctx, notifications,
    get launches() { return launches; }, get stops() { return stops; },
    get probes() { return probes; }, get clock() { return clock; } };
}

test('manifest: package resource, prerelease, peer only, published files', async () => {
  const manifest = JSON.parse(await readFile(new URL('../integrations/pi/package.json', import.meta.url)));
  assert.equal(manifest.name, 'agentrgb-pi');
  assert.match(manifest.version, /-/);
  assert.ok(manifest.keywords.includes('pi-package'));
  assert.deepEqual(manifest.pi.extensions, ['./agentrgb.ts']);
  assert.equal(manifest.peerDependencies['@earendil-works/pi-coding-agent'], '*');
  assert.equal(manifest.dependencies, undefined);
  for (const file of manifest.files) await readFile(new URL(`../integrations/pi/${file}`, import.meta.url));
});

test('factory and events before session_start do not launch resources or read payloads', async () => {
  const handlers = new Map();
  extension({ on: (name, fn) => handlers.set(name, fn) });
  const poison = new Proxy({}, { get() { throw new Error('private data read'); } });
  for (const name of ['agent_start', 'agent_end', 'agent_settled', 'ui_prompt_start', 'ui_prompt_end']) {
    await handlers.get(name)(poison, poison);
  }
  await handlers.get('session_shutdown')();
});

test('existing Core is external and never spawned/stopped; repeated start is idempotent', async () => {
  const f = fixture([true]);
  const core = createCoreSession(f.options);
  await Promise.all([core.start(f.ctx), core.start(f.ctx)]);
  assert.equal(core.connected, true);
  assert.equal(core.ownsCore, false);
  assert.equal(f.launches, 0);
  assert.equal(f.probes, 1);
  await core.shutdown(); await core.shutdown();
  assert.equal(f.stops, 0);
});

test('successful spawn owns Core; shutdown stops only once and disables delivery', async () => {
  const f = fixture();
  const core = createCoreSession(f.options);
  await core.start(f.ctx);
  assert.equal(core.connected, true);
  assert.equal(core.ownsCore, true);
  assert.equal(f.launches, 1);
  await Promise.all([core.shutdown(), core.shutdown()]);
  assert.equal(core.connected, false);
  assert.equal(core.ownsCore, false);
  assert.equal(f.stops, 1);
  await core.start(f.ctx);
  assert.equal(f.launches, 1);
});

test('health timeout has a total bound; child cleaned up and no restart', async () => {
  const f = fixture([false]);
  const core = createCoreSession(f.options);
  await core.start(f.ctx);
  assert.equal(f.clock, startupTimeoutMs);
  assert.equal(f.stops, 1);
  assert.equal(core.connected, false);
  assert.equal(core.ownsCore, false);
  await core.start(f.ctx); await core.shutdown();
  assert.equal(f.launches, 1);
  assert.equal(f.notifications.length, 1);
});

test('command not found reports once and never propagates an error into Pi', async () => {
  for (const synchronous of [false, true]) {
    const f = fixture([false], { ready: false, exited: true, missing: true });
    if (synchronous) f.options.launch = () => { throw Object.assign(new Error('PRIVATE'), { code: 'ENOENT' }); };
    const core = createCoreSession(f.options);
    await core.start(f.ctx); await core.start(f.ctx); await core.shutdown();
    assert.equal(core.connected, false);
    assert.deepEqual(f.notifications, ['AgentRGB Core not found. Install AgentRGB first.']);
  }
});

test('port race: failed child plus delayed healthy external Core is not owned', async () => {
  const f = fixture([false, false, true], { ready: false, exited: true });
  const core = createCoreSession(f.options);
  await core.start(f.ctx);
  assert.equal(core.connected, true);
  assert.equal(core.ownsCore, false);
  await core.shutdown();
  assert.equal(f.stops, 0);
});

test('healthy port without child readiness never grants ownership', async () => {
  const f = fixture([false, true], { ready: false });
  const core = createCoreSession(f.options);
  await core.start(f.ctx);
  assert.equal(core.connected, false);
  assert.equal(core.ownsCore, false);
  assert.equal(f.stops, 1);
});

test('shutdown during startup cancels readiness and cleans up the launched child', async () => {
  const f = fixture([false]);
  let release, entered;
  const reached = new Promise(resolve => { entered = resolve; });
  f.options.wait = () => { entered(); return new Promise(resolve => { release = resolve; }); };
  const core = createCoreSession(f.options);
  const starting = core.start(f.ctx);
  await reached;
  const stopping = core.shutdown();
  release();
  await Promise.all([starting, stopping]);
  assert.equal(f.stops, 1);
  assert.equal(core.connected, false);
  assert.equal(f.notifications.length, 0);
});

test('shutdown during first health probe prevents spawning', async () => {
  const f = fixture();
  let release;
  f.options.health = () => new Promise(resolve => { release = resolve; });
  const core = createCoreSession(f.options);
  const starting = core.start(f.ctx);
  const stopping = core.shutdown();
  release(false);
  await Promise.all([starting, stopping]);
  assert.equal(f.launches, 0);
});

test('invalid port, failing health, notification, and cleanup cannot break Pi', async () => {
  for (const options of [{ port: 0 }, { health: async () => { throw new Error('PRIVATE'); } },
    { launch: () => { throw new Error('PRIVATE'); } }]) {
    const f = fixture([false]);
    const core = createCoreSession({ ...f.options, ...options });
    await core.start({ hasUI: true, ui: { notify() { throw new Error(); } } });
    await core.shutdown();
    assert.equal(core.connected, false);
  }
});

test('owned child exiting disables lifecycle delivery without restart', async () => {
  const f = fixture();
  const core = createCoreSession(f.options);
  await core.start(f.ctx);
  f.child.exited = true;
  assert.equal(core.connected, false);
  assert.equal(core.ownsCore, false);
  await core.start(f.ctx); await core.shutdown();
  assert.equal(f.launches, 1);
});

test('spawn uses CLI without shell/TUI output; CRLF readiness and EOF shutdown', async () => {
  const child = new EventEmitter();
  child.stdin = new PassThrough(); child.stdout = new PassThrough();
  child.unref = () => {};
  child.stdin.on('finish', () => { child.emit('exit', 0); child.emit('close', 0); });
  let calls = 0;
  const state = spawnCore((command, args, options) => {
    calls++;
    assert.equal(command, 'agentrgb');
    assert.deepEqual(args, ['start', '--output', 'aula-f75']);
    assert.equal(options.shell, false);
    assert.equal(options.windowsHide, true);
    assert.deepEqual(options.stdio, ['pipe', 'pipe', 'ignore']);
    assert.equal(options.env.AGENTRGB_PARENT_STDIO, '1');
    return child;
  });
  child.stdout.write('AGENTRGB_'); child.stdout.write('READY\r\n');
  assert.equal(state.ready, true);
  await Promise.all([state.stop(), state.stop()]);
  assert.equal(state.exited, true);
  assert.equal(calls, 1);
});

test('child spawn error is observed and cleaned up without unhandled rejection', async () => {
  const child = new EventEmitter(); child.unref = () => {};
  const state = spawnCore(() => child);
  child.emit('error', Object.assign(new Error('PRIVATE'), { code: 'ENOENT' }));
  assert.equal(state.missing, true);
  await state.stop();
});

test('unresponsive owned child gets bounded fallback termination, not a port-based kill', async () => {
  const child = new EventEmitter();
  child.stdin = new PassThrough(); child.stdout = new PassThrough(); child.pid = 12345;
  child.unref = () => {};
  let killed = 0;
  const exit = () => { killed++; child.emit('exit', 1); child.emit('close', 1); };
  child.kill = signal => { assert.equal(signal, 'SIGKILL'); exit(); };
  const state = spawnCore((command, args, options) => {
    if (command === 'agentrgb') return child;
    assert.equal(command, 'taskkill');
    assert.deepEqual(args, ['/PID', '12345', '/T', '/F']);
    assert.equal(options.shell, false);
    exit();
    const killer = new EventEmitter(); killer.unref = () => {};
    return killer;
  });
  const began = performance.now();
  await state.stop();
  assert.equal(killed, 1);
  assert.ok(performance.now() - began < 4000);
});

test('health validates service and bounds slow/large/invalid responses', async () => {
  for (const mode of ['ok', 'foreign', 'large', 'invalid', 'hang']) {
    const server = createServer((_req, res) => {
      if (mode === 'hang') return;
      res.end(mode === 'ok' ? '{"status":"ok","service":"agentrgb"}'
        : mode === 'foreign' ? '{"status":"ok"}' : mode === 'large' ? 'x'.repeat(1025) : 'invalid');
    });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    try {
      const started = performance.now();
      assert.equal(await probeHealth(server.address().port, 100), mode === 'ok');
      assert.ok(performance.now() - started < 500);
    } finally { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
  }
});
