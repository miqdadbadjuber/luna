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

function switchGuideTab(tabId, btn) {
  const bar = document.getElementById('guideTabsBar');
  if (bar) {
    bar.querySelectorAll('.t-tab').forEach(b => {
      const isSelected = (b === btn);
      b.setAttribute('aria-selected', isSelected ? 'true' : 'false');
      b.classList.toggle('active', isSelected);
    });
  }
  updateGuidePill(btn, false);

  document.querySelectorAll('.guide-tab-pane').forEach(p => p.classList.add('hidden'));
  const activePane = document.getElementById(`tab-${tabId}`);
  if (activePane) {
    activePane.classList.remove('hidden');
  }
}

function initGuidePill() {
  const activeBtn = document.querySelector('#guideTabsBar .t-tab[aria-selected="true"]') || document.querySelector('#guideTabsBar .t-tab');
  if (activeBtn) {
    updateGuidePill(activeBtn, true);
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
