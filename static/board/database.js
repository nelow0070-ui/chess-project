function renderMoves(moves) {
  els.moveList.innerHTML = '';
  const sortedMoves = sortMoves(moves);
  els.resultCount.textContent = `${sortedMoves.length}개`;
  if (!sortedMoves.length) {
    els.moveList.innerHTML = `<div class="empty-state">이 포지션에서 저장된 ${currentMoveLabel()}가 없습니다.</div>`;
    return;
  }
  sortedMoves.forEach(move => {
    const item = document.createElement('div');
    item.className = `move-item ${move.type || 'unknown'}`;
    const categories = (move.categories || [])
      .slice(0, 2)
      .map(category => `${category.label} ${category.count}`)
      .join(' · ');
    item.innerHTML = `
      <button class="move-play-button" type="button">
        <strong class="san">${move.san}</strong>
        <span class="type">${move.type === 'brilliant' ? '탁월' : move.type || 'unknown'}</span>
        <span class="meta">${move.count}회 · 승률 ${move.winrate.toFixed(1)}% · ${move.wins}승 ${move.draws}무 ${move.losses}패${categories ? ` · ${escapeHtml(categories)}` : ''}</span>
      </button>
      <button class="move-games-button" type="button">경기</button>
    `;
    item.querySelector('.move-play-button').addEventListener('click', () => {
      clearSelection();
      const played = game.move({
        from: move.uci.slice(0, 2),
        to: move.uci.slice(2, 4),
        promotion: move.uci[4] || 'q',
      });
      if (!played) return;
      recordPlayedMove(played);
      board.position(game.fen(), false);
      refreshPosition();
    });
    item.querySelector('.move-games-button').addEventListener('click', () => {
      openMoveGames(move, game.fen());
    });
    els.moveList.appendChild(item);
  });
}

function qualityRank(type) {
  return {
    brilliant: 5,
    best: 4,
    inaccuracy: 3,
    mistake: 2,
    blunder: 1,
    unknown: 0,
  }[type || 'unknown'] ?? 0;
}

function sortMoves(moves) {
  return [...moves].sort((left, right) => {
    if (moveSort === 'quality') {
      return qualityRank(right.type) - qualityRank(left.type)
        || right.winrate - left.winrate
        || right.count - left.count
        || left.san.localeCompare(right.san);
    }
    return right.count - left.count
      || right.winrate - left.winrate
      || qualityRank(right.type) - qualityRank(left.type)
      || left.san.localeCompare(right.san);
  });
}

async function loadMoves() {
  if (detailMode) return;
  renderColorSetting();
  if (!accounts.length) {
    els.moveList.innerHTML = '<div class="empty-state">먼저 계정을 연결해주세요.</div>';
    return;
  }
  if (!activeAccounts().length) {
    els.moveList.innerHTML = '<div class="empty-state">표시 중인 계정이 없습니다. 설정에서 계정을 다시 표시해주세요.</div>';
    els.resultCount.textContent = '0개';
    return;
  }
  const currentRequest = ++requestId;
  try {
    const response = await fetch(`/moves?${accountQuery()}`);
    const moves = await response.json();
    if (currentRequest === requestId) renderMoves(moves);
  } catch {
    if (currentRequest === requestId) {
      els.moveList.innerHTML = '<div class="empty-state">수를 불러오지 못했습니다.</div>';
    }
  }
}

function clearAnalysisPoll() {
  if (analysisPollTimer) window.clearTimeout(analysisPollTimer);
  analysisPollTimer = null;
}

async function openMoveGames(move, fen) {
  detailMode = true;
  clearAnalysisPoll();
  switchPanel('database');
  els.moveList.innerHTML = '<div class="empty-state compact">경기 목록을 불러오는 중입니다.</div>';
  els.resultCount.textContent = '';
  try {
    const response = await fetch(`/api/move-games?${accountQuery(fen)}&move=${encodeURIComponent(move.uci)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '경기를 불러오지 못했습니다.');
    renderMoveGames(move, data.games || []);
  } catch (error) {
    els.moveList.innerHTML = `
      <div class="detail-heading">
        <button type="button" class="back-button" data-detail-back>← 수 목록</button>
      </div>
      <div class="empty-state">${escapeHtml(error.message)}</div>
    `;
  }
}

function renderMoveGames(move, games) {
  els.resultCount.textContent = `${games.length}게임`;
  els.moveList.innerHTML = `
    <div class="detail-heading">
      <button type="button" class="back-button" data-detail-back>← 수 목록</button>
      <strong>${escapeHtml(move.san)} 경기</strong>
    </div>
    <div class="game-detail-list">
      ${games.length ? games.map(gameItem => `
        <button type="button" class="game-row" data-game-id="${gameItem.game_id}">
          <span>
            <strong>${escapeHtml(gameItem.opponent)}</strong>
            <em>${escapeHtml(gameItem.date || '-')} · ${escapeHtml(gameItem.time_class_label)} · ${escapeHtml(gameItem.player_result)}</em>
          </span>
          <span>${escapeHtml(gameItem.white)} - ${escapeHtml(gameItem.black)}</span>
        </button>
      `).join('') : '<div class="empty-state compact">이 수가 나온 경기가 없습니다.</div>'}
    </div>
  `;
}

async function openGameAnalysis(gameId) {
  detailMode = true;
  clearAnalysisPoll();
  els.moveList.innerHTML = '<div class="empty-state compact">경기 분석을 준비하는 중입니다.</div>';
  try {
    const depth = Number(localStorage.getItem('analysisDepth') || '14');
    const request = await fetch(`/api/games/${gameId}/analysis`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ depth: Math.max(14, depth) }),
    });
    const requestData = await request.json();
    if (!request.ok) throw new Error(requestData.error || '분석을 시작하지 못했습니다.');
    await loadGameAnalysis(gameId, requestData.job);
  } catch (error) {
    els.moveList.innerHTML = `
      <div class="detail-heading">
        <button type="button" class="back-button" data-detail-back>← 수 목록</button>
      </div>
      <div class="empty-state">${escapeHtml(error.message)}</div>
    `;
  }
}

async function loadGameAnalysis(gameId, job = null) {
  const response = await fetch(`/api/games/${gameId}/analysis`);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '분석을 불러오지 못했습니다.');
  renderGameAnalysis(data, job);
  if (!data.ready && job?.id) {
    analysisPollTimer = window.setTimeout(async () => {
      try {
        const jobResponse = await fetch(`/api/jobs/${job.id}`);
        const nextJob = await jobResponse.json();
        await loadGameAnalysis(gameId, nextJob);
      } catch {
        analysisPollTimer = null;
      }
    }, 1600);
  }
}

function moveQualityLabel(type) {
  return {
    brilliant: '탁월',
    best: '최선',
    inaccuracy: '부정확',
    mistake: '실수',
    blunder: '블런더',
    illegal: '불법수',
    unknown: '대기',
  }[type || 'unknown'] || type;
}

function renderGameAnalysis(data, job) {
  const gameInfo = data.game;
  const progress = job && !data.ready
    ? `<div class="analysis-wait">분석 중 ${job.completed_moves}/${job.total_moves} · 깊이 ${job.depth}</div>`
    : '';
  els.resultCount.textContent = data.ready ? '완료' : '분석 중';
  els.moveList.innerHTML = `
    <div class="detail-heading">
      <button type="button" class="back-button" data-detail-back>← 수 목록</button>
      <strong>${escapeHtml(gameInfo.opponent)}전</strong>
    </div>
    <div class="game-summary">
      <span>${escapeHtml(gameInfo.date || '-')} · ${escapeHtml(gameInfo.time_class_label)} · ${escapeHtml(gameInfo.player_result)}</span>
      <strong>${escapeHtml(gameInfo.white)} - ${escapeHtml(gameInfo.black)}</strong>
      ${progress}
    </div>
    <div class="single-game-analysis">
      ${data.moves.map(move => {
        const needsLine = ['brilliant', 'mistake', 'blunder'].includes(move.mistake_type);
        const bestLine = (move.best_line || []).join(' ');
        const replyLine = (move.reply_line || []).join(' ');
        return `
          <div class="analysis-move ${move.mistake_type}">
            <div>
              <strong>${move.move_number}${move.turn === 'white' ? '.' : '...'} ${escapeHtml(move.san)}</strong>
              <span>${moveQualityLabel(move.mistake_type)} · 손실 ${move.eval_diff == null ? '-' : (move.eval_diff / 100).toFixed(2)}</span>
            </div>
            <p>최선수 ${escapeHtml(move.best_san || '-')}</p>
            ${needsLine && bestLine ? `<p>추천 수순 ${escapeHtml(bestLine)}</p>` : ''}
            ${needsLine && replyLine ? `<p>이후 대응 ${escapeHtml(replyLine)}</p>` : ''}
          </div>
        `;
      }).join('')}
    </div>
  `;
}

async function evaluatePosition() {
  els.evalLabel.textContent = '...';
  try {
    const response = await fetch(`/eval?fen=${encodeURIComponent(game.fen())}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error);
    const percent = data.type === 'mate'
      ? (data.mate > 0 ? 100 : 0)
      : 50 + Math.max(-800, Math.min(800, data.cp)) / 16;
    els.evalFill.style.height = `${percent}%`;
    els.evalLabel.classList.toggle('black-advantage', percent < 50);
    els.evalLabel.textContent = data.type === 'mate'
      ? `${data.mate > 0 ? '' : '-'}M${Math.abs(data.mate)}`
      : `${data.cp > 0 ? '+' : ''}${(data.cp / 100).toFixed(1)}`;
  } catch {
    els.evalLabel.textContent = '--';
    els.evalLabel.classList.remove('black-advantage');
  }
}

