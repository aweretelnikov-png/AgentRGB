// Только мост для двух тестовых клиентов. Node 24, без зависимостей и логов.
import readline from 'node:readline';
const endpoint = new URL(process.argv[2]);
if (endpoint.protocol !== 'ws:' || endpoint.hostname !== '127.0.0.1') process.exit(2);
const ws = new WebSocket(endpoint);
const pending = [];
const input = readline.createInterface({input: process.stdin});
input.on('line', line => {
  if (ws.readyState === WebSocket.OPEN) ws.send(line);
  else pending.push(line);
});
input.on('close', () => ws.close());
ws.addEventListener('open', () => { for (const line of pending.splice(0)) ws.send(line); });
ws.addEventListener('message', event => { process.stdout.write(event.data + '\n'); });
ws.addEventListener('close', () => process.exit(0));
ws.addEventListener('error', () => process.exit(1));
