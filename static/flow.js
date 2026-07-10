function prefersReducedMotion() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

const flowOrder = {
  '/': 1,
  '/analysis': 2,
  '/analyzing': 3,
  '/complete': 4,
  '/board': 5,
};

function normalizedPath(url) {
  const parsed = new URL(url, window.location.origin);
  return parsed.pathname.replace(/\/$/, '') || '/';
}

function slideDirection(url) {
  const from = flowOrder[normalizedPath(window.location.href)] || 0;
  const to = flowOrder[normalizedPath(url)] || from;
  return to < from ? 'backward' : 'forward';
}

const entryDirection = sessionStorage.getItem('checkssSlideDirection');
sessionStorage.removeItem('checkssSlideDirection');
if (entryDirection && !prefersReducedMotion()) {
  const className = `slide-enter-${entryDirection}`;
  document.body.classList.add(className);
  window.setTimeout(() => {
    document.body.classList.remove(className);
  }, 340);
}

window.checkssNavigate = function checkssNavigate(url) {
  if (!url) return;
  if (prefersReducedMotion()) {
    window.location.href = url;
    return;
  }
  const direction = slideDirection(url);
  sessionStorage.setItem('checkssSlideDirection', direction);
  document.body.classList.add(`slide-leave-${direction}`);
  window.setTimeout(() => {
    window.location.href = url;
  }, 220);
};

document.addEventListener('click', event => {
  const link = event.target.closest('a[data-slide-link]');
  if (!link) return;
  if (link.target || link.origin !== window.location.origin) return;
  event.preventDefault();
  window.checkssNavigate(link.href);
});
