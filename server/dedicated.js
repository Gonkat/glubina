#!/usr/bin/env node
/*
 * Выделенный сервер «ГЛУБИНЫ»: точка входа для игроков.
 *
 * Зачем отдельный процесс, а не только Python:
 *   • сервер слушает публичный порт и держит сессию, даже когда ни один
 *     игрок ещё не подключился;
 *   • авторитетная симуляция запускается рядом отдельным headless-процессом
 *     netplay.authority (тот же мир и код, что у игрока-хоста), поэтому
 *     клиенты не видят «фантомного» хоста и им не нужно ничего менять;
 *   • Node владеет жизненным циклом: запускает движок, следит за ним,
 *     перезапускает после падения и аккуратно гасит всё по SIGINT/SIGTERM.
 *
 * Каждое клиентское TCP-соединение проксируется в собственное соединение
 * с движком (127.0.0.1), поэтому протокол, рукопожатие, pid, лимит
 * игроков и реконнект остаются ровно теми же, что в host-based режиме.
 *
 * Запуск:
 *   node server/dedicated.js --port 32123 --clients 1
 * Клиент подключается к <ip>:32123 как к обычному хосту.
 */

"use strict";

const net = require("net");
const path = require("path");
const { spawn } = require("child_process");

function parseArgs(argv) {
  const args = {
    port: 32123,
    authorityPort: 32124,
    bind: "0.0.0.0",
    clients: 1,
    name: "Выделенный сервер",
    tick: 120,
    python: process.env.PYTHON || (process.platform === "win32" ? "python" : "python3"),
  };
  for (let i = 0; i < argv.length; i += 1) {
    const key = argv[i];
    const value = argv[i + 1];
    if (key === "--port") args.port = Number(value);
    else if (key === "--authority-port") args.authorityPort = Number(value);
    else if (key === "--bind") args.bind = value;
    else if (key === "--clients") args.clients = Number(value);
    else if (key === "--name") args.name = value;
    else if (key === "--tick") args.tick = Number(value);
    else if (key === "--python") args.python = value;
    else if (key === "--help" || key === "-h") {
      console.log("node server/dedicated.js [--port 32123] [--authority-port 32124] " +
                  "[--bind 0.0.0.0] [--clients 1] [--name ...] [--python python]");
      process.exit(0);
    } else continue;
    i += 1;
  }
  return args;
}

const args = parseArgs(process.argv.slice(2));
const root = path.resolve(__dirname, "..");
let shuttingDown = false;
let engine = null;
let engineRestarts = 0;
const sockets = new Set();

function log(message) {
  console.log(`[dedicated] ${message}`);
}

function spawnEngine() {
  const child = spawn(
    args.python,
    [
      "-m", "netplay.authority",
      "--port", String(args.authorityPort),
      "--bind", "127.0.0.1",
      "--clients", String(args.clients),
      "--name", args.name,
      "--tick", String(args.tick),
    ],
    {
      cwd: root,
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
      // Русский текст в логах не должен зависеть от кодовой страницы
      // консоли Windows.
      env: { ...process.env, PYTHONIOENCODING: "utf-8", PYTHONUNBUFFERED: "1" },
    }
  );
  child.stdout.on("data", (data) => process.stdout.write(String(data)));
  child.stderr.on("data", (data) => process.stderr.write(String(data)));
  child.on("exit", (code, signal) => {
    if (shuttingDown) return;
    engine = null;
    log(`движок завершился (code=${code}, signal=${signal})`);
    if (engineRestarts < 5) {
      engineRestarts += 1;
      const delay = 1000 * engineRestarts;
      log(`перезапуск движка через ${delay} мс`);
      setTimeout(() => {
        if (!shuttingDown) engine = spawnEngine();
      }, delay);
    } else {
      log("движок падает повторно — остановка");
      shutdown(1);
    }
  });
  return child;
}

function waitForEngine(timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const attempt = () => {
      if (shuttingDown) return reject(new Error("остановка"));
      const socket = net.connect(args.authorityPort, "127.0.0.1");
      socket.once("connect", () => {
        socket.destroy();
        resolve();
      });
      socket.once("error", () => {
        socket.destroy();
        if (Date.now() > deadline) {
          reject(new Error("движок не поднял порт"));
        } else {
          setTimeout(attempt, 250);
        }
      });
    };
    attempt();
  });
}

function proxyClient(client) {
  const upstream = net.connect(args.authorityPort, "127.0.0.1");
  sockets.add(client);
  sockets.add(upstream);
  let closed = false;

  const closeBoth = () => {
    if (closed) return;
    closed = true;
    sockets.delete(client);
    sockets.delete(upstream);
    client.destroy();
    upstream.destroy();
  };

  client.setNoDelay(true);
  upstream.setNoDelay(true);
  client.on("error", closeBoth);
  upstream.on("error", closeBoth);
  client.on("close", closeBoth);
  upstream.on("close", closeBoth);
  client.pipe(upstream);
  upstream.pipe(client);
  log(`игрок ${client.remoteAddress}:${client.remotePort} подключён ` +
      `(соединений ${sockets.size / 2})`);
}

function startProxy() {
  const server = net.createServer(proxyClient);
  server.on("error", (error) => {
    console.error(`[dedicated] сервер: ${error.message}`);
    shutdown(1);
  });
  server.listen(args.port, args.bind, () => {
    log(`слушаю ${args.bind}:${args.port} → движок 127.0.0.1:${args.authorityPort}`);
    log(`старт вылазки после ${args.clients} игрок(ов); Ctrl+C — остановка`);
  });
  return server;
}

function shutdown(code = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  log("остановка…");
  for (const socket of sockets) socket.destroy();
  sockets.clear();
  if (server) {
    try { server.close(); } catch (_) { /* уже закрыт */ }
  }
  if (engine) {
    try { engine.kill(); } catch (_) { /* уже мёртв */ }
  }
  setTimeout(() => process.exit(code), 250).unref();
}

let server = null;
engine = spawnEngine();
waitForEngine()
  .then(() => {
    server = startProxy();
  })
  .catch((error) => {
    console.error(`[dedicated] не удалось запустить движок: ${error.message}`);
    shutdown(1);
  });

process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));
