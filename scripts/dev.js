#!/usr/bin/env node
const { spawn, spawnSync } = require('child_process');
const path = require('path');
const fs = require('fs');

const root = path.resolve(__dirname, '..');
const isWindows = process.platform === 'win32';
const pythonCmd = isWindows ? 'py' : 'python3';
const pnpmCmd = isWindows ? 'pnpm.cmd' : 'pnpm';
const webPort = process.env.WEB_PORT || '3000';

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

/**
 * Environment shared by all child processes. In local mode it switches every
 * service to the no-Docker pipeline: disk storage, the polling local worker,
 * and embeddings stored in plain PostgreSQL.
 */
function buildServiceEnv(mode) {
  const fileEnv = loadRootEnv();
  const env = { ...fileEnv, ...process.env };
  const shared = {
    VEDA_DATABASE_URL: env.VEDA_DATABASE_URL || env.DATABASE_URL,
    INTERNAL_API_KEY: env.INTERNAL_API_KEY || '',
    VEDA_INTELLIGENCE_URL: 'http://127.0.0.1:8002',
    INTELLIGENCE_SERVICE_URL: 'http://127.0.0.1:8002',
  };
  if (mode === 'local') {
    Object.assign(shared, {
      STORAGE_BACKEND: 'local',
      LOCAL_STORAGE_DIR: env.LOCAL_STORAGE_DIR || path.join(root, '.data', 'uploads'),
      VEDA_VECTOR_BACKEND: 'local',
      VEDA_GRAPH_ENABLED: 'false',
      // Knowledge graph in plain PostgreSQL (needs 003_local_graph.sql applied)
      VEDA_GRAPH_BACKEND: 'local',
      VEDA_OPENSEARCH_ENABLED: 'false',
      // Keep retrieved context within a small local model's window
      VEDA_MAX_CHUNK_TOKENS: env.VEDA_MAX_CHUNK_TOKENS || '3500',
    });
  }
  return { ...env, ...shared };
}

async function checkOllama(env) {
  if ((env.LLM_PROVIDER || '').toLowerCase() !== 'ollama') return;
  const baseUrl = (env.LLM_BASE_URL || 'http://localhost:11434').replace(/\/+$/, '');
  try {
    const res = await fetch(`${baseUrl}/api/tags`, { signal: AbortSignal.timeout(3000) });
    const { models = [] } = await res.json();
    const names = models.map((m) => m.name);
    const wanted = env.LLM_MODEL || '';
    if (!names.some((n) => n === wanted || n.startsWith(`${wanted}:`))) {
      console.warn(`Ollama is running but model "${wanted}" is not pulled. Run: ollama pull ${wanted}`);
    } else {
      console.log(`Ollama ready with model "${wanted}". Loading it into memory...`);
      // An empty prompt makes Ollama load the model without generating, so
      // the first chat answer does not wait for the model to load. The
      // context size must match the chat's (LLM_NUM_CTX), or Ollama reloads
      // the model on the first question. Not awaited.
      fetch(`${baseUrl}/api/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: wanted,
          prompt: '',
          keep_alive: env.LLM_KEEP_ALIVE || '24h',
          options: { num_ctx: Number(env.LLM_NUM_CTX) || 6144 },
        }),
      })
        .then(() => console.log(`Model "${wanted}" loaded.`))
        .catch(() => console.warn(`Could not preload model "${wanted}"; the first answer may be slower.`));
    }
  } catch {
    console.warn(`Ollama is not reachable at ${baseUrl}. Start the Ollama app so the chatbot can answer.`);
  }
}

function cleanupStaleProcesses() {
  if (!isWindows) return;

  const ports = ['3000', '3001', '8001', '8002', '8003'];
  for (const port of ports) {
    try {
      const output = spawnSync('netstat', ['-ano', '|', 'findstr', `:${port}`], {
        cwd: root,
        encoding: 'utf8',
        shell: true,
      });

      if (output.status !== 0) continue;

      const pids = [...new Set(output.stdout.split(/\r?\n/)
        .map((line) => line.trim().split(/\s+/).pop())
        .filter((value) => /^\d+$/.test(value)))];

      for (const pid of pids) {
        try {
          spawnSync('taskkill', ['/F', '/PID', pid], { cwd: root, stdio: 'ignore', shell: true });
        } catch (error) {
          // ignore cleanup errors
        }
      }
    } catch (error) {
      // ignore cleanup errors
    }
  }
}

function isCommandAvailable(command) {
  try {
    const result = spawnSync(command, ['--version'], {
      cwd: root,
      stdio: 'ignore',
      shell: isWindows,
    });
    return result.status === 0 || result.error == null;
  } catch (error) {
    return false;
  }
}

function run(command, args, options = {}) {
  const child = spawn(command, args, {
    cwd: options.cwd || root,
    stdio: ['ignore', 'inherit', 'inherit'],
    env: { ...process.env, ...options.env },
    windowsHide: true,
    shell: isWindows,
  });

  child.on('error', (error) => {
    if (options.allowFailure) {
      console.warn(`Process failed to start: ${command} ${args.join(' ')} (${error.message})`);
      return;
    }

    console.error(`Failed to start process: ${command} ${args.join(' ')} (${error.message})`);
    process.exit(1);
  });

  child.on('exit', (code) => {
    if (code && !options.allowFailure) {
      console.error(`Process exited with code ${code}: ${command} ${args.join(' ')}`);
      process.exit(code);
    }
  });

  return child;
}

function getPythonExecutable(serviceDir) {
  const candidates = isWindows
    ? [
        path.join(serviceDir, '.venv', 'Scripts', 'python.exe'),
        path.join(serviceDir, '.venv', 'Scripts', 'python'),
      ]
    : [
        path.join(serviceDir, '.venv', 'bin', 'python'),
        path.join(serviceDir, '.venv', 'bin', 'python3'),
      ];

  return candidates.find((candidate) => fs.existsSync(candidate)) || null;
}

function ensureEnvFile() {
  const envFile = path.join(root, '.env');
  if (!fs.existsSync(envFile)) {
    fs.copyFileSync(path.join(root, '.env.example'), envFile);
  }
}

function installFrontendDeps() {
  const webDir = path.join(root, 'apps', 'web');
  if (!fs.existsSync(path.join(webDir, 'node_modules'))) {
    console.log('Installing web dependencies...');
    run(pnpmCmd, ['install'], { cwd: webDir, allowFailure: true });
  }
}

function runSync(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd || root,
    stdio: 'inherit',
    env: { ...process.env, ...options.env },
    shell: isWindows,
  });

  if (result.error) {
    console.warn(`Process failed to start: ${command} ${args.join(' ')} (${result.error.message})`);
    return false;
  }

  if (result.status !== 0) {
    console.warn(`Process exited with code ${result.status}: ${command} ${args.join(' ')}`);
    return false;
  }

  return true;
}

function installPythonDeps(serviceName) {
  const serviceDir = path.join(root, 'services', serviceName);
  const pyproject = path.join(serviceDir, 'pyproject.toml');
  if (!fs.existsSync(pyproject)) return;

  const venvDir = path.join(serviceDir, '.venv');
  const venvPython = getPythonExecutable(serviceDir);
  const installStamp = path.join(venvDir, '.deps-installed');
  const packageName = serviceName === 'intelligence' ? 'veda-intelligence' : 'veda-ingestion';

  if (!fs.existsSync(venvDir)) {
    console.log(`Creating Python virtualenv for ${serviceName}...`);
    if (!runSync(pythonCmd, isWindows ? ['-3', '-m', 'venv', '.venv'] : ['-m', 'venv', '.venv'], { cwd: serviceDir })) {
      console.warn(`Could not create Python virtualenv for ${serviceName}.`);
      return;
    }
  }

  if (!venvPython && fs.existsSync(venvDir)) {
    console.warn(`Python environment for ${serviceName} was created, but no interpreter was found.`);
    return;
  }

  if (!venvPython) {
    console.warn(`Skipping Python dependency installation for ${serviceName}; no virtualenv was created.`);
    return;
  }

  const packageCheck = spawnSync(venvPython, ['-m', 'pip', 'show', packageName], {
    cwd: serviceDir,
    stdio: 'ignore',
    shell: isWindows,
  });

  if (packageCheck.status === 0 && fs.existsSync(installStamp)) {
    console.log(`Python dependencies for ${serviceName} already installed; skipping install.`);
    return;
  }

  console.log(`Installing Python dependencies for ${serviceName}...`);
  runSync(venvPython, ['-m', 'pip', 'install', '--upgrade', 'pip', 'setuptools', 'wheel'], { cwd: serviceDir });
  runSync(venvPython, ['-m', 'pip', 'install', '-e', '.'], { cwd: serviceDir });

  try {
    fs.mkdirSync(venvDir, { recursive: true });
    fs.writeFileSync(installStamp, new Date().toISOString());
  } catch (error) {
    console.warn(`Could not write install stamp for ${serviceName}: ${error.message}`);
  }
}

function startInfra() {
  if (process.env.SKIP_DOCKER === '1') {
    console.log('Skipping Docker infrastructure startup.');
    return;
  }

  if (!isCommandAvailable('docker')) {
    console.log('Docker CLI not detected; skipping infrastructure startup.');
    return;
  }

  console.log('Starting Docker infrastructure...');
  run('docker', ['compose', 'up', '-d'], { cwd: root, allowFailure: true });
}

function startWeb(serviceEnv = process.env) {
  const webDir = path.join(root, 'apps', 'web');
  const nextDir = path.join(webDir, '.next');

  if (fs.existsSync(nextDir)) {
    try {
      fs.rmSync(nextDir, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
    } catch (error) {
      console.warn(`Could not clear ${nextDir}: ${error.message}`);
    }
  }

  console.log(`Starting web app on http://localhost:${webPort}`);
  run(pnpmCmd, ['dev', '--hostname', '0.0.0.0', '--port', webPort], {
    cwd: webDir,
    env: serviceEnv,
    allowFailure: true,
  });
}

function startPythonService(serviceName, args, port, serviceEnv = process.env) {
  const serviceDir = path.join(root, 'services', serviceName);
  const venvPython = getPythonExecutable(serviceDir);

  if (!venvPython) {
    console.warn(`Skipping ${serviceName}; Python environment not found.`);
    return;
  }

  console.log(`Starting ${serviceName} on http://localhost:${port}`);
  run(venvPython, args, {
    cwd: serviceDir,
    env: { ...serviceEnv, PORT: String(port) },
    allowFailure: true,
  });
}

async function main() {
  ensureEnvFile();
  const mode = (process.env.PIPELINE_MODE || loadRootEnv().PIPELINE_MODE || 'local').toLowerCase();
  const serviceEnv = buildServiceEnv(mode);
  console.log(`Pipeline mode: ${mode}`);

  cleanupStaleProcesses();
  installFrontendDeps();
  installPythonDeps('ingestion');
  installPythonDeps('intelligence');

  if (mode === 'local') {
    console.log('Local mode: skipping Docker. Uploads go to', serviceEnv.LOCAL_STORAGE_DIR);
    await checkOllama(serviceEnv);
  } else {
    startInfra();
  }

  startPythonService(
    'intelligence',
    ['-m', 'uvicorn', 'src.api:app', '--host', '127.0.0.1', '--port', '8002'],
    8002,
    serviceEnv
  );

  if (mode === 'local') {
    startPythonService('ingestion', ['-m', 'src.workers.local_worker'], 8001, serviceEnv);
  } else if (process.env.START_WORKERS === '1') {
    startPythonService('ingestion', ['-m', 'src.workers.ingestion_worker'], 8001, serviceEnv);
    startPythonService('intelligence', ['-m', 'src.knowledge_graph.graph_worker'], 8003, serviceEnv);
  } else {
    console.log('Optional worker services are disabled for faster startup. Set START_WORKERS=1 to enable them.');
  }

  startWeb(serviceEnv);
}

main();
