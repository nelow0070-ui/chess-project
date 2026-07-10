function activeAccounts() {
  return accounts.filter(account => !account.hidden);
}

function saveAccounts() {
  localStorage.setItem('chessAccounts', JSON.stringify(accounts));
}

function removeAccount(provider) {
  const index = accounts.findIndex(account => account.provider === provider);
  if (index < 0) return;
  accounts.splice(index, 1);
  saveAccounts();
  renderSettingsInfo();
  setManagerMessage('계정을 제거했습니다.');
  loadMoves();
}

function toggleAccountHidden(provider) {
  const account = accounts.find(item => item.provider === provider);
  if (!account) return;
  account.hidden = !account.hidden;
  saveAccounts();
  renderSettingsInfo();
  setManagerMessage(account.hidden ? '계정을 숨겼습니다.' : '계정을 다시 표시합니다.');
  loadMoves();
}

function squareElement(square) {
  return document.querySelector(`#board .square-${square}`);
}

function clearSelection() {
  selectedSquare = null;
  document.querySelectorAll('#board .square-55d63').forEach(square => {
    square.classList.remove('selected-square', 'legal-square', 'capture-square');
  });
}

function selectSquare(square) {
  clearSelection();
  const piece = game.get(square);
  if (!piece || piece.color !== game.turn()) return;

  const moves = game.moves({ square, verbose: true });
  if (!moves.length) return;

  selectedSquare = square;
  squareElement(square)?.classList.add('selected-square');
  moves.forEach(move => {
    const target = squareElement(move.to);
    if (target) target.classList.add(move.captured ? 'capture-square' : 'legal-square');
  });
}

function completeMove(target) {
  if (!selectedSquare) return false;
  let move = null;
  try {
    move = game.move({
      from: selectedSquare,
      to: target,
      promotion: 'q',
    });
  } catch {
    return false;
  }
  if (!move) return false;

  clearSelection();
  board.position(game.fen(), false);
  recordPlayedMove(move);
  refreshPosition();
  return true;
}

function handleBoardClick(event) {
  const squareNode = event.target.closest('.square-55d63');
  if (!squareNode || game.isGameOver()) return;
  const square = squareNode.dataset.square;
  if (!square) return;

  const piece = game.get(square);
  if (selectedSquare) {
    if (piece && piece.color === game.turn()) {
      if (square === selectedSquare) {
        clearSelection();
      } else {
        selectSquare(square);
      }
      return;
    }
    if (completeMove(square)) return;
    clearSelection();
    return;
  }

  if (piece && piece.color === game.turn()) {
    selectSquare(square);
  } else {
    clearSelection();
  }
}

function renderStatus() {
  const side = game.turn() === 'w' ? '백' : '흑';
  if (game.isCheckmate()) {
    els.status.textContent = `체크메이트 · ${side} 패배`;
  } else if (game.isDraw()) {
    els.status.textContent = '무승부';
  } else {
    els.status.textContent = `${side} 차례${game.isCheck() ? ' · 체크' : ''}`;
  }
  const hasMoves = moveLine.length > 0;
  if (hasMoves) {
    renderMoveHistory();
  } else {
    els.pgnDisplay.innerHTML = '<div class="empty-state compact">아직 진행된 수가 없습니다.</div>';
  }
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function renderMoveHistory() {
  const rows = [];
  for (let index = 0; index < moveLine.length; index += 2) {
    rows.push(`
      <span class="move-number">${Math.floor(index / 2) + 1}.</span>
      <span class="history-move-text ${currentPly === index ? 'current' : ''}" role="button" tabindex="0" data-ply="${index}">${escapeHtml(moveLine[index])}</span>
      <span class="history-move-text ${moveLine[index + 1] ? '' : 'empty'} ${currentPly === index + 1 ? 'current' : ''}" ${moveLine[index + 1] ? `role="button" tabindex="0" data-ply="${index + 1}"` : ''}>${moveLine[index + 1] ? escapeHtml(moveLine[index + 1]) : ''}</span>
    `);
  }
  els.pgnDisplay.innerHTML = `<div class="move-history-grid">${rows.join('')}</div>`;
}

function renderHistoryNavigation() {
  els.previousMove.disabled = currentPly < 0;
  els.nextMove.disabled = currentPly >= moveLine.length - 1;
}

function replayToPly(ply) {
  const targetMoves = moveLine.slice(0, ply + 1);
  try {
    game.load(lineStartFen);
    targetMoves.forEach(move => game.move(move));
  } catch {
    return;
  }

  currentPly = ply;
  return true;
}

function jumpToHistoryPly(ply) {
  if (!Number.isInteger(ply) || ply < 0 || ply >= moveLine.length) return;
  if (!replayToPly(ply)) return;

  clearSelection();
  board.position(game.fen(), false);
  refreshPosition();
}

function stepHistory(offset) {
  const targetPly = currentPly + offset;
  if (targetPly < -1 || targetPly >= moveLine.length) return;
  if (!replayToPly(targetPly)) return;

  clearSelection();
  board.position(game.fen(), false);
  refreshPosition();
}

function recordPlayedMove(move) {
  const san = typeof move === 'string' ? move : move.san;
  if (!san) return;

  const nextIndex = currentPly + 1;
  if (moveLine[nextIndex] === san) {
    currentPly = nextIndex;
    return;
  }

  moveLine = moveLine.slice(0, nextIndex);
  moveLine.push(san);
  currentPly = moveLine.length - 1;
}

function resetLine(startFen = defaultStartFen, moves = []) {
  lineStartFen = startFen;
  moveLine = [...moves];
  currentPly = -1;
  if (moveLine.length) replayToPly(moveLine.length - 1);
}

function isMyTurn() {
  return (myColor === 'white' && game.turn() === 'w')
    || (myColor === 'black' && game.turn() === 'b');
}

function currentPerspective() {
  return isMyTurn() ? 'player' : 'opponent';
}

function currentMoveLabel() {
  return isMyTurn() ? '내가 둔 수' : '상대가 둔 수';
}

function activeTimeClasses() {
  const stored = JSON.parse(localStorage.getItem('boardTimeClasses') || '[]');
  return Array.isArray(stored) ? stored : [];
}

function setActiveTimeClasses(values) {
  localStorage.setItem('boardTimeClasses', JSON.stringify(values));
  renderTimeClassFilters();
}

function renderTimeClassFilters() {
  const active = activeTimeClasses();
  document.querySelectorAll('[data-time-class]').forEach(button => {
    const enabled = active.includes(button.dataset.timeClass);
    button.classList.toggle('active', enabled);
    button.setAttribute('aria-pressed', String(enabled));
  });
}

function renderColorSetting() {
  els.myColorWhite.classList.toggle('active', myColor === 'white');
  els.myColorBlack.classList.toggle('active', myColor === 'black');
  els.settingsMyColorWhite.classList.toggle('active', myColor === 'white');
  els.settingsMyColorBlack.classList.toggle('active', myColor === 'black');
  els.moveListTitle.textContent = currentMoveLabel();
  els.databaseTab.textContent = currentMoveLabel();
  els.viewWhite?.classList.toggle('active', orientation === 'white');
  els.viewBlack?.classList.toggle('active', orientation === 'black');
  els.settingsViewWhite.classList.toggle('active', orientation === 'white');
  els.settingsViewBlack.classList.toggle('active', orientation === 'black');
  renderHistoryNavigation();
}

function renderMoveSort() {
  els.moveSortFrequency.classList.toggle('active', moveSort === 'frequency');
  els.moveSortQuality.classList.toggle('active', moveSort === 'quality');
}

function setMoveSort(sort) {
  moveSort = sort === 'quality' ? 'quality' : 'frequency';
  localStorage.setItem('moveSort', moveSort);
  renderMoveSort();
  loadMoves();
}

function setMyColor(color) {
  myColor = color;
  localStorage.setItem('myChessColor', color);
  renderColorSetting();
  loadMoves();
}

function setOrientation(color) {
  orientation = color;
  localStorage.setItem('boardOrientation', color);
  clearSelection();
  board.orientation(color);
  renderColorSetting();
}

function switchPanel(panel) {
  document.querySelectorAll('.board-tabs button').forEach(button => {
    button.classList.toggle('active', button.dataset.panel === panel);
  });
  document.getElementById('historyPanel').classList.toggle('active', panel === 'history');
  document.getElementById('databasePanel').classList.toggle('active', panel === 'database');
}

