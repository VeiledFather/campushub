
(() => {
  'use strict';

  const SELECTORS = [
    '#evai-widget', '.evai-widget', '#evai-float',
    '.evai-floating-button', '.evai-launcher',
    '[data-evai-widget]', '#evai-toggle', '.evai-toggle',
    '#evai-assistant-button', '.evai-assistant-button'
  ];

  let launcher = null;
  let dragging = false;
  let moved = false;
  let pointerId = null;
  let startX = 0, startY = 0, left0 = 0, top0 = 0;
  let suppressClickUntil = 0;
  let userMoved = false;
  let resizeTimer = 0;

  const clamp = (n, min, max) => Math.max(min, Math.min(n, max));

  function isVisible(el) {
    if (!el || !el.isConnected) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 &&
      s.display !== 'none' && s.visibility !== 'hidden';
  }

  function findLauncher() {
    for (const selector of SELECTORS) {
      const el = document.querySelector(selector);
      if (isVisible(el)) return el;
    }

    // Find the smallest visible button/link containing the EvAi label.
    const matches = [...document.querySelectorAll(
      'button, a, [role="button"], [aria-label], [title]'
    )].filter(el => {
      const label = [
        el.innerText, el.getAttribute('aria-label'), el.getAttribute('title')
      ].filter(Boolean).join(' ');
      return /\bEvAi\b/i.test(label) && isVisible(el);
    });

    matches.sort((a, b) => {
      const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
      return (ra.width * ra.height) - (rb.width * rb.height);
    });
    return matches[0] || null;
  }

  function setPosition(x, y) {
    if (!launcher) return;
    const r = launcher.getBoundingClientRect();
    const gap = window.matchMedia('(max-width: 600px)').matches ? 12 : 20;
    const maxX = Math.max(gap, window.innerWidth - r.width - gap);
    const maxY = Math.max(gap, window.innerHeight - r.height - gap);

    launcher.style.setProperty('position', 'fixed', 'important');
    launcher.style.setProperty('left', clamp(x, gap, maxX) + 'px', 'important');
    launcher.style.setProperty('top', clamp(y, gap, maxY) + 'px', 'important');
    launcher.style.setProperty('right', 'auto', 'important');
    launcher.style.setProperty('bottom', 'auto', 'important');
    launcher.style.setProperty('margin', '0', 'important');
    launcher.style.setProperty('transform', 'none', 'important');
    launcher.style.setProperty('z-index', '2147483000', 'important');
  }

  function anchorBottomRight() {
    if (!launcher || !isVisible(launcher)) return;
    const gap = window.matchMedia('(max-width: 600px)').matches ? 12 : 20;
    const r = launcher.getBoundingClientRect();

    if (!userMoved) {
      setPosition(window.innerWidth - r.width - gap,
                  window.innerHeight - r.height - gap);
    } else {
      setPosition(r.left, r.top);
    }
  }

  function bind(el) {
    if (!el || el === launcher && el.dataset.evAiResponsiveBound === '1') return;
    launcher = el;
    launcher.dataset.evAiResponsiveBound = '1';

    launcher.style.setProperty('touch-action', 'none', 'important');
    launcher.style.setProperty('cursor', 'grab', 'important');
    launcher.style.setProperty('pointer-events', 'auto', 'important');

    // Start at bottom-right unless the user has already repositioned it.
    anchorBottomRight();

    launcher.addEventListener('pointerdown', e => {
      if (e.pointerType === 'mouse' && e.button !== 0) return;
      if (e.target.closest('input, textarea, select')) return;

      const r = launcher.getBoundingClientRect();
      dragging = true;
      moved = false;
      pointerId = e.pointerId;
      startX = e.clientX;
      startY = e.clientY;
      left0 = r.left;
      top0 = r.top;
      launcher.style.cursor = 'grabbing';
    });

    launcher.addEventListener('click', e => {
      if (Date.now() < suppressClickUntil) {
        e.preventDefault();
        e.stopImmediatePropagation();
      }
    }, true);
  }

  window.addEventListener('pointermove', e => {
    if (!dragging || !launcher || e.pointerId !== pointerId) return;
    const dx = e.clientX - startX;
    const dy = e.clientY - startY;

    if (Math.abs(dx) + Math.abs(dy) > 5) moved = true;
    if (!moved) return;

    userMoved = true;
    setPosition(left0 + dx, top0 + dy);
    e.preventDefault();
  }, {passive: false});

  function endDrag(e) {
    if (!dragging || (e && e.pointerId !== pointerId)) return;
    dragging = false;
    pointerId = null;
    if (launcher) launcher.style.cursor = 'grab';
    if (moved) suppressClickUntil = Date.now() + 350;
  }

  window.addEventListener('pointerup', endDrag);
  window.addEventListener('pointercancel', endDrag);

  function scan() {
    const found = findLauncher();
    if (found && found !== launcher) bind(found);
    else if (found && found.dataset.evAiResponsiveBound !== '1') bind(found);
  }

  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      scan();
      if (launcher) anchorBottomRight();
    }, 100);
  });
  window.addEventListener('orientationchange', () => setTimeout(() => {
    scan();
    if (launcher) anchorBottomRight();
  }, 250));

  if (document.readyState === 'loading')
    document.addEventListener('DOMContentLoaded', scan);
  else scan();

  new MutationObserver(scan).observe(document.documentElement, {
    childList: true, subtree: true
  });
})();
