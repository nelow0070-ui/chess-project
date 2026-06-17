import './styles.css';

const settings = {
  engineMode: localStorage.getItem('engineMode') || 'browser',
  serverBaseUrl: localStorage.getItem('serverBaseUrl') || '',
  browserDepth: Number(localStorage.getItem('browserDepth') || 10),
};

const game = new Chess();
let board = null;
let orientation = 'white';
let engineWorker = null;
let engineReady = null;
let evalRequestId = 0;

const els = {
  board: document.getElementById('board'),
  status: document.getElementById('status'),
  fenInput: document.getElementById('fenInput'),
  evalFill: document.getElementById('evalFill'),
  evalLabel: document.getElementById('evalLabel'),
  engineStatus: document.getElementById('engineStatus'),
  settingsToggle: document.getElementById('settingsToggle'),
  settingsPanel: document.getElementById('settingsPanel'),
  engineMode: document.getElementById('engineMode'),
  serverBaseUrl: document.getElementById('serverBaseUrl'),
  browserDepth: document.getElementById('browserDepth'),
};

els.engineMode.value = settings.engineMode;
els.serverBaseUrl.value = settings.serverBaseUrl;
els.browserDepth.value = String(settings.browserDepth);

function normalizeLine(event) {
  return typeof event.data === 'string' ? event.data : String(event.data?.data || '');
}

function createBrowserEngine() {
  if (engineReady) return engineReady;

  engineReady = new Promise((resolve, reject) => {
    try {
      engineWorker = new Worker('/stockfish-worker.js');
    } catch (error) {
      reject(error);
      return;
    }

    const timer = window.setTimeout(() => reject(new Error('Stockfish init timeout')), 12000);
    engineWorker.onmessage = event => {
      const line = normalizeLine(event);
      if (line === 'uciok' || line === 'readyok') {
        window.clearTimeout(timer);
        resolve(engineWorker);
      }
    };
    engineWorker.onerror = reject;
    engineWorker.postMessage('uci');
    engineWorker.postMessage('isready');
  });

  return engineReady;
}

function parseScore(line) {
  const cp = line.match(/\bscore cp (-?\d+)/);
  if (cp) return { type: 'cp', value: Number(cp[1]) };
  const mate = line.match(/\bscore mate (-?\d+)/);
  if (mate) return { type: 'mate', value: Number(mate[1]) };
  return null;
}

function toWhiteScore(score, turn) {
  if (score.type === 'mate') return { type: 'mate', mate: turn === 'w' ? score.value : -score.value };
  return { type: 'cp', cp: turn === 'w' ? score.value : -score.value };
}

async function evaluateBrowser(fen, turn) {
  const worker = await createBrowserEngine();
  return new Promise((resolve, reject) => {
    let lastScore = null;
    const timer = window.setTimeout(() => reject(new Error('Stockfish eval timeout')), 15000);

    worker.onmessage = event => {
      const line = normalizeLine(event);
      if (line.startsWith('info ')) {
        const score = parseScore(line);
        if (score) lastScore = score;
        return;
      }
      if (line.startsWith('bestmove ')) {
        window.clearTimeout(timer);
        if (!lastScore) reject(new Error('No Stockfish score'));
        else resolve(toWhiteScore(lastScore, turn));
      }
    };

    worker.postMessage('stop');
    worker.postMessage(`position fen ${fen}`);
    worker.postMessage(`go depth ${settings.browserDepth}`);
  });
}

async function evaluateServer(fen) {
  if (!settings.serverBaseUrl) throw new Error('Server API base URL is empty');
  const base = settings.serverBaseUrl.replace(/\/$/, '');
  const response = await fetch(`${base}/eval?fen=${encodeURIComponent(fen)}`);
  const data = await response.json();
  if (data.error) throw new Error(data.error);
  return data;
}

function formatEval(data) {
  if (data.type === 'mate') return data.mate > 0 ? `M${data.mate}` : `-M${Math.abs(data.mate)}`;
  const pawns = data.cp / 100;
  return pawns > 0 ? `+${pawns.toFixed(1)}` : pawns.toFixed(1);
}

function renderEval(data) {
  const whitePercent = data.type === 'mate'
    ? (data.mate > 0 ? 100 : 0)
    : 50 + Math.max(-800, Math.min(800, data.cp)) / 16;
  els.evalFill.style.height = `${whitePercent}%`;
  els.evalLabel.textContent = formatEval(data);
  els.engineStatus.textContent = settings.engineMode === 'browser' ? 'Browser Stockfish' : 'Server Stockfish API';
}

function renderStatus() {
  const side = game.turn() === 'w' ? 'White' : 'Black';
  els.status.textContent = game.game_over() ? 'Game over' : `${side} to move`;
  els.fenInput.value = game.fen();
}

async function analyze() {
  const requestId = ++evalRequestId;
  const fen = game.fen();
  const turn = game.turn();
  els.evalLabel.textContent = '...';
  try {
    const result = settings.engineMode === 'server'
      ? await evaluateServer(fen)
      : await evaluateBrowser(fen, turn);
    if (requestId === evalRequestId) renderEval(result);
  } catch (error) {
    if (requestId === evalRequestId) {
      els.evalLabel.textContent = '--';
      els.engineStatus.textContent = error.message;
    }
  }
}

function onDrop(source, target) {
  const move = game.move({ from: source, to: target, promotion: 'q' });
  if (!move) return 'snapback';
  renderStatus();
  analyze();
}

board = Chessboard('board', {
  draggable: true,
  position: 'start',
  orientation,
  pieceTheme: 'https://chessboardjs.com/img/chesspieces/wikipedia/{piece}.png',
  onDrop,
  onSnapEnd: () => board.position(game.fen()),
});

els.settingsToggle.addEventListener('click', () => els.settingsPanel.classList.toggle('hidden'));
els.engineMode.addEventListener('change', event => {
  settings.engineMode = event.target.value;
  localStorage.setItem('engineMode', settings.engineMode);
  analyze();
});
els.serverBaseUrl.addEventListener('change', event => {
  settings.serverBaseUrl = event.target.value.trim();
  localStorage.setItem('serverBaseUrl', settings.serverBaseUrl);
});
els.browserDepth.addEventListener('change', event => {
  settings.browserDepth = Number(event.target.value || 10);
  localStorage.setItem('browserDepth', String(settings.browserDepth));
});
document.getElementById('newGame').addEventListener('click', () => {
  game.reset();
  board.start();
  renderStatus();
  analyze();
});
document.getElementById('undoMove').addEventListener('click', () => {
  game.undo();
  board.position(game.fen());
  renderStatus();
  analyze();
});
document.getElementById('flipBoard').addEventListener('click', () => {
  orientation = orientation === 'white' ? 'black' : 'white';
  board.orientation(orientation);
});
document.getElementById('analyze').addEventListener('click', analyze);

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/service-worker.js').catch(() => {});
}

renderStatus();
analyze();
