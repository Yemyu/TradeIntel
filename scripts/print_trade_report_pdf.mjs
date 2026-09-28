#!/usr/bin/env node
// Print an existing local trade report in an isolated headless Edge profile.
// This reads saved report state only; it never starts a model task or changes review state.
import { spawn } from 'node:child_process';
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

const [reportId, outputPath] = process.argv.slice(2);
const baseUrl = process.env.TRADEINTEL_PRINT_BASE_URL || 'http://127.0.0.1:8765';
if (!/^[a-f0-9]{32}$/.test(reportId || '') || !outputPath) {
  console.error('Usage: node scripts/print_trade_report_pdf.mjs REPORT_ID OUTPUT.pdf');
  process.exit(2);
}
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(baseUrl)) throw new Error('Only a localhost report service is allowed');

const edgePath = '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge';
const profile = await mkdtemp(join(tmpdir(), 'tradeintel-print-'));
const browser = spawn(edgePath, [
  '--headless=new', '--no-first-run', '--no-default-browser-check',
  '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank',
], { stdio: ['ignore', 'pipe', 'pipe'] });
let debugUrl = '';
let browserLog = '';
for (const stream of [browser.stdout, browser.stderr]) {
  stream.on('data', chunk => {
    const line = chunk.toString();
    browserLog += line;
    const match = line.match(/DevTools listening on (ws:\/\/[^\s]+)/);
    if (match) debugUrl = match[1];
  });
}

async function waitFor(predicate, label, timeoutMs = 15000) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    const result = await predicate();
    if (result) return result;
    await new Promise(ok => setTimeout(ok, 100));
  }
  throw new Error(`Timed out waiting for ${label}`);
}

let socket;
try {
  await waitFor(() => debugUrl, 'Edge DevTools', 15000);
  const browserEndpoint = debugUrl.replace('ws://', 'http://').replace(/\/devtools\/browser\/.*$/, '');
  const tabs = await (await fetch(`${browserEndpoint}/json`)).json();
  const page = tabs.find(tab => tab.type === 'page');
  if (!page) throw new Error('No Edge page target');
  socket = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((ok, fail) => { socket.addEventListener('open', ok, { once: true }); socket.addEventListener('error', fail, { once: true }); });
  let sequence = 0;
  const pending = new Map();
  socket.addEventListener('message', event => {
    const data = JSON.parse(event.data);
    if (!data.id || !pending.has(data.id)) return;
    const { ok, fail } = pending.get(data.id);
    pending.delete(data.id);
    data.error ? fail(new Error(data.error.message)) : ok(data.result);
  });
  function call(method, params = {}) {
    const id = ++sequence;
    return new Promise((ok, fail) => {
      pending.set(id, { ok, fail });
      socket.send(JSON.stringify({ id, method, params }));
    });
  }
  async function evaluate(expression) {
    const result = await call('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
    return result.result.value;
  }

  await call('Page.enable');
  await call('Runtime.enable');
  await call('Page.navigate', { url: `${baseUrl}/preview/#report` });
  await waitFor(() => evaluate('document.readyState === "complete"'), 'page load');
  await evaluate(`localStorage.setItem('tradeintel_last_report_type','trade'); localStorage.setItem('tradeintel_live_trade_report_id',${JSON.stringify(reportId)}); true`);
  await call('Page.reload', { ignoreCache: true });
  const title = await waitFor(() => evaluate(`document.querySelector('.live-result > h1')?.textContent?.trim() || ''`), 'saved report', 20000);
  const stats = await evaluate(`({title: document.querySelector('.live-result > h1')?.textContent?.trim(), sections: document.querySelectorAll('.live-section').length, closedDetails: document.querySelectorAll('.live-result details:not([open])').length})`);
  if (stats.sections < 2) throw new Error(`Report not fully rendered: ${JSON.stringify(stats)}`);
  const pdf = await call('Page.printToPDF', { printBackground: true, preferCSSPageSize: true, landscape: false });
  const path = resolve(outputPath);
  await mkdir(resolve(path, '..'), { recursive: true });
  await writeFile(path, Buffer.from(pdf.data, 'base64'));
  console.log(JSON.stringify({ path, ...stats, bytes: Buffer.from(pdf.data, 'base64').length }));
} catch (error) {
  console.error(error.message);
  if (!debugUrl) console.error(browserLog.slice(-1000));
  process.exitCode = 1;
} finally {
  socket?.close();
  browser.kill();
  await new Promise(ok => {
    if (browser.exitCode !== null) return ok();
    browser.once('exit', ok);
    setTimeout(ok, 2000);
  });
  await rm(profile, { recursive: true, force: true });
}
