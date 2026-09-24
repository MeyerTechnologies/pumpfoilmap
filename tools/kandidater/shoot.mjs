// Tager skærmbilleder af gennemgangssiden med headless Chrome via DevTools-protokollen.
// Venter til siden sætter window.__ready (alle luftfoto-fliser indlæst).
//   node shoot.mjs jobs.json      jobs.json = [{ "url": "...", "out": "fil.png" }, ...]
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const PARALLEL = 4;
const TIMEOUT_MS = 45000;
const jobs = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'pfm-chrome-'));

const chrome = spawn(CHROME, [
  '--headless=new', '--disable-gpu', '--hide-scrollbars', '--no-first-run', '--no-default-browser-check',
  '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank',
], { stdio: ['ignore', 'ignore', 'pipe'] });

const wsUrl = await new Promise((resolve, reject) => {
  let buf = '';
  chrome.stderr.on('data', (d) => {
    buf += d;
    const m = buf.match(/DevTools listening on (ws:\/\/\S+)/);
    if (m) resolve(m[1]);
  });
  setTimeout(() => reject(new Error('Chrome startede ikke')), 15000);
});

const ws = new WebSocket(wsUrl);
await new Promise((r) => ws.addEventListener('open', r, { once: true }));
let nextId = 1;
const pending = new Map();
ws.addEventListener('message', (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
  }
});
const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
  const id = nextId++;
  pending.set(id, { resolve, reject });
  ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
});
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function shoot(job) {
  const { targetId } = await send('Target.createTarget', { url: 'about:blank' });
  const { sessionId } = await send('Target.attachToTarget', { targetId, flatten: true });
  try {
    await send('Emulation.setDeviceMetricsOverride', { width: 1200, height: 700, deviceScaleFactor: 1, mobile: false }, sessionId);
    await send('Page.enable', {}, sessionId);
    await send('Page.navigate', { url: job.url }, sessionId);
    const start = Date.now();
    let ready = false;
    while (Date.now() - start < TIMEOUT_MS) {
      await sleep(400);
      const { result } = await send('Runtime.evaluate', { expression: 'window.__ready === true', returnByValue: true }, sessionId);
      if (result.value) { ready = true; break; }
    }
    await sleep(ready ? 250 : 0);
    const { data } = await send('Page.captureScreenshot', { format: 'png' }, sessionId);
    fs.writeFileSync(job.out, Buffer.from(data, 'base64'));
    console.log(`${ready ? 'ok' : 'timeout'} ${job.out}`);
  } finally {
    await send('Target.closeTarget', { targetId }).catch(() => {});
  }
}

const queue = [...jobs];
await Promise.all(Array.from({ length: Math.min(PARALLEL, queue.length) }, async () => {
  while (queue.length) {
    const job = queue.shift();
    try { await shoot(job); } catch (err) { console.log(`fejl ${job.out}: ${err.message}`); }
  }
}));
ws.close();
await new Promise((r) => { chrome.once('exit', r); chrome.kill(); setTimeout(r, 5000); });
try { fs.rmSync(profile, { recursive: true, force: true, maxRetries: 3 }); } catch {}
