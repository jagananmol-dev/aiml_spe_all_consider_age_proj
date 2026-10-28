#!/usr/bin/env node
/**
 * VEDA AI — Compute node agent (hosted mode)
 *
 * Runs on your own PC when the web app is hosted on Vercel with
 * COMPUTE_NODE=tunnel. It:
 *
 * 1. starts the intelligence service (127.0.0.1:8002) and the ingestion
 *    worker, both pointed at the hosted database; they are never exposed
 *    directly
 * 2. watches the `compute_node` row: as soon as a signed-in user is active
 *    on the site (wanted_at is recent), it opens a Cloudflare tunnel to the
 *    intelligence service and publishes the tunnel's address there
 * 3. closes the tunnel again once nobody has been active for
 *    TUNNEL_IDLE_MINUTES (default 15)
 *
 * Chat reaches Ollama through the intelligence service's /llm proxy, which
 * requires INTERNAL_API_KEY, so Ollama itself is never on the internet.
 *
 * Quick tunnels (the default) need no Cloudflare account; the address
 * changes each time. For a fixed address, create a named tunnel and set
 * TUNNEL_TOKEN and TUNNEL_URL.
 *
 * Run: npm run node   (reads the root .env; see DEPLOY.md)
 */
const { spawn, spawnSync } = require('child_process');
const { createRequire } = require('module');
const path = require('path');
const fs = require('fs');

const root = path.resolve(__dirname, '..');
const isWindows = process.platform === 'win32';
// The web app's dependencies include the PostgreSQL client
const postgres = createRequire(path.join(root, 'apps', 'web', 'package.json'))('postgres');

const INTELLIGENCE_PORT = 8002;
const POLL_MS = 3_000;
const SEEN_REFRESH_MS = 30_000;
const TUNNEL_READY_TIMEOUT_MS = 90_000;

/** Parse the root .env file (KEY=VALUE lines) without overriding real env vars. */
function loadRootEnv() {
  const envFile = path.join(root, '.env');
  if (!fs.existsSync(envFile)) return {};
  const values = {};
  for (const line of fs.readFileSync(envFile, 'utf8').split(/\r?\n/)) {
    const match = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/);
    if (!match) continue;
    const value = match[2].replace(/^(['"])(.*)\1$/, '$2');
    if (value !== '') values[match[1]] = value;
  }
  return values;
}

const env = { ...loadRootEnv(), ...process.env };
const databaseUrl = env.NODE_DATABASE_URL || env.DATABASE_URL;
const idleMs = (Number(env.TUNNEL_IDLE_MINUTES) || 15) * 60_000;

function fail(message) {
  console.error(`\n✖ ${message}\n`);
  process.exit(1);
}

if (!databaseUrl) fail('Set DATABASE_URL (or NODE_DATABASE_URL) to the hosted database in .env.');
if (!env.INTERNAL_API_KEY || env.INTERNAL_API_KEY.length < 16) {
  fail('Set INTERNAL_API_KEY (16+ characters, the same value as on Vercel) in .env.');
}
if (spawnSync('cloudflared', ['--version'], { stdio: 'ignore' }).status !== 0) {
  fail(
    'cloudflared is not installed. Install it with:\n' +
      '    winget install --id Cloudflare.cloudflared      (Windows)\n' +
      '    brew install cloudflared                         (macOS)\n' +
      '  then open a new terminal.'
  );
}

/** Same settings scripts/dev.js uses for local mode, against the hosted database. */
const serviceEnv = {
  ...env,
  VEDA_DATABASE_URL: databaseUrl,
  VEDA_INTELLIGENCE_URL: `http://127.0.0.1:${INTELLIGENCE_PORT}`,
  VEDA_OLLAMA_URL: (env.LLM_BASE_URL || 'http://127.0.0.1:11434').replace(/\/+$/, ''),
  VEDA_VECTOR_BACKEND: 'local',
  VEDA_GRAPH_ENABLED: 'false',
  VEDA_GRAPH_BACKEND: 'local',
  VEDA_OPENSEARCH_ENABLED: 'false',
  VEDA_MAX_CHUNK_TOKENS: env.VEDA_MAX_CHUNK_TOKENS || '3500',
  PYTHONUNBUFFERED: '1',
};

const sql = postgres(databaseUrl, { max: 1, prepare: false, connect_timeout: 10 });

// ── Python services ─────────────────────────────────
const services = [];
let shuttingDown = false;

function venvPython(serviceName) {
  const dir = path.join(root, 'services', serviceName, '.venv');
  const candidates = isWindows
    ? [path.join(dir, 'Scripts', 'python.exe')]
    : [path.join(dir, 'bin', 'python'), path.join(dir, 'bin', 'python3')];
  return candidates.find((c) => fs.existsSync(c)) || null;
}

/** Start a service and restart it if it stops, until the agent shuts down. */
function supervise(name, serviceName, args) {
  const python = venvPython(serviceName);
  if (!python) {
    fail(`No virtualenv for ${serviceName}. Run "npm run dev" once, or follow the README setup.`);
  }
  const entry = { name, child: null };
  const start = () => {
    console.log(`▶ Starting ${name}`);
    entry.child = spawn(python, args, {
      cwd: path.join(root, 'services', serviceName),
      env: serviceEnv,
      stdio: ['ignore', 'inherit', 'inherit'],
      windowsHide: true,
    });
    entry.child.on('exit', (code) => {
      if (shuttingDown) return;
      console.warn(`${name} stopped (code ${code}); restarting in 5 s`);
      setTimeout(start, 5_000);
    });
  };
  start();
  services.push(entry);
}

async function checkOllama() {
  if ((env.LLM_PROVIDER || '').toLowerCase() !== 'ollama') return;
  try {
    const res = await fetch(`${serviceEnv.VEDA_OLLAMA_URL}/api/tags`, {
      signal: AbortSignal.timeout(3000),
    });
    const { models = [] } = await res.json();
    const wanted = env.LLM_MODEL || 'llama3';
    if (!models.some((m) => m.name === wanted || m.name.startsWith(`${wanted}:`))) {
      console.warn(`Ollama has no model "${wanted}". Run: ollama pull ${wanted}`);
    }
  } catch {
    console.warn('Ollama is not running. Start the Ollama app so the chatbot can answer.');
  }
}

// ── Tunnel ──────────────────────────────────────────
let tunnel = null; // { child, url }
let opening = false;
let lastSeenWrite = 0;

async function waitUntilReachable(url) {
  const deadline = Date.now() + TUNNEL_READY_TIMEOUT_MS;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${url}/health`, { signal: AbortSignal.timeout(5000) });
      if (res.ok) return true;
    } catch {
      // DNS for a new quick tunnel takes a few seconds
    }
    await new Promise((r) => setTimeout(r, 2000));
  }
  return false;
}

function startCloudflared() {
  const named = env.TUNNEL_TOKEN && env.TUNNEL_URL;
  const args = named
    ? ['tunnel', '--no-autoupdate', 'run', '--token', env.TUNNEL_TOKEN]
    : ['tunnel', '--no-autoupdate', '--url', `http://127.0.0.1:${INTELLIGENCE_PORT}`];
  const child = spawn('cloudflared', args, { stdio: ['ignore', 'ignore', 'pipe'], windowsHide: true });

  const url = named
    ? Promise.resolve(env.TUNNEL_URL.replace(/\/+$/, ''))
    : new Promise((resolve, reject) => {
        let output = '';
        child.stderr.on('data', (data) => {
          output += data.toString();
          const match = output.match(/https:\/\/[a-z0-9-]+\.trycloudflare\.com/);
          if (match) resolve(match[0]);
        });
        child.on('exit', () => reject(new Error('cloudflared exited before giving an address')));
      });
  // Keep draining cloudflared's log so it never blocks on a full pipe
  child.stderr.resume();
  return { child, url };
}

async function openTunnel() {
  opening = true;
  try {
    console.log('● A user is active — opening the tunnel');
    const { child, url: urlPromise } = startCloudflared();
    const url = await urlPromise;
    if (!(await waitUntilReachable(url))) {
      child.kill();
      throw new Error(`the tunnel at ${url} did not answer`);
    }
    tunnel = { child, url };
    child.on('exit', () => {
      if (tunnel?.child !== child) return;
      console.warn('cloudflared stopped; the tunnel will reopen while users are active');
      tunnel = null;
      clearTunnelUrl().catch(() => {});
    });
    await sql`UPDATE compute_node SET tunnel_url = ${url}, seen_at = NOW() WHERE id = 1`;
    lastSeenWrite = Date.now();
    console.log(`✔ Tunnel open: ${url}`);
  } catch (error) {
    console.warn(`Could not open the tunnel: ${error.message}`);
  } finally {
    opening = false;
  }
}

async function clearTunnelUrl() {
  await sql`UPDATE compute_node SET tunnel_url = NULL, seen_at = NULL WHERE id = 1`;
}

async function closeTunnel(reason) {
  if (!tunnel) return;
  const { child } = tunnel;
  tunnel = null;
  console.log(`○ Closing the tunnel (${reason})`);
  await clearTunnelUrl().catch((e) => console.warn(`Could not clear the tunnel address: ${e.message}`));
  child.kill();
}

// ── Main loop ───────────────────────────────────────
async function tick() {
  const [row] = await sql`
    SELECT EXTRACT(EPOCH FROM (NOW() - wanted_at)) * 1000 AS idle_ms
    FROM compute_node WHERE id = 1
  `;
  if (!row) throw new Error('compute_node row missing: apply 006_hosted_mode.sql');
  const wanted = row.idle_ms !== null && Number(row.idle_ms) < idleMs;

  if (wanted && !tunnel && !opening) {
    await openTunnel();
  } else if (!wanted && tunnel) {
    await closeTunnel(`no activity for ${Math.round(idleMs / 60_000)} min`);
  } else if (tunnel && Date.now() - lastSeenWrite > SEEN_REFRESH_MS) {
    await sql`UPDATE compute_node SET seen_at = NOW() WHERE id = 1`;
    lastSeenWrite = Date.now();
  }
}

async function loop() {
  try {
    await tick();
  } catch (error) {
    console.warn(`Database check failed: ${error.message}`);
  }
  if (!shuttingDown) setTimeout(loop, POLL_MS);
}

async function shutdown() {
  if (shuttingDown) return;
  shuttingDown = true;
  console.log('\nStopping…');
  await closeTunnel('agent stopped');
  for (const { child } of services) child?.kill();
  await sql.end({ timeout: 5 }).catch(() => {});
  process.exit(0);
}

async function main() {
  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);

  await sql`SELECT 1 FROM compute_node LIMIT 1`.catch((error) =>
    fail(`Cannot use the hosted database: ${error.message}\n  (Did you apply 006_hosted_mode.sql?)`)
  );
  // A previous run that was killed may have left its address behind
  await clearTunnelUrl();
  await checkOllama();

  if (env.COMPUTE_NODE_START_SERVICES !== '0') {
    supervise('intelligence service', 'intelligence', [
      '-m', 'uvicorn', 'src.api:app', '--host', '127.0.0.1', '--port', String(INTELLIGENCE_PORT),
    ]);
    supervise('ingestion worker', 'ingestion', ['-m', 'src.workers.local_worker']);
  }

  console.log(
    `Compute node ready. The tunnel opens when someone uses the site and closes after ` +
      `${Math.round(idleMs / 60_000)} min without activity. Ctrl+C to stop.`
  );
  loop();
}

main();
