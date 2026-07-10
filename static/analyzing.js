const accounts = JSON.parse(localStorage.getItem('chessAccounts') || '[]');
const state = {
  jobId: Number(localStorage.getItem('analysisJobId') || 0),
  pollTimer: null,
  completedRedirected: false,
};

function activeAccounts() {
  return accounts.filter(account => !account.hidden);
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

function hideAllActions() {
  ['runningActions', 'resumeActions', 'completeActions', 'emptyActions'].forEach(id => {
    document.getElementById(id).classList.add('hidden');
  });
}

function updateFlowProgress(isCompleted) {
  const progress = document.querySelector('.flow-progress');
  const analysisStep = document.querySelector('[data-flow-step="analysis"]');
  const completeStep = document.querySelector('[data-flow-step="complete"]');
  if (!analysisStep || !completeStep) return;
  if (progress) {
    progress.classList.toggle('progress-3', !isCompleted);
    progress.classList.toggle('progress-4', isCompleted);
  }
  analysisStep.classList.toggle('is-active', !isCompleted);
  analysisStep.classList.toggle('is-complete', isCompleted);
  completeStep.classList.toggle('is-active', isCompleted);
}

function accountLabel(job) {
  const jobAccounts = job.accounts || [];
  if (!jobAccounts.length) return '-';
  return jobAccounts
    .map(account => account.username || account.provider)
    .join(', ');
}

function renderNoJob(message = '진행 중인 분석 작업이 없습니다.') {
  window.clearTimeout(state.pollTimer);
  state.jobId = 0;
  localStorage.removeItem('analysisJobId');
  updateFlowProgress(false);
  document.getElementById('jobPanel').style.setProperty('--job-progress', '0%');
  document.getElementById('jobPanel').classList.remove('is-complete');
  document.getElementById('progressPiece').textContent = '♙';
  document.getElementById('jobStatus').textContent = message;
  document.getElementById('jobNumbers').textContent = '0 / 0';
  document.getElementById('progressFill').style.width = '0%';
  document.getElementById('progressPercent').textContent = '0%';
  document.getElementById('remainingTime').textContent = '-';
  document.getElementById('jobDepth').textContent = '-';
  document.getElementById('jobThreads').textContent = '-';
  document.getElementById('jobAccounts').textContent = '-';
  document.getElementById('jobError').textContent = '';
  hideAllActions();
  document.getElementById('emptyActions').classList.remove('hidden');
}

function renderJob(job) {
  if (!job) {
    renderNoJob();
    return;
  }

  const progress = Number(job.progress || 0);
  const running = job.status === 'queued' || job.status === 'running';
  const resumable = job.status === 'cancelled' || job.status === 'failed';
  const completed = job.status === 'completed';
  updateFlowProgress(completed);
  document.getElementById('jobPanel').style.setProperty(
    '--job-progress',
    `${Math.max(0, Math.min(100, progress))}%`
  );
  document.getElementById('jobPanel').classList.toggle('is-complete', completed);
  document.getElementById('progressPiece').textContent = completed ? '♕' : '♙';

  document.getElementById('jobStatus').textContent = job.status_label || job.status;
  document.getElementById('jobNumbers').textContent =
    `${job.completed_moves.toLocaleString()} / ${job.total_moves.toLocaleString()}`;
  document.getElementById('progressFill').style.width = `${Math.max(0, Math.min(100, progress))}%`;
  document.getElementById('progressPercent').textContent = `${progress.toFixed(1)}%`;
  document.getElementById('remainingTime').textContent = completed
    ? '분석 완료'
    : resumable
      ? '분석이 멈춰 있습니다.'
      : `남은 시간 ${formatDuration(job.estimated_remaining_seconds)}`;
  document.getElementById('jobDepth').textContent = job.depth;
  document.getElementById('jobThreads').textContent = `${job.threads}개`;
  document.getElementById('jobAccounts').textContent = accountLabel(job);
  document.getElementById('jobError').textContent = job.error_message || '';

  hideAllActions();
  if (running) {
    document.getElementById('runningActions').classList.remove('hidden');
  } else if (resumable) {
    document.getElementById('resumeActions').classList.remove('hidden');
  } else if (completed) {
    document.getElementById('completeActions').classList.remove('hidden');
    if (!state.completedRedirected) {
      state.completedRedirected = true;
      window.setTimeout(() => {
        if (window.checkssNavigate) {
          window.checkssNavigate('/complete');
        } else {
          window.location.href = '/complete';
        }
      }, 650);
    }
  } else {
    document.getElementById('emptyActions').classList.remove('hidden');
  }
}

async function fetchJob(jobId) {
  const response = await fetch(`/api/jobs/${jobId}`);
  if (!response.ok) return null;
  return response.json();
}

async function fetchActiveJob() {
  const response = await fetch('/api/jobs/active', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ accounts: activeAccounts() }),
  });
  if (!response.ok) return null;
  const data = await response.json();
  return data.job || null;
}

async function pollJob() {
  window.clearTimeout(state.pollTimer);
  if (!state.jobId) {
    renderNoJob();
    return;
  }
  try {
    const job = await fetchJob(state.jobId);
    if (!job) {
      renderNoJob();
      return;
    }
    renderJob(job);
    if (job.status === 'queued' || job.status === 'running') {
      state.pollTimer = window.setTimeout(pollJob, 1500);
    }
  } catch (error) {
    document.getElementById('jobError').textContent = error.message;
    state.pollTimer = window.setTimeout(pollJob, 3000);
  }
}

async function loadInitialJob() {
  let job = state.jobId ? await fetchJob(state.jobId) : null;
  if (!job || !['queued', 'running', 'cancelled', 'failed', 'completed'].includes(job.status)) {
    job = await fetchActiveJob();
  }
  if (!job) {
    renderNoJob();
    return;
  }
  state.jobId = job.id;
  localStorage.setItem('analysisJobId', String(job.id));
  renderJob(job);
  if (job.status === 'queued' || job.status === 'running') {
    pollJob();
  }
}

document.getElementById('stopAnalysis').addEventListener('click', async event => {
  if (!state.jobId) return;
  const button = event.currentTarget;
  button.disabled = true;
  button.textContent = '중단 요청 중...';
  try {
    const response = await fetch(`/api/jobs/${state.jobId}/cancel`, {
      method: 'POST',
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '분석을 중단하지 못했습니다.');
    renderJob(data);
  } catch (error) {
    document.getElementById('jobError').textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = '분석 중단';
  }
});

document.getElementById('resumeAnalysis').addEventListener('click', async event => {
  if (!state.jobId) return;
  const button = event.currentTarget;
  button.disabled = true;
  button.textContent = '이어가는 중...';
  try {
    const response = await fetch(`/api/jobs/${state.jobId}/resume`, {
      method: 'POST',
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '분석을 이어가지 못했습니다.');
    renderJob(data);
    pollJob();
  } catch (error) {
    document.getElementById('jobError').textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = '분석 이어하기';
  }
});

loadInitialJob().catch(error => renderNoJob(error.message));
