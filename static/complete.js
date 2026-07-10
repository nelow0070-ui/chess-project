const accounts = JSON.parse(localStorage.getItem('chessAccounts') || '[]');
const jobId = Number(localStorage.getItem('analysisJobId') || 0);

function activeAccounts() {
  return accounts.filter(account => !account.hidden);
}

function accountLabel(job) {
  const jobAccounts = job?.accounts || activeAccounts();
  if (!jobAccounts.length) return '-';
  return jobAccounts
    .map(account => account.username || account.provider)
    .join(', ');
}

function renderComplete(job) {
  document.getElementById('completeMoves').textContent = job
    ? `${Number(job.completed_moves || 0).toLocaleString()}수`
    : '-';
  document.getElementById('completeDepth').textContent = job?.depth || localStorage.getItem('analysisDepth') || '-';
  document.getElementById('completeAccounts').textContent = accountLabel(job);
}

async function loadCompleteJob() {
  if (!jobId) {
    renderComplete(null);
    return;
  }

  const response = await fetch(`/api/jobs/${jobId}`);
  if (!response.ok) {
    renderComplete(null);
    return;
  }
  const job = await response.json();
  if (job.status && job.status !== 'completed') {
    if (window.checkssNavigate) {
      window.checkssNavigate('/analyzing');
    } else {
      window.location.href = '/analyzing';
    }
    return;
  }
  renderComplete(job);
}

loadCompleteJob().catch(error => {
  document.getElementById('completeError').textContent = error.message;
  renderComplete(null);
});
