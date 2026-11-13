// Global WebGL Lifecycle Controllers to maximize GPU/CPU efficiency
window.pauseUnicornStudio = function () {
  try {
    if (window.__unicornScenes && Array.isArray(window.__unicornScenes)) {
      window.__unicornScenes.forEach(function (scene) {
        if (scene && scene.curtain && typeof scene.curtain.disableDrawing === 'function') {
          scene.curtain.disableDrawing();
        } else if (scene && typeof scene.disable === 'function') {
          scene.disable();
        }
      });
    }
  } catch (e) {
    console.debug('[UnicornStudio pause]', e);
  }
};

window.resumeUnicornStudio = function () {
  try {
    if (typeof currentMainTab === 'undefined' || currentMainTab === 'studio') {
      if (!document.hidden && window.__unicornScenes && Array.isArray(window.__unicornScenes)) {
        window.__unicornScenes.forEach(function (scene) {
          if (scene && scene.curtain && typeof scene.curtain.enableDrawing === 'function') {
            scene.curtain.enableDrawing();
            if (typeof scene.curtain.resize === 'function') {
              scene.curtain.resize();
            }
          } else if (scene && typeof scene.enable === 'function') {
            scene.enable();
          }
        });
      }
    }
  } catch (e) {
    console.debug('[UnicornStudio resume]', e);
  }
};

// Automatically pause WebGL rendering when browser tab is inactive / hidden
document.addEventListener('visibilitychange', function () {
  if (document.hidden) {
    window.pauseUnicornStudio();
  } else if (typeof currentMainTab !== 'undefined' && currentMainTab === 'studio') {
    window.resumeUnicornStudio();
  }
});

!function () {
  if (!window.UnicornStudio) {
    window.UnicornStudio = { isInitialized: !1 };
    var i = document.createElement("script");
    i.src = "https://cdn.jsdelivr.net/gh/hiunicornstudio/unicornstudio.js@v1.4.30/dist/unicornStudio.umd.js";
    i.onload = function () {
      if (!window.UnicornStudio.isInitialized && window.UnicornStudio.init) {
        window.UnicornStudio.init().then(function (scenes) {
          window.__unicornScenes = scenes;
          if (window.UnicornStudio && typeof window.UnicornStudio.unbindEvents === 'function') {
            window.UnicornStudio.unbindEvents();
          }
          if (scenes && Array.isArray(scenes)) {
            scenes.forEach(function (scene) {
              if (scene && scene.interactivity && scene.interactivity.mouse) {
                scene.interactivity.mouse.disabled = true;
              }
            });
          }
          // If loaded while on non-studio tab, pause WebGL drawing immediately
          if (typeof currentMainTab !== 'undefined' && currentMainTab !== 'studio') {
            window.pauseUnicornStudio();
          }
        }).catch(function (e) {
          console.warn('[UnicornStudio]', e);
        });
        window.UnicornStudio.isInitialized = !0;
      }
    };
    (document.head || document.body).appendChild(i);
  }
}();

// Guide Script Functions
const GUIDE_DOCS_ORDER = [
  {
    id: 'workflow',
    label: 'Workflow',
    title: 'Understand the Luna workflow',
    subtitle: 'See how media moves from a source URL to ready-to-use videos, audio, and clips. Click any step to view technical details.',
  },
  {
    id: 'modes',
    label: 'Features & Modes',
    title: 'Features & Modes',
    subtitle: 'Compare the four download, trimming, and AI clipping modes to pick what fits your content.',
  },
  {
    id: 'setup',
    label: 'Setup & Requirements',
    title: 'Setup & Requirements',
    subtitle: 'What Luna sets up automatically via install.ps1, install.sh, or Docker, and what is optional.',
  },
  {
    id: 'vault',
    label: 'Media Vault',
    title: 'Media Vault',
    subtitle: 'Luna organizes outputs into structured category folders, customizable anytime from Move Folder in Settings.',
  },
  {
    id: 'faq',
    label: 'FAQ',
    title: 'FAQ & Troubleshooting',
    subtitle: 'Quick answers to common setup, download, and configuration questions.',
  },
];

function updateGuidePager(tabId) {
  const idx = GUIDE_DOCS_ORDER.findIndex(item => item.id === tabId);
  const currentItem = GUIDE_DOCS_ORDER[idx] || GUIDE_DOCS_ORDER[0];
  const breadcrumb = document.getElementById('guideBreadcrumbCurrent');
  const titleEl = document.getElementById('guidePageTitle');
  const subtitleEl = document.getElementById('guidePageSubtitle');

  if (breadcrumb && currentItem) {
    breadcrumb.textContent = currentItem.label;
  }
  if (titleEl && currentItem) {
    titleEl.textContent = currentItem.title;
  }
  if (subtitleEl && currentItem) {
    subtitleEl.textContent = currentItem.subtitle;
  }

  const prevBtn = document.getElementById('guidePrevBtn');
  const prevTitle = document.getElementById('guidePrevTitle');
  const nextBtn = document.getElementById('guideNextBtn');
  const nextTitle = document.getElementById('guideNextTitle');

  if (prevBtn && prevTitle) {
    const prev = idx > 0 ? GUIDE_DOCS_ORDER[idx - 1] : null;
    if (prev) {
      prevBtn.classList.remove('invisible', 'pointer-events-none');
      prevBtn.dataset.targetTab = prev.id;
      prevTitle.textContent = prev.label;
    } else {
      prevBtn.classList.add('invisible', 'pointer-events-none');
      prevBtn.dataset.targetTab = '';
    }
  }

  if (nextBtn && nextTitle) {
    const next = idx >= 0 && idx < GUIDE_DOCS_ORDER.length - 1 ? GUIDE_DOCS_ORDER[idx + 1] : null;
    if (next) {
      nextBtn.classList.remove('invisible', 'pointer-events-none');
      nextBtn.dataset.targetTab = next.id;
      nextTitle.textContent = next.label;
    } else {
      nextBtn.classList.add('invisible', 'pointer-events-none');
      nextBtn.dataset.targetTab = '';
    }
  }
}

function updateGuidePill(tab, immediate = false) {
  const pill = document.getElementById('tabsPill');
  if (!pill || !tab) return;
  if (immediate) {
    pill.style.transition = 'none';
    pill.style.transform = `translateX(${tab.offsetLeft}px)`;
    pill.style.width = `${tab.offsetWidth}px`;
    void pill.offsetHeight;
    pill.style.transition = '';
  } else {
    pill.style.transform = `translateX(${tab.offsetLeft}px)`;
    pill.style.width = `${tab.offsetWidth}px`;
  }
}

function switchGuideTab(tabId, btn, shouldScroll = false) {
  const bar = document.getElementById('guideTabsBar');
  let targetBtn = btn;
  if (bar) {
    if (!targetBtn || !bar.contains(targetBtn)) {
      targetBtn = bar.querySelector(`[data-guide-tab="${tabId}"]`);
    }
    bar.querySelectorAll('[data-guide-tab]').forEach(b => {
      const isSelected = (b === targetBtn) || b.dataset.guideTab === tabId;
      b.setAttribute('aria-selected', isSelected ? 'true' : 'false');
      b.classList.toggle('active', isSelected);
    });
  }
  updateGuidePill(targetBtn, false);

  document.querySelectorAll('.guide-tab-pane').forEach(p => p.classList.add('hidden'));
  const activePane = document.getElementById(`tab-${tabId}`);
  if (activePane) {
    activePane.classList.remove('hidden');
  }
  updateGuidePager(tabId);
  if (shouldScroll) {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }
}

function stepGuideTab(direction) {
  const btn = direction < 0
    ? document.getElementById('guidePrevBtn')
    : document.getElementById('guideNextBtn');
  const nextId = btn && btn.dataset ? btn.dataset.targetTab : '';
  if (nextId) {
    switchGuideTab(nextId, null, true);
  }
}

function initGuidePill() {
  const activeBtn = document.querySelector('#guideTabsBar [aria-selected="true"]')
    || document.querySelector('#guideTabsBar [data-guide-tab]');
  if (activeBtn) {
    updateGuidePill(activeBtn, true);
    if (activeBtn.dataset && activeBtn.dataset.guideTab) {
      updateGuidePager(activeBtn.dataset.guideTab);
    }
  }
}

function toggleTaskRow(btn) {
  const row = btn.closest('.task-row');
  if (!row) return;
  const isOpen = row.classList.toggle('is-open');
  btn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
}

function toggleFaq(element) {
  const p = element.querySelector('p');
  const chevron = element.querySelector('.faq-chevron');
  if (!p) return;
  const isHidden = p.classList.contains('hidden');
  if (isHidden) {
    p.classList.remove('hidden');
    if (chevron) chevron.style.transform = 'rotate(180deg)';
  } else {
    p.classList.add('hidden');
    if (chevron) chevron.style.transform = 'rotate(0deg)';
  }
}

function copySnippet(text, triggerEl) {
  navigator.clipboard.writeText(text).then(() => {
    const btn = triggerEl.classList.contains('spell-copy-btn') 
      ? triggerEl 
      : triggerEl.querySelector('.spell-copy-btn');
    if (btn) {
      btn.classList.add('is-copied');
      setTimeout(() => btn.classList.remove('is-copied'), 1600);
    }
  });
}
