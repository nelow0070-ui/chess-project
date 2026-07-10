function refreshPosition(options = {}) {
  if (!options.keepDetail) {
    detailMode = false;
    clearAnalysisPoll();
  }
  renderStatus();
  loadMoves();
  evaluatePosition();
}

document.getElementById('board').addEventListener('click', handleBoardClick);
document.getElementById('newGame').addEventListener('click', () => {
  game.reset();
  resetLine(game.fen());
  clearSelection();
  board.start(false);
  refreshPosition();
});
document.getElementById('undoMove').addEventListener('click', () => {
  if (currentPly >= 0) {
    replayToPly(currentPly - 1);
  } else {
    game.undo();
  }
  clearSelection();
  board.position(game.fen(), false);
  refreshPosition();
});
els.previousMove.addEventListener('click', () => stepHistory(-1));
els.nextMove.addEventListener('click', () => stepHistory(1));
els.myColorWhite.addEventListener('click', () => setMyColor('white'));
els.myColorBlack.addEventListener('click', () => setMyColor('black'));
els.viewWhite?.addEventListener('click', () => setOrientation('white'));
els.viewBlack?.addEventListener('click', () => setOrientation('black'));
els.settingsViewWhite.addEventListener('click', () => setOrientation('white'));
els.settingsViewBlack.addEventListener('click', () => setOrientation('black'));
els.settingsMyColorWhite.addEventListener('click', () => setMyColor('white'));
els.settingsMyColorBlack.addEventListener('click', () => setMyColor('black'));
els.moveSortFrequency.addEventListener('click', () => setMoveSort('frequency'));
els.moveSortQuality.addEventListener('click', () => setMoveSort('quality'));
els.timeClassFilters.addEventListener('click', event => {
  const button = event.target.closest('button[data-time-class]');
  if (!button) return;
  const current = activeTimeClasses();
  const value = button.dataset.timeClass;
  const next = current.includes(value)
    ? current.filter(item => item !== value)
    : [...current, value];
  setActiveTimeClasses(next);
  loadMoves();
});
document.querySelectorAll('.board-tabs button').forEach(button => {
  button.addEventListener('click', () => switchPanel(button.dataset.panel));
});
document.querySelectorAll('.settings-tab-button').forEach(button => {
  button.addEventListener('click', () => switchSettingsTab(button.dataset.settingsTab));
});
els.managerAccountList.addEventListener('click', event => {
  const button = event.target.closest('button[data-account-action]');
  if (!button) return;
  if (button.dataset.accountAction === 'toggle') {
    toggleAccountHidden(button.dataset.provider);
  } else if (button.dataset.accountAction === 'remove') {
    removeAccount(button.dataset.provider);
  }
});
els.pgnDisplay.addEventListener('click', event => {
  const move = event.target.closest('.history-move-text[data-ply]');
  if (!move) return;
  jumpToHistoryPly(Number(move.dataset.ply));
});
els.pgnDisplay.addEventListener('keydown', event => {
  if (event.key !== 'Enter' && event.key !== ' ') return;
  const move = event.target.closest('.history-move-text[data-ply]');
  if (!move) return;
  event.preventDefault();
  jumpToHistoryPly(Number(move.dataset.ply));
});
document.getElementById('openAnalysisManager').addEventListener('click', openAnalysisManager);
document.getElementById('closeAnalysisManager').addEventListener('click', closeAnalysisManager);
els.openTutorial.addEventListener('click', () => {
  els.tutorialModal.classList.remove('hidden');
  els.tutorialModal.setAttribute('aria-hidden', 'false');
});
els.closeTutorial.addEventListener('click', () => {
  els.tutorialModal.classList.add('hidden');
  els.tutorialModal.setAttribute('aria-hidden', 'true');
});
els.openFenInput.addEventListener('click', openFenInput);
els.closeFenInput.addEventListener('click', closeFenInput);
els.applyFenSearch.addEventListener('click', applyFenSearch);
els.copyFen.addEventListener('click', copyFen);
els.openPgnInput.addEventListener('click', openPgnInput);
els.closePgnInput.addEventListener('click', closePgnInput);
els.applyPgnPaste.addEventListener('click', applyPgnPaste);
els.copyPgn.addEventListener('click', copyPgn);
els.fenSearchInput.addEventListener('keydown', event => {
  if (event.key === 'Escape') closeFenInput();
  if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') applyFenSearch();
});
els.pgnPasteInput.addEventListener('keydown', event => {
  if (event.key === 'Escape') closePgnInput();
  if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') applyPgnPaste();
});
els.analysisManager.addEventListener('click', event => {
  if (event.target === els.analysisManager) closeAnalysisManager();
});
els.tutorialModal.addEventListener('click', event => {
  if (event.target === els.tutorialModal) {
    els.tutorialModal.classList.add('hidden');
    els.tutorialModal.setAttribute('aria-hidden', 'true');
  }
});
els.moveList.addEventListener('click', event => {
  const back = event.target.closest('[data-detail-back]');
  if (back) {
    detailMode = false;
    clearAnalysisPoll();
    loadMoves();
    return;
  }
  const gameRow = event.target.closest('.game-row[data-game-id]');
  if (gameRow) openGameAnalysis(gameRow.dataset.gameId);
});
els.addGamesPlaceholder.addEventListener('click', () => {
  closeAnalysisManager();
  localStorage.removeItem('chessPendingAddAccounts');
  localStorage.removeItem('analysisAccountSource');
  if (window.checkssNavigate) {
    window.checkssNavigate('/?flow=add-games');
  } else {
    window.location.href = '/?flow=add-games';
  }
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && !els.analysisManager.classList.contains('hidden')) {
    closeAnalysisManager();
  }
});
els.managerDateFrom.addEventListener('change', refreshManagerSummary);
els.managerDateTo.addEventListener('change', refreshManagerSummary);
els.toggleDateFilter.addEventListener('click', () => {
  const enabled = els.toggleDateFilter.getAttribute('aria-pressed') !== 'true';
  setDateFilterEnabled(enabled);
  if (!enabled) {
    els.managerDateFrom.value = '';
    els.managerDateTo.value = '';
    localStorage.removeItem('boardDateFrom');
    localStorage.removeItem('boardDateTo');
    refreshManagerSummary();
    setManagerMessage('표시 기간을 끄고 전체 기간의 데이터를 표시합니다.');
    loadMoves();
  } else {
    setManagerMessage('');
    els.managerDateFrom.focus();
  }
});
document.getElementById('applyDateFilter').addEventListener('click', () => {
  if (
    els.managerDateFrom.value
    && els.managerDateTo.value
    && els.managerDateFrom.value > els.managerDateTo.value
  ) {
    setManagerMessage('시작 날짜는 종료 날짜보다 늦을 수 없습니다.', true);
    return;
  }
  localStorage.setItem('boardDateFrom', els.managerDateFrom.value);
  localStorage.setItem('boardDateTo', els.managerDateTo.value);
  setManagerMessage('표시 기간을 적용했습니다.');
  loadMoves();
});
document.getElementById('clearDateFilter').addEventListener('click', () => {
  els.managerDateFrom.value = '';
  els.managerDateTo.value = '';
  localStorage.removeItem('boardDateFrom');
  localStorage.removeItem('boardDateTo');
  setDateFilterEnabled(false);
  refreshManagerSummary();
  setManagerMessage('표시 기간을 끄고 전체 기간의 데이터를 표시합니다.');
  loadMoves();
});
els.resetConfirmation.addEventListener('input', () => {
  els.resetDatabase.disabled = els.resetConfirmation.value !== 'RESET';
});
els.resetDatabase.addEventListener('click', async () => {
  els.resetDatabase.disabled = true;
  setManagerMessage('데이터베이스를 초기화하는 중입니다.');
  try {
    const response = await fetch('/api/database/reset', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirmation: els.resetConfirmation.value }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '초기화하지 못했습니다.');
    localStorage.removeItem('chessAccounts');
    localStorage.removeItem('analysisJobId');
    localStorage.removeItem('boardDateFrom');
    localStorage.removeItem('boardDateTo');
    accounts.splice(0, accounts.length);
    window.location.assign('/');
  } catch (error) {
    setManagerMessage(error.message, true);
    els.resetDatabase.disabled = els.resetConfirmation.value !== 'RESET';
  }
});

orientation = localStorage.getItem('boardOrientation') || myColor;
board = Chessboard('board', {
  draggable: false,
  position: 'start',
  orientation,
  pieceTheme: 'https://chessboardjs.com/img/chesspieces/wikipedia/{piece}.png',
});

function resizeBoard() {
  const boardElement = document.getElementById('board');
  const stage = document.querySelector('.board-stage');
  const evalBar = document.querySelector('.eval-bar');
  boardElement.style.width = '';
  evalBar.style.height = '';
  const available = Math.min(
    boardElement.getBoundingClientRect().width,
    stage.clientHeight,
    stage.clientWidth - evalBar.offsetWidth - 33
  );
  const snapped = Math.max(8, Math.floor(available / 8) * 8);
  boardElement.style.width = `${snapped + 1}px`;
  evalBar.style.height = `${snapped}px`;
  board.resize();
  const boardFrame = boardElement.querySelector?.('.board-b72b1');
  if (boardFrame) {
    boardElement.style.width = `${boardFrame.offsetWidth}px`;
  }
}

let boardResizeTimer = null;
window.addEventListener('resize', () => {
  window.clearTimeout(boardResizeTimer);
  boardResizeTimer = window.setTimeout(resizeBoard, 80);
});
window.requestAnimationFrame(resizeBoard);

renderColorSetting();
renderMoveSort();
renderTimeClassFilters();
refreshPosition();
