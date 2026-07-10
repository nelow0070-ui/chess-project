function accountQuery(fen = game.fen()) {
  const params = new URLSearchParams({
    fen,
    perspective: currentPerspective(),
  });
  const dateFrom = localStorage.getItem('boardDateFrom') || '';
  const dateTo = localStorage.getItem('boardDateTo') || '';
  if (dateFrom) params.set('date_from', dateFrom);
  if (dateTo) params.set('date_to', dateTo);
  const timeClasses = activeTimeClasses();
  if (timeClasses.length) params.set('time_classes', timeClasses.join(','));
  activeAccounts().forEach(account => params.set(account.provider, account.username));
  return params.toString();
}

function setManagerMessage(message, isError = false) {
  els.managerMessage.textContent = message;
  els.managerMessage.classList.toggle('error', isError);
}

function setDateFilterEnabled(enabled) {
  els.toggleDateFilter.classList.toggle('active', enabled);
  els.toggleDateFilter.setAttribute('aria-pressed', String(enabled));
  els.dateFilterControls.classList.toggle('hidden', !enabled);
}

async function refreshManagerSummary() {
  const dateFrom = els.managerDateFrom.value;
  const dateTo = els.managerDateTo.value;
  els.managerSummary.textContent = dateFrom || dateTo
    ? `${dateFrom || '처음'}부터 ${dateTo || '오늘'}까지의 게임만 보드 수 목록에 표시합니다.`
    : '전체 기간의 데이터를 보드 수 목록에 표시합니다.';
}

function switchSettingsTab(tab) {
  document.querySelectorAll('.settings-tab-button').forEach(button => {
    button.classList.toggle('active', button.dataset.settingsTab === tab);
  });
  els.settingsAnalysisPanel.classList.toggle('active', tab === 'analysis');
  els.settingsBoardPanel.classList.toggle('active', tab === 'board');
  els.settingsUserPanel.classList.toggle('active', tab === 'user');
}

function renderSettingsInfo() {
  if (accounts.length) {
    els.managerAccountList.innerHTML = accounts.map(account => `
      <div class="settings-info-row settings-account-row ${account.hidden ? 'is-hidden' : ''}">
        <div class="settings-account-main">
          <span>${account.provider === 'chesscom' ? 'Chess.com' : 'Lichess'}</span>
          <strong>${escapeHtml(account.username)}</strong>
          <em>${account.hidden ? '숨김' : '사용 중'}</em>
        </div>
        <div class="settings-account-actions">
          <button type="button" data-account-action="toggle" data-provider="${account.provider}">
            ${account.hidden ? '표시' : '숨김'}
          </button>
          <button type="button" class="danger-button compact-danger" data-account-action="remove" data-provider="${account.provider}">
            제거
          </button>
        </div>
      </div>
    `).join('');
  } else {
    els.managerAccountList.innerHTML = '<div class="settings-empty">연결된 계정이 없습니다.</div>';
  }

  if (accounts.length) {
    els.settingsAccountList.innerHTML = accounts.map(account => `
      <div class="settings-info-row settings-account-row ${account.hidden ? 'is-hidden' : ''}">
        <div class="settings-account-main">
          <span>${account.provider === 'chesscom' ? 'Chess.com' : 'Lichess'}</span>
          <strong>${escapeHtml(account.username)}</strong>
          <em>${account.hidden ? '숨김' : '사용 중'}</em>
        </div>
      </div>
    `).join('');
  } else {
    els.settingsAccountList.innerHTML = '<div class="settings-empty">연결된 계정이 없습니다.</div>';
  }
  els.settingsDepth.textContent = localStorage.getItem('analysisDepth') || '14';
  renderColorSetting();
  renderTimeClassFilters();
}

function openAnalysisManager() {
  switchSettingsTab('analysis');
  els.managerDateFrom.value = localStorage.getItem('boardDateFrom') || '';
  els.managerDateTo.value = localStorage.getItem('boardDateTo') || '';
  setDateFilterEnabled(Boolean(els.managerDateFrom.value || els.managerDateTo.value));
  els.resetConfirmation.value = '';
  els.resetDatabase.disabled = true;
  setManagerMessage('');
  renderSettingsInfo();
  els.analysisManager.classList.remove('hidden');
  els.analysisManager.setAttribute('aria-hidden', 'false');
  refreshManagerSummary();
}

function closeAnalysisManager() {
  els.analysisManager.classList.add('hidden');
  els.analysisManager.setAttribute('aria-hidden', 'true');
}

function setFenMessage(message, isError = false) {
  els.fenMessage.textContent = message;
  els.fenMessage.classList.toggle('error', isError);
}

function openFenInput() {
  els.fenSearchInput.value = game.fen();
  setFenMessage('');
  els.fenPopover.classList.remove('hidden');
  els.fenPopover.setAttribute('aria-hidden', 'false');
  els.fenSearchInput.focus();
  els.fenSearchInput.select();
}

function closeFenInput() {
  els.fenPopover.classList.add('hidden');
  els.fenPopover.setAttribute('aria-hidden', 'true');
}

function applyFenSearch() {
  const fen = els.fenSearchInput.value.trim();
  if (!fen) {
    setFenMessage('FEN을 입력해주세요.', true);
    return;
  }

  try {
    game.load(fen);
  } catch {
    setFenMessage('올바른 FEN 형식이 아닙니다.', true);
    return;
  }

  resetLine(game.fen());
  clearSelection();
  board.position(game.fen(), false);
  closeFenInput();
  switchPanel('database');
  refreshPosition();
}

function buildLinePgn() {
  const pgnGame = new Chess();
  if (lineStartFen !== defaultStartFen) {
    pgnGame.load(lineStartFen);
    pgnGame.setHeader('SetUp', '1');
    pgnGame.setHeader('FEN', lineStartFen);
  }
  moveLine.forEach(move => pgnGame.move(move));
  return pgnGame.pgn();
}

function setPgnMessage(message, isError = false) {
  els.pgnMessage.textContent = message;
  els.pgnMessage.classList.toggle('error', isError);
}

function openPgnInput() {
  els.pgnPasteInput.value = '';
  setPgnMessage('');
  els.pgnPopover.classList.remove('hidden');
  els.pgnPopover.setAttribute('aria-hidden', 'false');
  els.pgnPasteInput.focus();
}

function closePgnInput() {
  els.pgnPopover.classList.add('hidden');
  els.pgnPopover.setAttribute('aria-hidden', 'true');
}

function applyPgnPaste() {
  const pgn = els.pgnPasteInput.value.trim();
  if (!pgn) {
    setPgnMessage('PGN을 입력해주세요.', true);
    return;
  }

  const parsed = new Chess();
  try {
    parsed.loadPgn(pgn);
  } catch {
    setPgnMessage('올바른 PGN 형식이 아닙니다.', true);
    return;
  }

  const headers = parsed.header ? parsed.header() : {};
  const startFen = headers.FEN || defaultStartFen;
  const moves = parsed.history();
  try {
    game.load(startFen);
    moves.forEach(move => game.move(move));
  } catch {
    setPgnMessage('이 PGN의 시작 포지션을 불러오지 못했습니다.', true);
    return;
  }

  resetLine(startFen, moves);
  clearSelection();
  board.position(game.fen(), false);
  closePgnInput();
  switchPanel('history');
  refreshPosition();
}

async function copyPgn() {
  const pgn = buildLinePgn();
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(pgn);
    } else {
      const textarea = document.createElement('textarea');
      textarea.value = pgn;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      textarea.remove();
    }
    els.copyPgn.textContent = '복사됨';
    window.setTimeout(() => {
      els.copyPgn.textContent = '현재 PGN 복사';
    }, 1200);
  } catch {
    openPgnInput();
    els.pgnPasteInput.value = pgn;
    setPgnMessage('복사하지 못했습니다. 직접 선택해서 복사해주세요.', true);
  }
}

async function copyFen() {
  const fen = game.fen();
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(fen);
    } else {
      const textarea = document.createElement('textarea');
      textarea.value = fen;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      textarea.remove();
    }
    els.copyFen.textContent = '복사됨';
    window.setTimeout(() => {
      els.copyFen.textContent = '현재 FEN 복사';
    }, 1200);
  } catch {
    openFenInput();
    setFenMessage('복사하지 못했습니다. 직접 선택해서 복사해주세요.', true);
  }
}

