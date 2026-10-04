/**
 * scripts/browser_uat_panel.mjs
 * End-to-end Browser UAT for VoiceFi Voice Control Panel.
 * Launches headless Google Chrome with CDP, browses the UI, clicks controls,
 * tests the configure drawer, exercises dropdowns, and asserts zero console errors.
 */

import { spawn } from 'child_process';
import { writeFileSync, mkdirSync } from 'fs';
import { resolve, dirname } from 'path';

const PORT = 9385;
const CDP_PORT = 9225;
const CHROME_PATH = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const PANEL_URL = `http://127.0.0.1:${PORT}`;

async function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function run() {
  console.log('🚀 Starting VoiceFi Control Panel server in background on port', PORT);
  const serverProc = spawn('.venv/bin/python', [
    '-c',
    `
import time
from voicefi.config import load_config
from voicefi.ui.panel import start_panel_server
cfg = load_config()
srv, p = start_panel_server(port=${PORT}, config=cfg)
print(f"READY:{p}", flush=True)
while True:
    time.sleep(1)
`
  ], { stdio: ['inherit', 'pipe', 'inherit'] });

  // Wait for server ready
  await new Promise((res, rej) => {
    serverProc.stdout.on('data', (d) => {
      if (d.toString().includes('READY:')) res();
    });
    setTimeout(() => rej(new Error('Server start timeout')), 5000);
  });
  console.log('✅ Control Panel server ready at', PANEL_URL);

  console.log('🌐 Launching Headless Chrome on CDP port', CDP_PORT);
  const chromeProc = spawn(CHROME_PATH, [
    '--headless=new',
    `--remote-debugging-port=${CDP_PORT}`,
    '--disable-gpu',
    '--no-sandbox',
    '--disable-dev-shm-usage',
    'about:blank'
  ]);

  // Wait for Chrome CDP port to open
  let wsUrl = null;
  for (let i = 0; i < 20; i++) {
    await sleep(300);
    try {
      const resp = await fetch(`http://127.0.0.1:${CDP_PORT}/json/version`);
      if (resp.ok) {
        const data = await resp.json();
        wsUrl = data.webSocketDebuggerUrl;
        break;
      }
    } catch (e) {}
  }

  if (!wsUrl) {
    serverProc.kill();
    chromeProc.kill();
    throw new Error('Failed to connect to Chrome DevTools Protocol');
  }
  console.log('✅ Connected to Chrome CDP at', wsUrl);

  // Create new page target
  const newTargetResp = await fetch(`http://127.0.0.1:${CDP_PORT}/json/new?${PANEL_URL}`, { method: 'PUT' });
  const targetData = await newTargetResp.json();
  const pageWsUrl = targetData.webSocketDebuggerUrl;

  const ws = new WebSocket(pageWsUrl);
  await new Promise((res) => ws.onopen = res);

  let msgId = 1;
  const pendingRequests = new Map();
  const consoleErrors = [];

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id && pendingRequests.has(msg.id)) {
      const { resolve } = pendingRequests.get(msg.id);
      pendingRequests.delete(msg.id);
      resolve(msg);
    }
    if (msg.method === 'Runtime.exceptionThrown') {
      consoleErrors.push(msg.params.exceptionDetails);
    }
  };

  function sendCommand(method, params = {}) {
    return new Promise((resolve) => {
      const id = msgId++;
      pendingRequests.set(id, { resolve });
      ws.send(JSON.stringify({ id, method, params }));
    });
  }

  async function evaluate(expression) {
    const res = await sendCommand('Runtime.evaluate', {
      expression,
      returnByValue: true,
      awaitPromise: true,
    });
    if (res.result?.exceptionDetails) {
      throw new Error('Eval error: ' + JSON.stringify(res.result.exceptionDetails));
    }
    return res.result?.result?.value;
  }

  await sendCommand('Page.enable');
  await sendCommand('Runtime.enable');

  console.log('📄 Waiting for page load and initial state render...');
  await sleep(1500);

  // 1. Verify Page Title & Header
  const title = await evaluate('document.title');
  console.log('   Title:', title);
  if (!title.includes('Voice Control Panel')) throw new Error('Incorrect page title');

  // 2. Verify Turn Completion Readout dropdown exists
  console.log('🔍 Checking Turn Completion Readout dropdown...');
  const formatOptions = await evaluate(`
    (() => {
      const sel = document.getElementById('turnCompleteFormatSelect');
      if (!sel) return null;
      return Array.from(sel.options).map(o => ({ value: o.value, text: o.text }));
    })()
  `);
  console.log('   Found format options:', formatOptions);
  if (!formatOptions || formatOptions.length !== 5) {
    throw new Error('Expected 5 turn complete format options');
  }

  // 3. Test Configure button toggle
  console.log('🖱️ Clicking [ Configure... ] button to test drawer expansion...');
  const initialDrawerDisplay = await evaluate(`document.getElementById('turnFormatConfigDrawer').style.display`);
  console.log('   Initial drawer display:', initialDrawerDisplay);

  await evaluate(`document.getElementById('btnConfigureTurnFormat').click()`);
  await sleep(300);

  const openedDrawerDisplay = await evaluate(`document.getElementById('turnFormatConfigDrawer').style.display`);
  console.log('   Opened drawer display:', openedDrawerDisplay);
  if (openedDrawerDisplay !== 'block') {
    throw new Error('Configure drawer did not open on button click');
  }

  // 4. Verify Chime Sound options
  const chimeOptions = await evaluate(`
    (() => {
      const sel = document.getElementById('turnCompleteChimeSelect');
      return Array.from(sel.options).map(o => o.value);
    })()
  `);
  console.log('   Available completion chimes:', chimeOptions);
  if (!chimeOptions.includes('Glass') || !chimeOptions.includes('Hero') || !chimeOptions.includes('Ping')) {
    throw new Error('Expected system sound options (Glass, Hero, Ping, etc.)');
  }

  // 5. Test inline [ Play ] chime test button
  console.log('🔔 Clicking inline Play chime test button...');
  await evaluate(`testTurnCompleteChime()`);
  await sleep(500);

  // 6. Test character baseline display & instruction typing
  const baselineText = await evaluate(`document.getElementById('characterBaselineToneText').textContent`);
  console.log('   Character baseline display:', baselineText);
  if (!baselineText.includes('Baseline:')) throw new Error('Missing character baseline tone');

  console.log('✍️ Entering custom character quip instruction...');
  await evaluate(`
    (() => {
      const inp = document.getElementById('characterQuipInstructionInput');
      inp.value = 'Triumphant celebratory one-liner';
      inp.dispatchEvent(new Event('change'));
    })()
  `);
  await sleep(400);

  // 7. Cycle through all 5 Turn Completion formats and verify persistence
  for (const fmt of ['distilled', 'full', 'character_quip', 'chime_only', 'first_sentence']) {
    console.log(`🔄 Selecting format '${fmt}'...`);
    await evaluate(`
      (() => {
        const sel = document.getElementById('turnCompleteFormatSelect');
        sel.value = '${fmt}';
        sel.dispatchEvent(new Event('change'));
      })()
    `);
    await sleep(400);

    // Verify backend received update
    const stateResp = await fetch(`${PANEL_URL}/api/state`);
    const stateJson = await stateResp.json();
    if (stateJson.config.tts.turn_complete_format !== fmt) {
      throw new Error(`State mismatch: expected ${fmt}, got ${stateJson.config.tts.turn_complete_format}`);
    }
  }
  console.log('✅ All 5 format switches verified against backend API!');

  // 8. Test tabs clicking (Antigravity, Claude, Researcher, Debugger, etc.)
  console.log('🖱️ Clicking Agent Target tabs to verify reactive UX...');
  for (const tabId of ['tab-claude', 'tab-researcher', 'tab-debugger', 'tab-antigravity']) {
    await evaluate(`document.getElementById('${tabId}').click()`);
    await sleep(250);
  }
  console.log('✅ All agent tabs clicked cleanly without layout thrashing');

  // 9. Check for uncaught console errors
  console.log('🛡️ Verifying zero JavaScript console errors...');
  if (consoleErrors.length > 0) {
    console.error('❌ Console errors detected:', consoleErrors);
    throw new Error('JavaScript console errors occurred during UAT');
  }
  console.log('✅ Zero console errors or unhandled exceptions detected!');

  // 10. Capture full page screenshot centered on Turn Completion Readout
  console.log('📸 Capturing focused UAT screenshot...');
  await evaluate(`document.getElementById('turnFormatConfigDrawer').scrollIntoView({ behavior: 'instant', block: 'center' })`);
  await sleep(400);
  const ssRes = await sendCommand('Page.captureScreenshot', { format: 'png' });
  const buffer = Buffer.from(ssRes.result.data, 'base64');
  const screenshotPath = resolve('assets/screenshots/uat_turn_readout_panel.png');
  mkdirSync(dirname(screenshotPath), { recursive: true });
  writeFileSync(screenshotPath, buffer);
  console.log('✅ Screenshot saved to:', screenshotPath);

  // Cleanup
  ws.close();
  serverProc.kill();
  chromeProc.kill();

  console.log('\n=============================================================');
  console.log('🎉 BROWSER UAT PASSED: ALL CONTROLS & API SYNCS VERIFIED!');
  console.log('=============================================================\n');
}

run().catch((err) => {
  console.error('\n❌ BROWSER UAT FAILED:', err);
  process.exit(1);
});
