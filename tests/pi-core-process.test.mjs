// Реальные дочерние Python Core; spawn harness принудительно выбирает только fake.
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { createCoreSession, spawnCore, probeHealth } from '../integrations/pi/core.ts';

async function freePort() {
  const reservation = createServer();
  await new Promise(resolve => reservation.listen(0, '127.0.0.1', resolve));
  const port = reservation.address().port;
  await new Promise(resolve => reservation.close(resolve));
  return port;
}

function fakeLaunch(port, children) {
  return () => spawnCore((command, args, options) => {
    assert.equal(command, 'agentrgb', 'fake child must exit gracefully without fallback');
    assert.deepEqual(args, ['start', '--output', 'aula-f75']);
    const child = spawn(process.env.AGENTRGB_TEST_PYTHON ?? 'python', ['-m', 'agentrgb.cli', 'start', '--output', 'fake'],
      { ...options, env: { ...options.env, AGENTRGB_PORT: String(port) } });
    children.push(child);
    return child;
  });
}

test('real fake Core handshake, HTTP readiness and EOF shutdown', async () => {
  const port = await freePort(), children = [];
  const core = createCoreSession({ port, launch: fakeLaunch(port, children) });
  try {
    await core.start({});
    assert.equal(core.connected, true);
    assert.equal(core.ownsCore, true);
    assert.equal(await probeHealth(port), true);
  } finally { await core.shutdown(); }
  assert.equal(children.length, 1);
  assert.equal(children[0].exitCode, 0);
  assert.equal(await probeHealth(port), false);
});

test('two real fake children race: exactly one owner; non-owner shutdown preserves winner', async () => {
  const port = await freePort(), children = [];
  let probes = 0, release;
  const barrier = new Promise(resolve => { release = resolve; });
  const health = async timeout => {
    if (++probes <= 2) {
      if (probes === 2) release();
      await barrier;
      return false;
    }
    return probeHealth(port, timeout);
  };
  const cores = [0, 1].map(() => createCoreSession({ port, health, launch: fakeLaunch(port, children) }));
  try {
    await Promise.all(cores.map(core => core.start({})));
    assert.ok(cores.every(core => core.connected));
    assert.equal(cores.filter(core => core.ownsCore).length, 1);
    await cores.find(core => !core.ownsCore).shutdown();
    assert.equal(await probeHealth(port), true);
  } finally { await Promise.all(cores.map(core => core.shutdown())); }
  assert.equal(children.length, 2);
  assert.ok(children.every(child => child.exitCode !== null));
  assert.equal(await probeHealth(port), false);
});
