const analysisAccountSource = localStorage.getItem('analysisAccountSource');
const accountStorageKey = analysisAccountSource === 'add-games'
  ? 'chessPendingAddAccounts'
  : 'chessAccounts';
const accounts = JSON.parse(localStorage.getItem(accountStorageKey) || '[]');
const state = {
  depth: 14,
  threads: 6,
  analysisMoves: 0,
  summary: null,
};

function activeAccounts() {
  return accounts.filter(account => !account.hidden);
}

function mergeMainAccounts(nextAccounts) {
  const mainAccounts = JSON.parse(localStorage.getItem('chessAccounts') || '[]');
  nextAccounts.forEach(account => {
    const index = mainAccounts.findIndex(item => item.provider === account.provider);
    const merged = { ...account, hidden: false };
    if (index >= 0) mainAccounts[index] = merged;
    else mainAccounts.push(merged);
  });
  localStorage.setItem('chessAccounts', JSON.stringify(mainAccounts));
  localStorage.removeItem('chessPendingAddAccounts');
  localStorage.removeItem('analysisAccountSource');
}

function formatDuration(seconds) {
  if (!Number.isFinite(seconds)) return '-';
  if (seconds < 60) return `약 ${Math.max(1, seconds)}초`;
  const minutes = Math.ceil(seconds / 60);
  if (minutes < 60) return `약 ${minutes}분`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `약 ${hours}시간 ${rest}분` : `약 ${hours}시간`;
}

function showSetupError(message) {
  const error = document.getElementById('setupError');
  error.textContent = message || '';
  error.classList.toggle('hidden', !message);
}

function buildThreadOptions() {
  const select = document.getElementById('threadSelect');
  const logical = Math.max(1, Math.min(16, navigator.hardwareConcurrency || 4));
  const available = [...select.options]
    .map(option => Number(option.value))
    .filter(value => value <= logical);
  const target = logical >= 12 ? 6 : logical >= 8 ? 4 : Math.max(1, logical - 2);
  const recommended = available.filter(value => value <= target).pop() || 1;

  [...select.options].forEach(option => {
    const value = Number(option.value);
    option.disabled = value > logical;
    option.textContent = value === recommended
      ? `${value}개 (권장)`
      : `${value}개`;
    option.selected = value === recommended;
  });
  state.threads = recommended;
}

async function loadSummary() {
  const visibleAccounts = activeAccounts();
  if (!visibleAccounts.length) {
    window.location.replace(
      analysisAccountSource === 'add-games' ? '/?flow=add-games' : '/'
    );
    return;
  }
  const response = await fetch('/api/accounts/summary', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      accounts: visibleAccounts,
      cutoff_date: document.getElementById('cutoffDate').value,
      depth: state.depth,
    }),
  });
  const data = await response.json();
  state.summary = data;
  state.analysisMoves = data.eligible_moves;
  document.getElementById('accountCount').textContent = data.accounts.length;
  document.getElementById('gameCount').textContent = data.games.toLocaleString();
  document.getElementById('analysisMoveCount').textContent = data.eligible_moves.toLocaleString();
  document.getElementById('estimateMoves').textContent = `${data.eligible_moves.toLocaleString()}수`;
  const cutoffDate = document.getElementById('cutoffDate').value;
  const removedGames = data.games - data.eligible_games;
  document.getElementById('cleanupPreview').textContent = cutoffDate
    ? removedGames
      ? `분석 시작 시 오래된 ${removedGames.toLocaleString()}게임을 삭제합니다.`
      : '삭제할 오래된 게임이 없습니다.'
    : '날짜를 선택하지 않으면 모든 게임을 유지합니다.';
  updateEstimate();
}

async function updateEstimate() {
  document.getElementById('estimateDepth').textContent = state.depth;
  document.getElementById('estimateThreads').textContent = state.threads;
  if (!state.analysisMoves) {
    document.getElementById('estimatedTime').textContent = '-';
    return;
  }
  const response = await fetch('/api/estimate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      move_count: state.analysisMoves,
      depth: state.depth,
      threads: state.threads,
    }),
  });
  const data = await response.json();
  document.getElementById('estimatedTime').textContent = formatDuration(data.estimated_seconds);
}

document.getElementById('depthOptions').addEventListener('click', event => {
  const button = event.target.closest('button[data-depth]');
  if (!button) return;
  state.depth = Number(button.dataset.depth);
  localStorage.setItem('analysisDepth', String(state.depth));
  document.querySelectorAll('#depthOptions button').forEach(item => {
    item.classList.toggle('active', item === button);
  });
  loadSummary();
});

document.getElementById('threadSelect').addEventListener('change', event => {
  state.threads = Number(event.target.value);
  updateEstimate();
});

document.getElementById('startAnalysis').addEventListener('click', async event => {
  const button = event.currentTarget;
  button.disabled = true;
  button.textContent = '작업 등록 중...';
  showSetupError('');
  try {
    const visibleAccounts = activeAccounts();
    if (!visibleAccounts.length) throw new Error('분석할 계정이 없습니다.');
    const response = await fetch('/api/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        accounts: visibleAccounts,
        depth: state.depth,
        threads: state.threads,
        cutoff_date: document.getElementById('cutoffDate').value,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '분석을 시작하지 못했습니다.');
    localStorage.setItem('analysisJobId', String(data.id));
    localStorage.setItem('analysisDepth', String(state.depth));
    if (analysisAccountSource === 'add-games') {
      mergeMainAccounts(visibleAccounts);
    }
    if (window.checkssNavigate) {
      window.checkssNavigate('/analyzing');
    } else {
      window.location.href = '/analyzing';
    }
  } catch (error) {
    showSetupError(error.message);
    button.disabled = false;
    button.textContent = '분석 시작';
  }
});

document.getElementById('cutoffDate').addEventListener('change', () => {
  localStorage.setItem('analysisCutoffDate', document.getElementById('cutoffDate').value);
  loadSummary();
});

buildThreadOptions();
localStorage.setItem('analysisDepth', String(state.depth));
document.getElementById('cutoffDate').value =
  localStorage.getItem('analysisCutoffDate') || '';
loadSummary().catch(error => showSetupError(error.message));
