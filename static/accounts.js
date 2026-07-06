const flowMode = document.body.dataset.flowMode || 'setup';
const isAddGamesFlow = flowMode === 'add-games';
const mainAccounts = JSON.parse(localStorage.getItem('chessAccounts') || '[]');
const storageKey = isAddGamesFlow ? 'chessPendingAddAccounts' : 'chessAccounts';
const accounts = JSON.parse(localStorage.getItem(storageKey) || '[]');

function sameAccount(left, right) {
  return left.provider === right.provider
    && String(left.username || '').toLowerCase() === String(right.username || '').toLowerCase();
}

function saveAccounts() {
  localStorage.setItem(storageKey, JSON.stringify(accounts));
  renderAccounts();
}

function upsertAccount(account) {
  const index = accounts.findIndex(item => item.provider === account.provider);
  const nextAccount = { ...account, hidden: false };
  if (index >= 0) accounts[index] = nextAccount;
  else accounts.push(nextAccount);
  saveAccounts();
}

function renderAccounts() {
  document.querySelectorAll('.account-panel').forEach(form => {
    const provider = form.dataset.provider;
    const account = accounts.find(item => item.provider === provider && !item.hidden);
    const state = form.querySelector('.connection-state');
    if (account) {
      form.querySelector('input').value = account.username;
      state.textContent = `${account.username} · ${account.games.toLocaleString()}게임`;
      state.classList.add('connected');
    } else {
      state.textContent = '연결 안 됨';
      state.classList.remove('connected');
    }
  });

  const visibleAccounts = accounts.filter(account => !account.hidden);
  const totalGames = visibleAccounts.reduce((sum, account) => sum + account.games, 0);
  document.getElementById('accountSummary').textContent = visibleAccounts.length
    ? `${visibleAccounts.length}개 계정 · ${totalGames.toLocaleString()}게임`
    : '연결된 계정이 없습니다.';
  document.getElementById('continueButton').disabled = visibleAccounts.length === 0;
}

async function readJsonResponse(response) {
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    return response.json();
  }
  const text = await response.text();
  const plainText = text
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  throw new Error(plainText || '서버가 올바른 응답을 반환하지 않았습니다.');
}

document.querySelectorAll('.account-panel').forEach(form => {
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const provider = form.dataset.provider;
    const input = form.querySelector('input');
    const button = form.querySelector('button');
    const message = form.querySelector('.inline-message');
    const username = input.value.trim();
    if (!username) return;
    if (
      isAddGamesFlow
      && mainAccounts.some(account => sameAccount(account, { provider, username }))
    ) {
      message.className = 'inline-message error';
      message.textContent = '이미 분석에 사용 중인 계정입니다. 새 계정만 추가해주세요.';
      return;
    }

    button.disabled = true;
    button.textContent = '불러오는 중...';
    message.className = 'inline-message';
    message.textContent = '게임 기록을 확인하고 있습니다.';
    try {
      const response = await fetch('/api/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider, username }),
      });
      const data = await readJsonResponse(response);
      if (!response.ok) throw new Error(data.error || '게임을 불러오지 못했습니다.');
      if (
        isAddGamesFlow
        && mainAccounts.some(account => sameAccount(account, { provider, username: data.username }))
      ) {
        throw new Error('이미 분석에 사용 중인 계정입니다. 새 계정만 추가해주세요.');
      }
      upsertAccount({
        provider,
        username: data.username,
        games: data.games,
        moves: data.moves,
        player_moves: data.player_moves,
      });
      message.textContent = data.added_games
        ? `${data.added_games}게임을 새로 저장했습니다.`
        : '이미 최신 상태입니다.';
    } catch (error) {
      message.className = 'inline-message error';
      message.textContent = error.message;
    } finally {
      button.disabled = false;
      button.textContent = '불러오기';
    }
  });
});

document.getElementById('continueButton').addEventListener('click', () => {
  if (isAddGamesFlow) {
    localStorage.setItem('analysisAccountSource', 'add-games');
  } else {
    localStorage.removeItem('analysisAccountSource');
    localStorage.removeItem('chessPendingAddAccounts');
  }
  if (window.checkssNavigate) {
    window.checkssNavigate('/analysis');
  } else {
    window.location.href = '/analysis';
  }
});

renderAccounts();
