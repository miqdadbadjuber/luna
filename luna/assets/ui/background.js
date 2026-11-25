// Studio Background Registry & WebGL Lifecycle Controllers
const LUNA_STUDIO_BG_STORAGE_KEY = 'luna_studio_bg';
const LUNA_DEFAULT_STUDIO_BG = 'obsidian';

const LUNA_STUDIO_BACKGROUNDS = [
  {
    id: 'obsidian',
    name: 'Obsidian',
    badge: 'Default',
    type: 'obsidian',
    css: '#0d0d0d',
    preview: '#0d0d0d',
  },
  {
    id: 'lunar-waves',
    name: 'Lunar Waves',
    badge: 'Animated',
    type: 'webgl',
    css: '#000000',
    preview: 'radial-gradient(circle at 50% 95%, rgba(160, 160, 160, 0.28), transparent 48%), linear-gradient(155deg, rgba(255, 255, 255, 0.14) 0%, rgba(255, 255, 255, 0.03) 34%, transparent 52%, rgba(255, 255, 255, 0.11) 70%, transparent 88%), #050505',
  },
  {
    id: 'crimson-horizon',
    name: 'Crimson Horizon',
    badge: 'Static',
    type: 'css',
    css: 'radial-gradient(125% 125% at 50% 100%, #000000 40%, #2b0707 100%)',
  },
  {
    id: 'emerald-horizon',
    name: 'Emerald Horizon',
    badge: 'Static',
    type: 'css',
    css: 'radial-gradient(125% 125% at 50% 90%, #000000 40%, #072607 100%)',
  },
  {
    id: 'dark-horizon',
    name: 'Dark Horizon',
    badge: 'Static',
    type: 'css',
    css: 'radial-gradient(125% 125% at 50% 90%, #000000 40%, #0d1a36 100%)',
  },
  {
    id: 'crimson-abyss',
    name: 'Crimson Abyss',
    badge: 'Static',
    type: 'css',
    css: 'radial-gradient(125% 125% at 50% 10%, #000000 40%, #2b0707 100%)',
  },
  {
    id: 'emerald-abyss',
    name: 'Emerald Abyss',
    badge: 'Static',
    type: 'css',
    css: 'radial-gradient(125% 125% at 50% 10%, #000000 40%, #072607 100%)',
  },
  {
    id: 'violet-abyss',
    name: 'Violet Abyss',
    badge: 'Static',
    type: 'css',
    css: 'radial-gradient(125% 125% at 50% 10%, #000000 40%, #2b092b 100%)',
  },
  {
    id: 'ocean-glow',
    name: 'Ocean Glow',
    badge: 'Static',
    type: 'css',
    css: 'radial-gradient(ellipse 80% 60% at 50% 0%, rgba(6, 182, 212, 0.25), transparent 70%), #000000',
  },
  {
    id: 'copper-forge',
    name: 'Copper Forge',
    badge: 'Static',
    type: 'css',
    css: 'radial-gradient(ellipse 80% 60% at 50% 0%, rgba(249, 115, 22, 0.25), transparent 70%), #000000',
  },
  {
    id: 'stellar-mist',
    name: 'Stellar Mist',
    badge: 'Static',
    type: 'css',
    css: 'radial-gradient(ellipse 140% 50% at 15% 60%, rgba(124, 58, 237, 0.11), transparent 48%), radial-gradient(ellipse 90% 80% at 85% 25%, rgba(245, 101, 101, 0.09), transparent 58%), radial-gradient(ellipse 120% 65% at 40% 90%, rgba(34, 197, 94, 0.13), transparent 52%), radial-gradient(ellipse 100% 45% at 70% 5%, rgba(251, 191, 36, 0.07), transparent 42%), radial-gradient(ellipse 80% 75% at 90% 80%, rgba(168, 85, 247, 0.10), transparent 55%), #000000',
  },
  {
    id: 'cosmic-nebula',
    name: 'Cosmic Nebula',
    badge: 'Static',
    type: 'css',
    css: 'radial-gradient(ellipse 110% 70% at 25% 80%, rgba(147, 51, 234, 0.12), transparent 55%), radial-gradient(ellipse 130% 60% at 75% 15%, rgba(59, 130, 246, 0.10), transparent 65%), radial-gradient(ellipse 80% 90% at 20% 30%, rgba(236, 72, 153, 0.14), transparent 50%), radial-gradient(ellipse 100% 40% at 60% 70%, rgba(16, 185, 129, 0.08), transparent 45%), #000000',
  },
  {
    id: 'prismatic-aurora',
    name: 'Prismatic Aurora',
    badge: 'Static',
    type: 'css',
    css: 'radial-gradient(ellipse 120% 80% at 70% 20%, rgba(255, 20, 147, 0.15), transparent 50%), radial-gradient(ellipse 100% 60% at 30% 10%, rgba(0, 255, 255, 0.12), transparent 60%), radial-gradient(ellipse 90% 70% at 50% 0%, rgba(138, 43, 226, 0.18), transparent 65%), radial-gradient(ellipse 110% 50% at 80% 30%, rgba(255, 215, 0, 0.08), transparent 40%), #000000',
  },
];

window.LUNA_STUDIO_BACKGROUNDS = LUNA_STUDIO_BACKGROUNDS;

function __resolveStudioBackground(bgId) {
  const raw = String(bgId || '').trim().toLowerCase();
  const match = LUNA_STUDIO_BACKGROUNDS.find(function (item) {
    return item.id === raw;
  });
  return match || LUNA_STUDIO_BACKGROUNDS[0];
}

function __readCachedStudioBackground() {
  try {
    return __resolveStudioBackground(window.localStorage.getItem(LUNA_STUDIO_BG_STORAGE_KEY)).id;
  } catch (e) {
    return LUNA_DEFAULT_STUDIO_BG;
  }
}

let __activeStudioBackgroundId = __readCachedStudioBackground();
let __unicornScriptRequested = false;
let __unicornLastViewport = {
  w: window.innerWidth,
  h: window.innerHeight,
  dpr: window.devicePixelRatio || 1,
};
let __unicornNeedsResize = false;
let __unicornNeedsRefresh = false;
let __unicornResizeTimer = null;
let __unicornBootPending = false;

window.getActiveStudioBackground = function () {
  return __activeStudioBackgroundId;
};

function __isWebGLBackgroundActive() {
  return __activeStudioBackgroundId === 'lunar-waves';
}

(function installUnicornWebGLShim() {
  if (window.__lunaWebGLShimInstalled || typeof HTMLCanvasElement === 'undefined') return;
  window.__lunaWebGLShimInstalled = true;
  const origGetContext = HTMLCanvasElement.prototype.getContext;
  if (typeof origGetContext !== 'function') return;

  HTMLCanvasElement.prototype.getContext = function (type, attrs) {
    let ctx = origGetContext.call(this, type, attrs);
    if (
      !ctx &&
      (type === 'webgl2' || type === 'webgl' || type === 'experimental-webgl') &&
      attrs &&
      attrs.failIfMajorPerformanceCaveat
    ) {
      ctx = origGetContext.call(
        this,
        type,
        Object.assign({}, attrs, { failIfMajorPerformanceCaveat: false })
      );
    }
    return ctx;
  };
})();

function __isStudioTabActive() {
  if (document.documentElement.hasAttribute('data-init-route')) {
    return false;
  }
  if (document.body && (
    document.body.classList.contains('tab-vault') ||
    document.body.classList.contains('tab-settings') ||
    document.body.classList.contains('tab-guide')
  )) {
    return false;
  }
  if (typeof currentMainTab !== 'undefined') {
    return currentMainTab === 'studio';
  }
  return true;
}

function __keepUnicornPlanesDrawable(scene, refreshTextures) {
  if (!scene) return;
  if (scene.curtain && Array.isArray(scene.curtain.planes)) {
    scene.curtain.planes.forEach(function (plane) {
      if (plane) {
        plane._canDraw = true;
      }
    });
  }
  if (refreshTextures && Array.isArray(scene.layers)) {
    scene.layers.forEach(function (layer) {
      const tex = layer && layer.preloadedCanvasTexture;
      if (tex && typeof tex.needUpdate === 'function') {
        tex.needUpdate();
      }
    });
  }
  if (scene.curtain && typeof scene.curtain.needRender === 'function') {
    scene.curtain.needRender();
  }
}

function __bindSceneContextHandlers(scene) {
  const canvas = scene && scene.curtain ? scene.curtain.canvas : null;
  if (!canvas || (canvas.dataset && canvas.dataset.lunaContextBound === '1')) {
    return;
  }
  if (canvas.dataset) {
    canvas.dataset.lunaContextBound = '1';
  }
  canvas.addEventListener('webglcontextlost', function () {
    __unicornNeedsRefresh = true;
  });
  canvas.addEventListener('webglcontextrestored', function () {
    __unicornNeedsRefresh = true;
    if (__isWebGLBackgroundActive() && __isStudioTabActive() && !document.hidden) {
      requestAnimationFrame(function () {
        window.resumeUnicornStudio();
      });
    }
  });
}

function __initUnicornStudioNow() {
  if (!__isWebGLBackgroundActive()) {
    __unicornBootPending = false;
    return;
  }
  if (!window.UnicornStudio || window.UnicornStudio.isInitialized || typeof window.UnicornStudio.init !== 'function') {
    return;
  }
  if (!__isStudioTabActive()) {
    __unicornBootPending = true;
    return;
  }
  __unicornBootPending = false;
  window.UnicornStudio.isInitialized = true;
  window.UnicornStudio.init().then(function (scenes) {
    window.__unicornScenes = scenes;
    if (window.UnicornStudio && typeof window.UnicornStudio.unbindEvents === 'function') {
      window.UnicornStudio.unbindEvents();
    }
    if (scenes && Array.isArray(scenes)) {
      scenes.forEach(function (scene) {
        if (!scene) return;
        if (scene.interactivity && scene.interactivity.mouse) {
          scene.interactivity.mouse.disabled = true;
        }
        scene.disablePlanes = function () {};
        __keepUnicornPlanesDrawable(scene, false);
        __bindSceneContextHandlers(scene);
      });
    }
    if (!__isWebGLBackgroundActive() || !__isStudioTabActive() || document.hidden) {
      window.pauseUnicornStudio();
    } else {
      const curtainsCanvas = document.getElementById('curtains-canvas');
      if (curtainsCanvas) {
        curtainsCanvas.style.removeProperty('display');
        curtainsCanvas.style.opacity = '1';
        curtainsCanvas.style.visibility = 'visible';
      }
      window.resumeUnicornStudio();
    }
  }).catch(function (e) {
    window.UnicornStudio.isInitialized = false;
    console.warn('[StudioBackground]', e);
  });
}

function __ensureUnicornStudioLoaded() {
  if (!__isWebGLBackgroundActive()) return;
  if (window.UnicornStudio && typeof window.UnicornStudio.init === 'function') {
    __initUnicornStudioNow();
    return;
  }
  if (__unicornScriptRequested) return;
  __unicornScriptRequested = true;

  const cdnUrls = [
    'https://cdn.jsdelivr.net/gh/hiunicornstudio/unicornstudio.js@v1.4.30/dist/unicornStudio.umd.js',
    'https://fastly.jsdelivr.net/gh/hiunicornstudio/unicornstudio.js@v1.4.30/dist/unicornStudio.umd.js',
  ];

  function loadUnicornScript(attempt) {
    if (attempt >= cdnUrls.length) {
      __unicornScriptRequested = false;
      return;
    }
    const s = document.createElement('script');
    s.src = cdnUrls[attempt];
    s.onload = function () {
      __initUnicornStudioNow();
    };
    s.onerror = function () {
      loadUnicornScript(attempt + 1);
    };
    (document.head || document.body).appendChild(s);
  }

  if (!window.UnicornStudio) {
    window.UnicornStudio = { isInitialized: false };
  }
  loadUnicornScript(0);
}

window.pauseUnicornStudio = function () {
  try {
    if (window.__unicornScenes && Array.isArray(window.__unicornScenes)) {
      window.__unicornScenes.forEach(function (scene) {
        if (!scene) return;
        scene.paused = true;
        if (scene.curtain && typeof scene.curtain.disableDrawing === 'function') {
          scene.curtain.disableDrawing();
        } else if (typeof scene.disable === 'function') {
          scene.disable();
        }
      });
    }
  } catch (e) {
    console.debug('[StudioBackground pause]', e);
  }
};

window.resumeUnicornStudio = function () {
  if (!__isWebGLBackgroundActive()) {
    window.pauseUnicornStudio();
    return;
  }
  if (__isStudioTabActive()) {
    if (!window.UnicornStudio || typeof window.UnicornStudio.init !== 'function') {
      __ensureUnicornStudioLoaded();
      return;
    }
    if (__unicornBootPending || !window.UnicornStudio.isInitialized) {
      __initUnicornStudioNow();
    }
  }
  try {
    if (__isStudioTabActive() && !document.hidden) {
      if (window.__unicornScenes && Array.isArray(window.__unicornScenes)) {
        const vw = window.innerWidth;
        const vh = window.innerHeight;
        const dpr = window.devicePixelRatio || 1;
        const viewportChanged = (
          __unicornNeedsResize ||
          vw !== __unicornLastViewport.w ||
          vh !== __unicornLastViewport.h ||
          dpr !== __unicornLastViewport.dpr
        );
        window.__unicornScenes.forEach(function (scene) {
          if (!scene) return;
          scene.paused = false;
          scene.disablePlanes = function () {};
          if (scene.curtain && typeof scene.curtain.enableDrawing === 'function') {
            scene.curtain.enableDrawing();
          } else if (typeof scene.enable === 'function') {
            scene.enable();
          }
          const canvas = scene.curtain ? scene.curtain.canvas : null;
          const needsZeroFix = Boolean(canvas && (canvas.width === 0 || canvas.height === 0));
          __keepUnicornPlanesDrawable(scene, true);
          if (__unicornNeedsRefresh || viewportChanged || needsZeroFix) {
            if (typeof scene.refresh === 'function') {
              scene.refresh();
            } else if (typeof scene.resize === 'function') {
              scene.resize();
            } else if (scene.curtain && typeof scene.curtain.resize === 'function') {
              scene.curtain.resize();
            }
          }
        });
        __unicornLastViewport = { w: vw, h: vh, dpr: dpr };
        __unicornNeedsResize = false;
        __unicornNeedsRefresh = false;
      }
    }
  } catch (e) {
    console.debug('[StudioBackground resume]', e);
  }
};

window.applyStudioBackground = function (bgId, options) {
  const preset = __resolveStudioBackground(bgId);
  __activeStudioBackgroundId = preset.id;
  if (!options || options.persistCache !== false) {
    try {
      window.localStorage.setItem(LUNA_STUDIO_BG_STORAGE_KEY, preset.id);
    } catch (e) {}
  }

  const bgContainer = document.getElementById('studioBackgroundContainer');
  const cssLayer = document.getElementById('studioBgCssLayer');
  const usNode = bgContainer ? bgContainer.querySelector('[data-us-project]') : null;
  const curtainsCanvas = document.getElementById('curtains-canvas');

  if (bgContainer) {
    bgContainer.setAttribute('data-bg-id', preset.id);
    bgContainer.setAttribute('data-bg-type', preset.type);
  }

  if (preset.type === 'webgl') {
    if (cssLayer) {
      cssLayer.style.background = '#000000';
      cssLayer.style.opacity = '0';
    }
    if (usNode) {
      usNode.style.display = '';
    }
    if (curtainsCanvas && __isStudioTabActive()) {
      curtainsCanvas.style.removeProperty('display');
      curtainsCanvas.style.opacity = '1';
      curtainsCanvas.style.visibility = 'visible';
    }
    __ensureUnicornStudioLoaded();
    if (__isStudioTabActive()) {
      window.resumeUnicornStudio();
    }
  } else {
    window.pauseUnicornStudio();
    if (usNode) {
      usNode.style.display = 'none';
    }
    if (curtainsCanvas) {
      curtainsCanvas.style.opacity = '0';
      curtainsCanvas.style.visibility = 'hidden';
      curtainsCanvas.style.display = 'none';
    }
    if (cssLayer) {
      cssLayer.style.background = preset.css;
      cssLayer.style.opacity = '1';
    }
  }

  return preset;
};

window.addEventListener('resize', function () {
  if (!__isWebGLBackgroundActive()) return;
  __unicornNeedsResize = true;
  if (__unicornResizeTimer) clearTimeout(__unicornResizeTimer);
  __unicornResizeTimer = setTimeout(function () {
    __unicornResizeTimer = null;
    if (!document.hidden && __isStudioTabActive()) {
      window.resumeUnicornStudio();
    }
  }, 120);
});

document.addEventListener('visibilitychange', function () {
  if (!__isWebGLBackgroundActive()) return;
  if (document.hidden) {
    window.pauseUnicornStudio();
  } else if (__isStudioTabActive()) {
    window.resumeUnicornStudio();
  }
});

window.addEventListener('pageshow', function (event) {
  if (!__isWebGLBackgroundActive()) return;
  if (event && event.persisted) {
    __unicornNeedsRefresh = true;
  }
  if (!document.hidden && __isStudioTabActive()) {
    window.resumeUnicornStudio();
  }
});

window.addEventListener('pagehide', function () {
  window.pauseUnicornStudio();
});

// Apply initial background immediately without loading WebGL unless lunar-waves is selected
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', function () {
    window.applyStudioBackground(__activeStudioBackgroundId, { persistCache: false });
  });
} else {
  window.applyStudioBackground(__activeStudioBackgroundId, { persistCache: false });
}

// Guide Script Functions
const GUIDE_DOCS_ORDER = [
  {
    id: 'wf-youtube',
    label: 'YouTube',
    title: 'YouTube Workflow',
    subtitle: 'Select a YouTube mode below to trace every node from URL input to Workspace output.',
  },
  {
    id: 'wf-instagram',
    label: 'Instagram Reels',
    title: 'Instagram Reels Workflow',
    subtitle: 'How Luna validates and downloads Instagram Reels directly to your local Workspace.',
  },
  {
    id: 'wf-tiktok',
    label: 'TikTok',
    title: 'TikTok Workflow',
    subtitle: 'Select Video MP4 or Audio MP3 to inspect each processing node from link to saved output.',
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
    label: 'Workspace',
    title: 'Workspace',
    subtitle: 'Luna organizes outputs into structured category folders, customizable anytime from Move Folder in Settings.',
  },
  {
    id: 'faq',
    label: 'FAQ',
    title: 'FAQ & Troubleshooting',
    subtitle: 'Quick answers to common setup, download, and configuration questions.',
  },
];

const GUIDE_WORKFLOWS = {
  youtube: {
    canvasId: 'wfYoutubeCanvas',
    stepsId: 'wfYoutubeSteps',
    summaryId: 'wfYoutubeSummary',
    modes: {
      ai_clip: {
        summary: 'Pipeline for AI Short Clips: requires an LLM key (and a Groq, Gemini, or ElevenLabs key if the video has no captions).',
        phases: ['1. Input', '2. Speech & Cache', '3. AI & Render', '4. Output'],
        studio: [
          {
            align: 'bottom',
            nodes: [
              { id: 'u-url', kind: 'box', label: 'YouTube URL', step: 0 },
              { id: 'u-cfg', kind: 'pill', label: 'Config & Start', step: 0 },
            ],
          },
          { align: 'bottom', nodes: [] },
          { align: 'bottom', nodes: [] },
          {
            align: 'bottom',
            nodes: [
              { id: 'u-zip', kind: 'pill', label: 'Download .ZIP', step: 3 },
              { id: 'u-prev', kind: 'pill', label: 'Preview Clips', step: 3 },
              { id: 'u-canv', kind: 'box', label: 'Clipper Canvas', step: 3 },
            ],
          },
        ],
        pipeline: [
          {
            align: 'top',
            nodes: [
              { id: 'p-dlp', kind: 'box', label: 'yt-dlp + Deno', step: 1 },
              { id: 'p-h264', kind: 'pill', label: '1080p H.264', step: 1 },
            ],
          },
          {
            align: 'top',
            nodes: [
              { id: 'p-stt', kind: 'box', label: 'Transcription', step: 1 },
              { id: 'p-srt', kind: 'pill', label: 'Captions / .SRT', step: 1 },
              { id: 'p-asr', kind: 'pill', label: 'Groq · Gemini · ElevenLabs · Whisper', step: 1 },
            ],
          },
          {
            align: 'top',
            nodes: [
              { id: 'p-ai', kind: 'box', label: 'Virality + FFmpeg', step: 2 },
              { id: 'p-llm', kind: 'pill', label: 'LLM Hook Score', step: 2 },
              { id: 'p-crop', kind: 'pill', label: 'Crop / Face Track', step: 2 },
            ],
          },
          {
            align: 'top',
            nodes: [
              { id: 'p-vault', kind: 'box', label: '01-AI-Clips', step: 3 },
              { id: 'p-meta', kind: 'pill', label: 'Clips + meta.json', step: 3 },
            ],
          },
        ],
        edges: [
          { from: 'u-url', to: 'u-cfg', route: 'v', style: 'green' },
          { from: 'u-cfg', to: 'p-dlp', route: 'v', style: 'dashed', badge: { color: '#a855f7', text: 'Submit' } },
          { from: 'p-dlp', to: 'p-h264', route: 'left-branch', style: 'green' },
          { from: 'p-dlp', to: 'p-stt', route: 'h', style: 'green' },
          { from: 'p-stt', to: 'p-srt', route: 'left-branch', style: 'green' },
          { from: 'p-stt', to: 'p-asr', route: 'left-branch', style: 'green' },
          { from: 'p-stt', to: 'p-ai', route: 'h', style: 'green' },
          { from: 'p-ai', to: 'p-llm', route: 'left-branch', style: 'green' },
          { from: 'p-ai', to: 'p-crop', route: 'left-branch', style: 'green' },
          { from: 'p-ai', to: 'p-vault', route: 'h', style: 'green' },
          { from: 'p-vault', to: 'p-meta', route: 'left-branch', style: 'green' },
          { from: 'p-vault', to: 'u-canv', route: 'v-up', style: 'dashed', badge: { color: '#22c55e', text: 'Ready' } },
          { from: 'u-canv', to: 'u-prev', route: 'right-up', style: 'green' },
          { from: 'u-canv', to: 'u-zip', route: 'right-up', style: 'green' },
        ],
        steps: [
          {
            tag: 'Studio',
            title: 'Input URL & Configuration',
            detail: 'Paste a YouTube video URL in Studio. Before dispatching the job, Luna validates URL format and public host safety, fetches quick metadata, and locks in your rendering preferences.',
            points: [
              '<strong>Target Aspect Ratio:</strong> Choose 9:16 (vertical Reels/Shorts/TikTok), 16:9, 1:1, or 3:4.',
              '<strong>Clip Count & Framing:</strong> Pick between 3 to 7 clips and select either fast Center Crop or OpenCV Face Tracking.',
              '<strong>Workspace Destination:</strong> Outputs are routed into your active Workspace subfolder so parallel channels or projects stay separated.',
            ],
          },
          {
            tag: 'yt-dlp + Speech',
            title: 'Download Source & Resolve Transcript',
            detail: 'Luna ingests the clean high-resolution source stream via yt-dlp powered by the Deno JS runtime, then builds a time-synced transcript before touching your LLM quota.',
            points: [
              '<strong>1080p H.264 Stream & Cookies:</strong> Downloads video + audio and automatically attaches cookies.txt if uploaded in Settings to bypass YouTube sign-in or 403 challenges.',
              '<strong>Transcript Priority Chain:</strong> Checks existing local .srt cache first, then official YouTube captions, before falling back to Groq Cloud Whisper, Gemini audio transcription, ElevenLabs Scribe, or local Faster-Whisper.',
            ],
          },
          {
            tag: 'LLM + FFmpeg',
            title: 'Virality Scoring, Reframing & Rendering',
            detail: 'Your configured LLM scans the timestamped transcript to find standalone hooks, then FFmpeg cuts and reframes each selected moment cleanly.',
            points: [
              '<strong>Hook Scoring (0–100):</strong> Uses your OpenAI-compatible endpoint or Gemini model to rank self-contained segments with non-overlapping timestamps.',
              '<strong>Reframe & Encode:</strong> Slices the video accurately per timestamp and applies Center Crop or OpenCV face centering into ready-to-upload MP4 files (without hardcoded burned captions).',
            ],
          },
          {
            tag: 'Storage + UI',
            title: 'Save to Workspace & Clipper Canvas',
            detail: 'Finished clips are indexed atomically and handed back to the Studio UI so you can inspect results right away.',
            points: [
              '<strong>Folder Structure:</strong> Saves every rendered MP4 along with meta.json (score, timestamps, summary, and provider metadata) into 01-AI-Clips\\{Workspace}.',
              '<strong>Interactive Review & Export:</strong> Opens clips inside Clipper Canvas for instant preview, individual downloads, or a one-click batch .ZIP archive.',
            ],
          },
        ],
      },
      video: {
        summary: 'Standard YouTube video download with optional resolution, aspect ratio crop, and FPS conversion. No API key needed.',
        phases: ['1. Input', '2. Download & Format', '3. Output'],
        studio: [
          {
            align: 'bottom',
            nodes: [
              { id: 'u-url', kind: 'box', label: 'YouTube URL', step: 0 },
              { id: 'u-cfg', kind: 'pill', label: 'Quality, Ratio & FPS', step: 0 },
            ],
          },
          { align: 'bottom', nodes: [] },
          {
            align: 'bottom',
            nodes: [
              { id: 'u-open', kind: 'pill', label: 'Open Folder', step: 2 },
              { id: 'u-prev', kind: 'pill', label: 'Preview MP4', step: 2 },
              { id: 'u-vault', kind: 'box', label: 'Workspace', step: 2 },
            ],
          },
        ],
        pipeline: [
          {
            align: 'top',
            nodes: [
              { id: 'p-dlp', kind: 'box', label: 'yt-dlp Mux', step: 1 },
              { id: 'p-res', kind: 'pill', label: '1080p / 720p / 480p', step: 1 },
            ],
          },
          {
            align: 'top',
            nodes: [
              { id: 'p-ff', kind: 'box', label: 'FFmpeg Format', step: 1 },
              { id: 'p-ratio', kind: 'pill', label: 'Aspect Ratio Crop', step: 1 },
              { id: 'p-fps', kind: 'pill', label: 'Auto / 60 / 30 FPS', step: 1 },
            ],
          },
          {
            align: 'top',
            nodes: [
              { id: 'p-out', kind: 'box', label: '02-YouTube-Full', step: 2 },
              { id: 'p-meta', kind: 'pill', label: 'MP4 + meta.json', step: 2 },
            ],
          },
        ],
        edges: [
          { from: 'u-url', to: 'u-cfg', route: 'v', style: 'green' },
          { from: 'u-cfg', to: 'p-dlp', route: 'v', style: 'dashed', badge: { color: '#a855f7', text: 'Submit' } },
          { from: 'p-dlp', to: 'p-res', route: 'left-branch', style: 'green' },
          { from: 'p-dlp', to: 'p-ff', route: 'h', style: 'green' },
          { from: 'p-ff', to: 'p-ratio', route: 'left-branch', style: 'green' },
          { from: 'p-ff', to: 'p-fps', route: 'left-branch', style: 'green' },
          { from: 'p-ff', to: 'p-out', route: 'h', style: 'green' },
          { from: 'p-out', to: 'p-meta', route: 'left-branch', style: 'green' },
          { from: 'p-out', to: 'u-vault', route: 'v-up', style: 'dashed', badge: { color: '#22c55e', text: 'Ready' } },
          { from: 'u-vault', to: 'u-prev', route: 'right-up', style: 'green' },
          { from: 'u-vault', to: 'u-open', route: 'right-up', style: 'green' },
        ],
        steps: [
          {
            tag: 'Studio',
            title: 'Input URL & Format Options',
            detail: 'Paste a standard YouTube or Shorts URL in Studio and choose your desired resolution, aspect ratio, and frame rate without configuring any AI API keys.',
            points: [
              '<strong>Video Quality:</strong> Select 1080p, 720p, or 480p depending on speed vs. file size requirements.',
              '<strong>Ratio & Frame Rate:</strong> Keep Original / Auto FPS for maximum speed, or enforce 9:16 / 3:4 / 1:1 crop and 60 or 30 FPS output.',
            ],
          },
          {
            tag: 'yt-dlp + FFmpeg',
            title: 'Download, Mux & Conditional Re-Encoding',
            detail: 'Luna pulls separate best-match video and audio streams via yt-dlp + Deno runtime and merges them into a standard H.264 MP4 container.',
            points: [
              '<strong>Direct Stream Copy vs. Re-Encode:</strong> When Original ratio and Auto FPS are selected, muxing finishes quickly without re-encoding pixels.',
              '<strong>Custom Format Conversion:</strong> If a cropped aspect ratio or fixed FPS (60/30) is chosen, FFmpeg applies center framing and frame-rate normalization automatically.',
            ],
          },
          {
            tag: 'Storage + UI',
            title: 'Save to 02-YouTube-Full & Workspace',
            detail: 'Completed files are organized inside your storage root and surfaced immediately inside Studio and Workspace.',
            points: [
              '<strong>Destination & Metadata:</strong> Stores the final MP4 and meta.json inside 02-YouTube-Full\\{Workspace}.',
              '<strong>Quick Actions:</strong> Play inline in Workspace, trigger browser download, or jump straight to the local folder.',
            ],
          },
        ],
      },
      mp3: {
        summary: 'Fast audio-only extraction directly to high-bitrate MP3. No API key needed.',
        phases: ['1. Input', '2. Extract Audio', '3. Output'],
        studio: [
          {
            align: 'bottom',
            nodes: [
              { id: 'u-url', kind: 'box', label: 'YouTube URL', step: 0 },
              { id: 'u-cfg', kind: 'pill', label: 'Audio MP3 Mode', step: 0 },
            ],
          },
          { align: 'bottom', nodes: [] },
          {
            align: 'bottom',
            nodes: [
              { id: 'u-open', kind: 'pill', label: 'Open Folder', step: 2 },
              { id: 'u-play', kind: 'pill', label: 'Play Audio', step: 2 },
              { id: 'u-vault', kind: 'box', label: 'Workspace', step: 2 },
            ],
          },
        ],
        pipeline: [
          {
            align: 'top',
            nodes: [
              { id: 'p-dlp', kind: 'box', label: 'yt-dlp Audio', step: 1 },
              { id: 'p-trk', kind: 'pill', label: 'Best Audio Track', step: 1 },
            ],
          },
          {
            align: 'top',
            nodes: [
              { id: 'p-ff', kind: 'box', label: 'FFmpeg Transcode', step: 1 },
              { id: 'p-br', kind: 'pill', label: '320 kbps MP3', step: 1 },
            ],
          },
          {
            align: 'top',
            nodes: [
              { id: 'p-out', kind: 'box', label: '05-Audio-MP3', step: 2 },
              { id: 'p-meta', kind: 'pill', label: 'MP3 + meta.json', step: 2 },
            ],
          },
        ],
        edges: [
          { from: 'u-url', to: 'u-cfg', route: 'v', style: 'green' },
          { from: 'u-cfg', to: 'p-dlp', route: 'v', style: 'dashed', badge: { color: '#a855f7', text: 'Submit' } },
          { from: 'p-dlp', to: 'p-trk', route: 'left-branch', style: 'green' },
          { from: 'p-dlp', to: 'p-ff', route: 'h', style: 'green' },
          { from: 'p-ff', to: 'p-br', route: 'left-branch', style: 'green' },
          { from: 'p-ff', to: 'p-out', route: 'h', style: 'green' },
          { from: 'p-out', to: 'p-meta', route: 'left-branch', style: 'green' },
          { from: 'p-out', to: 'u-vault', route: 'v-up', style: 'dashed', badge: { color: '#22c55e', text: 'Ready' } },
          { from: 'u-vault', to: 'u-play', route: 'right-up', style: 'green' },
          { from: 'u-vault', to: 'u-open', route: 'right-up', style: 'green' },
        ],
        steps: [
          {
            tag: 'Studio',
            title: 'Input YouTube Link',
            detail: 'Paste a YouTube link (music track, podcast, interview, or video) and choose Audio MP3 mode. Zero AI tokens or API keys are required.',
            points: [
              '<strong>Fast Metadata Check:</strong> Validates the URL host and pulls title/thumbnail metadata before starting extraction.',
            ],
          },
          {
            tag: 'yt-dlp + FFmpeg',
            title: 'Fetch Audio Stream & Transcode 320 kbps MP3',
            detail: 'Instead of pulling large 1080p video files, yt-dlp grabs only the highest-bitrate audio track and pipes it into FFmpeg.',
            points: [
              '<strong>High-Bitrate Output:</strong> FFmpeg runs FFmpegExtractAudio with preferredcodec mp3 and preferredquality 320 kbps.',
              '<strong>Cookie Support:</strong> Automatically uses Settings cookies.txt if YouTube requires sign-in verification.',
            ],
          },
          {
            tag: 'Storage + UI',
            title: 'Save to 05-Audio-MP3 & Workspace',
            detail: 'Once conversion finishes, the audio file is registered in your workspace.',
            points: [
              '<strong>Destination & Playback:</strong> Saves the .mp3 alongside meta.json inside 05-Audio-MP3\\{Workspace} for instant audio playback or folder access.',
            ],
          },
        ],
      },
      trim: {
        summary: 'Exact multi-segment cutter (up to 20 ranges per job) with aspect ratio framing. Uses zero AI quota.',
        phases: ['1. Input & Ranges', '2. Cut & Frame', '3. Output'],
        studio: [
          {
            align: 'bottom',
            nodes: [
              { id: 'u-url', kind: 'box', label: 'YouTube URL', step: 0 },
              { id: 'u-cfg', kind: 'pill', label: '1–20 Timestamps', step: 0 },
            ],
          },
          { align: 'bottom', nodes: [] },
          {
            align: 'bottom',
            nodes: [
              { id: 'u-zip', kind: 'pill', label: 'Download .ZIP', step: 2 },
              { id: 'u-prev', kind: 'pill', label: 'Preview Clips', step: 2 },
              { id: 'u-vault', kind: 'box', label: 'Workspace', step: 2 },
            ],
          },
        ],
        pipeline: [
          {
            align: 'top',
            nodes: [
              { id: 'p-dlp', kind: 'box', label: 'yt-dlp Source', step: 1 },
              { id: 'p-src', kind: 'pill', label: 'Up to 1080p MP4', step: 1 },
            ],
          },
          {
            align: 'top',
            nodes: [
              { id: 'p-ff', kind: 'box', label: 'FFmpeg Trimmer', step: 1 },
              { id: 'p-rng', kind: 'pill', label: 'Exact Timecodes', step: 1 },
              { id: 'p-crop', kind: 'pill', label: 'Ratio Crop', step: 1 },
            ],
          },
          {
            align: 'top',
            nodes: [
              { id: 'p-out', kind: 'box', label: '02-YouTube-Full', step: 2 },
              { id: 'p-meta', kind: 'pill', label: 'Clips + meta.json', step: 2 },
            ],
          },
        ],
        edges: [
          { from: 'u-url', to: 'u-cfg', route: 'v', style: 'green' },
          { from: 'u-cfg', to: 'p-dlp', route: 'v', style: 'dashed', badge: { color: '#a855f7', text: 'Submit' } },
          { from: 'p-dlp', to: 'p-src', route: 'left-branch', style: 'green' },
          { from: 'p-dlp', to: 'p-ff', route: 'h', style: 'green' },
          { from: 'p-ff', to: 'p-rng', route: 'left-branch', style: 'green' },
          { from: 'p-ff', to: 'p-crop', route: 'left-branch', style: 'green' },
          { from: 'p-ff', to: 'p-out', route: 'h', style: 'green' },
          { from: 'p-out', to: 'p-meta', route: 'left-branch', style: 'green' },
          { from: 'p-out', to: 'u-vault', route: 'v-up', style: 'dashed', badge: { color: '#22c55e', text: 'Ready' } },
          { from: 'u-vault', to: 'u-prev', route: 'right-up', style: 'green' },
          { from: 'u-vault', to: 'u-zip', route: 'right-up', style: 'green' },
        ],
        steps: [
          {
            tag: 'Studio',
            title: 'Input Link & Exact Timestamp Ranges',
            detail: 'Select Video Trimmer mode when you already know the exact timestamps to extract — uses zero AI quota and requires no API keys.',
            points: [
              '<strong>Multi-Segment Queue:</strong> Add between 1 and 20 start/end timestamp ranges in a single job.',
              '<strong>Aspect Ratio Framing:</strong> Pick Original, 9:16, 3:4, or 1:1 crop to apply uniformly across every trimmed cut.',
            ],
          },
          {
            tag: 'yt-dlp + FFmpeg',
            title: 'Download Source Once & Cut Every Segment',
            detail: 'Luna downloads the source video up to 1080p locally once, then runs FFmpeg sequentially over your timestamp list for frame-accurate cuts.',
            points: [
              '<strong>Precise Seeking:</strong> Trims each start-to-end range cleanly with synchronized audio and video.',
              '<strong>Optional Reframing:</strong> Applies the requested aspect ratio filter on each output segment during rendering.',
            ],
          },
          {
            tag: 'Storage + UI',
            title: 'Save Trimmed Clips to 02-YouTube-Full & .ZIP',
            detail: 'All generated segments from the batch are stored together and bundled for easy delivery.',
            points: [
              '<strong>Destination & Batch Export:</strong> Writes numbered clips + meta.json into 02-YouTube-Full\\{Workspace}, with inline preview and a single .ZIP archive for all segments.',
            ],
          },
        ],
      },
    },
  },
  instagram: {
    canvasId: 'wfInstagramCanvas',
    stepsId: 'wfInstagramSteps',
    summaryId: 'wfInstagramSummary',
    modes: {
      reels: {
        summary: 'Direct Instagram Reels video download at full available quality. No API key needed.',
        phases: ['1. Input', '2. Fetch Reel', '3. Output'],
        studio: [
          {
            align: 'bottom',
            nodes: [
              { id: 'u-url', kind: 'box', label: 'Reels URL', step: 0 },
              { id: 'u-cfg', kind: 'pill', label: 'Start Download', step: 0 },
            ],
          },
          { align: 'bottom', nodes: [] },
          {
            align: 'bottom',
            nodes: [
              { id: 'u-open', kind: 'pill', label: 'Open Folder', step: 2 },
              { id: 'u-prev', kind: 'pill', label: 'Preview Reel', step: 2 },
              { id: 'u-vault', kind: 'box', label: 'Workspace', step: 2 },
            ],
          },
        ],
        pipeline: [
          {
            align: 'top',
            nodes: [
              { id: 'p-val', kind: 'box', label: 'URL Validator', step: 0 },
              { id: 'p-sec', kind: 'pill', label: 'HTTPS Public Check', step: 0 },
            ],
          },
          {
            align: 'top',
            nodes: [
              { id: 'p-dlp', kind: 'box', label: 'yt-dlp Reels', step: 1 },
              { id: 'p-mp4', kind: 'pill', label: 'Full Quality MP4', step: 1 },
            ],
          },
          {
            align: 'top',
            nodes: [
              { id: 'p-out', kind: 'box', label: '03-Instagram-Reels', step: 2 },
              { id: 'p-meta', kind: 'pill', label: 'MP4 + meta.json', step: 2 },
            ],
          },
        ],
        edges: [
          { from: 'u-url', to: 'u-cfg', route: 'v', style: 'green' },
          { from: 'u-cfg', to: 'p-val', route: 'v', style: 'dashed', badge: { color: '#a855f7', text: 'Submit' } },
          { from: 'p-val', to: 'p-sec', route: 'left-branch', style: 'green' },
          { from: 'p-val', to: 'p-dlp', route: 'h', style: 'green' },
          { from: 'p-dlp', to: 'p-mp4', route: 'left-branch', style: 'green' },
          { from: 'p-dlp', to: 'p-out', route: 'h', style: 'green' },
          { from: 'p-out', to: 'p-meta', route: 'left-branch', style: 'green' },
          { from: 'p-out', to: 'u-vault', route: 'v-up', style: 'dashed', badge: { color: '#22c55e', text: 'Ready' } },
          { from: 'u-vault', to: 'u-prev', route: 'right-up', style: 'green' },
          { from: 'u-vault', to: 'u-open', route: 'right-up', style: 'green' },
        ],
        steps: [
          {
            tag: 'Studio + Guard',
            title: 'Input & Validate Instagram Reels URL',
            detail: 'Paste any public Instagram Reels link in Studio. No AI API key is needed to download Reels.',
            points: [
              '<strong>Host & Safety Validation:</strong> Verifies HTTPS scheme and valid public Instagram hostnames before queuing the request.',
              '<strong>Instant Feedback:</strong> Rejects malformed or private/local host targets upfront with a clear alert modal.',
            ],
          },
          {
            tag: 'yt-dlp',
            title: 'Fetch Full-Quality Reels MP4 Stream',
            detail: 'Luna hands the validated URL to yt-dlp to pull the highest-quality MP4 video + audio stream available for that Reel.',
            points: [
              '<strong>Cookie Fallback Ready:</strong> If Instagram rate-limits or requests authentication on a session, cookies uploaded in Settings are used automatically.',
            ],
          },
          {
            tag: 'Storage + UI',
            title: 'Save to 03-Instagram-Reels & Workspace',
            detail: 'Completed Reels are organized under a dedicated platform directory so they never mix with YouTube or TikTok downloads.',
            points: [
              '<strong>Destination & Access:</strong> Writes the MP4 alongside meta.json into 03-Instagram-Reels\\{Workspace} with immediate Workspace preview, download, and Open Folder buttons.',
            ],
          },
        ],
      },
    },
  },
  tiktok: {
    canvasId: 'wfTiktokCanvas',
    stepsId: 'wfTiktokSteps',
    summaryId: 'wfTiktokSummary',
    modes: {
      video: {
        summary: 'Clean TikTok MP4 download without watermark. No API key needed.',
        phases: ['1. Input', '2. Clean Fetch', '3. Output'],
        studio: [
          {
            align: 'bottom',
            nodes: [
              { id: 'u-url', kind: 'box', label: 'TikTok URL', step: 0 },
              { id: 'u-cfg', kind: 'pill', label: 'oEmbed Preview', step: 0 },
            ],
          },
          { align: 'bottom', nodes: [] },
          {
            align: 'bottom',
            nodes: [
              { id: 'u-open', kind: 'pill', label: 'Open Folder', step: 2 },
              { id: 'u-prev', kind: 'pill', label: 'Preview Video', step: 2 },
              { id: 'u-vault', kind: 'box', label: 'Workspace', step: 2 },
            ],
          },
        ],
        pipeline: [
          {
            align: 'top',
            nodes: [
              { id: 'p-val', kind: 'box', label: 'URL Validator', step: 0 },
              { id: 'p-sec', kind: 'pill', label: 'Host & Link Check', step: 0 },
            ],
          },
          {
            align: 'top',
            nodes: [
              { id: 'p-dlp', kind: 'box', label: 'yt-dlp Clean', step: 1 },
              { id: 'p-mp4', kind: 'pill', label: 'No Watermark MP4', step: 1 },
            ],
          },
          {
            align: 'top',
            nodes: [
              { id: 'p-out', kind: 'box', label: '04-TikTok-Clean', step: 2 },
              { id: 'p-meta', kind: 'pill', label: 'MP4 + meta.json', step: 2 },
            ],
          },
        ],
        edges: [
          { from: 'u-url', to: 'u-cfg', route: 'v', style: 'green' },
          { from: 'u-cfg', to: 'p-val', route: 'v', style: 'dashed', badge: { color: '#a855f7', text: 'Submit' } },
          { from: 'p-val', to: 'p-sec', route: 'left-branch', style: 'green' },
          { from: 'p-val', to: 'p-dlp', route: 'h', style: 'green' },
          { from: 'p-dlp', to: 'p-mp4', route: 'left-branch', style: 'green' },
          { from: 'p-dlp', to: 'p-out', route: 'h', style: 'green' },
          { from: 'p-out', to: 'p-meta', route: 'left-branch', style: 'green' },
          { from: 'p-out', to: 'u-vault', route: 'v-up', style: 'dashed', badge: { color: '#22c55e', text: 'Ready' } },
          { from: 'u-vault', to: 'u-prev', route: 'right-up', style: 'green' },
          { from: 'u-vault', to: 'u-open', route: 'right-up', style: 'green' },
        ],
        steps: [
          {
            tag: 'Studio + Guard',
            title: 'Input Link, Validate & Preview Metadata',
            detail: 'Paste a full or shortened TikTok video link in Studio. No AI API key is needed.',
            points: [
              '<strong>Preview & Safety Check:</strong> Fetches video title, author, and thumbnail via TikTok oEmbed (with yt-dlp fallback) while enforcing public HTTPS URL validation.',
            ],
          },
          {
            tag: 'yt-dlp',
            title: 'Download Clean Watermark-Free MP4',
            detail: 'Luna extracts the source video stream directly via yt-dlp without TikTok overlay watermarks.',
            points: [
              '<strong>Original Fidelity:</strong> Preserves source vertical resolution and audio sync directly inside a clean MP4 container.',
            ],
          },
          {
            tag: 'Storage + UI',
            title: 'Save to 04-TikTok-Clean & Workspace',
            detail: 'Finished downloads are indexed automatically inside your local TikTok workspace.',
            points: [
              '<strong>Destination & Quick Actions:</strong> Saves the clean MP4 and meta.json inside 04-TikTok-Clean\\{Workspace} so you can preview, download, or open the folder immediately.',
            ],
          },
        ],
      },
      mp3: {
        summary: 'Extract TikTok audio track or song directly to 320 kbps MP3. No API key needed.',
        phases: ['1. Input', '2. Extract Audio', '3. Output'],
        studio: [
          {
            align: 'bottom',
            nodes: [
              { id: 'u-url', kind: 'box', label: 'TikTok URL', step: 0 },
              { id: 'u-cfg', kind: 'pill', label: 'Audio MP3 Mode', step: 0 },
            ],
          },
          { align: 'bottom', nodes: [] },
          {
            align: 'bottom',
            nodes: [
              { id: 'u-open', kind: 'pill', label: 'Open Folder', step: 2 },
              { id: 'u-play', kind: 'pill', label: 'Play Audio', step: 2 },
              { id: 'u-vault', kind: 'box', label: 'Workspace', step: 2 },
            ],
          },
        ],
        pipeline: [
          {
            align: 'top',
            nodes: [
              { id: 'p-dlp', kind: 'box', label: 'yt-dlp Audio', step: 0 },
              { id: 'p-trk', kind: 'pill', label: 'Fetch Audio Track', step: 0 },
            ],
          },
          {
            align: 'top',
            nodes: [
              { id: 'p-ff', kind: 'box', label: 'FFmpeg Transcode', step: 1 },
              { id: 'p-br', kind: 'pill', label: '320 kbps MP3', step: 1 },
            ],
          },
          {
            align: 'top',
            nodes: [
              { id: 'p-out', kind: 'box', label: '05-Audio-MP3', step: 2 },
              { id: 'p-meta', kind: 'pill', label: 'MP3 + meta.json', step: 2 },
            ],
          },
        ],
        edges: [
          { from: 'u-url', to: 'u-cfg', route: 'v', style: 'green' },
          { from: 'u-cfg', to: 'p-dlp', route: 'v', style: 'dashed', badge: { color: '#a855f7', text: 'Submit' } },
          { from: 'p-dlp', to: 'p-trk', route: 'left-branch', style: 'green' },
          { from: 'p-dlp', to: 'p-ff', route: 'h', style: 'green' },
          { from: 'p-ff', to: 'p-br', route: 'left-branch', style: 'green' },
          { from: 'p-ff', to: 'p-out', route: 'h', style: 'green' },
          { from: 'p-out', to: 'p-meta', route: 'left-branch', style: 'green' },
          { from: 'p-out', to: 'u-vault', route: 'v-up', style: 'dashed', badge: { color: '#22c55e', text: 'Ready' } },
          { from: 'u-vault', to: 'u-play', route: 'right-up', style: 'green' },
          { from: 'u-vault', to: 'u-open', route: 'right-up', style: 'green' },
        ],
        steps: [
          {
            tag: 'Studio + yt-dlp',
            title: 'Validate Link & Extract Source Audio Track',
            detail: 'Paste any TikTok video or sound link and select Audio MP3 mode. Zero AI keys required.',
            points: [
              '<strong>Audio-Only Fetch:</strong> Validates the TikTok URL and pulls the clean audio track via yt-dlp without rendering unnecessary video copies.',
            ],
          },
          {
            tag: 'FFmpeg',
            title: 'Transcode to 320 kbps High-Bitrate MP3',
            detail: 'FFmpeg processes the pulled audio track through FFmpegExtractAudio into a standardized high-quality MP3.',
            points: [
              '<strong>Uniform Quality:</strong> Outputs clean 320 kbps stereo MP3 compatible with editors, DAWs, and mobile players.',
            ],
          },
          {
            tag: 'Storage + UI',
            title: 'Save to 05-Audio-MP3 & Workspace',
            detail: 'Completed MP3 tracks share the central audio folder across platforms, separated cleanly by Workspace.',
            points: [
              '<strong>Destination & Playback:</strong> Stores the .mp3 file + meta.json inside 05-Audio-MP3\\{Workspace} for built-in playback and instant folder access.',
            ],
          },
        ],
      },
    },
  },
};

const activeWorkflowModes = {
  youtube: 'ai_clip',
  instagram: 'reels',
  tiktok: 'video',
};

function roundedOrthoPath(pts, radius = 8) {
  if (pts.length < 2) return '';
  let d = `M ${pts[0][0]} ${pts[0][1]}`;
  for (let i = 1; i < pts.length - 1; i++) {
    const [x0, y0] = pts[i - 1];
    const [x1, y1] = pts[i];
    const [x2, y2] = pts[i + 1];
    const dx1 = x1 - x0;
    const dy1 = y1 - y0;
    const dx2 = x2 - x1;
    const dy2 = y2 - y1;
    const len1 = Math.hypot(dx1, dy1);
    const len2 = Math.hypot(dx2, dy2);
    if (!len1 || !len2) continue;
    const r = Math.min(radius, len1 * 0.45, len2 * 0.45);
    const ax = x1 - (dx1 / len1) * r;
    const ay = y1 - (dy1 / len1) * r;
    const bx = x1 + (dx2 / len2) * r;
    const by = y1 + (dy2 / len2) * r;
    d += ` L ${ax} ${ay} Q ${x1} ${y1}, ${bx} ${by}`;
  }
  const last = pts[pts.length - 1];
  d += ` L ${last[0]} ${last[1]}`;
  return d;
}

function drawGuideFlowConnectors(canvas) {
  if (!canvas) return;
  const stage = canvas.querySelector('.sl-stage');
  const svg = canvas.querySelector('.sl-svg');
  const badgesLayer = canvas.querySelector('.sl-badges');
  if (!stage || !svg) return;

  const w = stage.clientWidth;
  const h = stage.clientHeight;
  if (!w || !h) return;

  const platform = canvas.dataset.platform;
  const modeKey = canvas.dataset.mode;
  const mode = GUIDE_WORKFLOWS[platform] && GUIDE_WORKFLOWS[platform].modes[modeKey];
  if (!mode) return;

  svg.setAttribute('width', w);
  svg.setAttribute('height', h);
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
  svg.innerHTML = '';
  if (badgesLayer) badgesLayer.innerHTML = '';

  const ns = 'http://www.w3.org/2000/svg';
  const defs = document.createElementNS(ns, 'defs');
  const mkArrow = (id, fill) => {
    const m = document.createElementNS(ns, 'marker');
    m.setAttribute('id', id);
    m.setAttribute('viewBox', '0 0 8 8');
    m.setAttribute('refX', '7');
    m.setAttribute('refY', '4');
    m.setAttribute('markerWidth', '5');
    m.setAttribute('markerHeight', '5');
    m.setAttribute('orient', 'auto');
    const poly = document.createElementNS(ns, 'polygon');
    poly.setAttribute('points', '0,1 8,4 0,7');
    poly.setAttribute('fill', fill);
    m.appendChild(poly);
    defs.appendChild(m);
  };
  const greenId = `${canvas.id}-arrow-green`;
  const dashedId = `${canvas.id}-arrow-dashed`;
  mkArrow(greenId, '#737373');
  mkArrow(dashedId, '#a3a3a3');
  svg.appendChild(defs);

  const uiZoom = (typeof window.__getLunaUiScale === 'function') ? window.__getLunaUiScale() : 1;
  const sRect = stage.getBoundingClientRect();
  const rects = {};
  stage.querySelectorAll('[data-sl-id]').forEach(el => {
    const r = el.getBoundingClientRect();
    rects[el.dataset.slId] = {
      el,
      left: (r.left - sRect.left) / uiZoom,
      right: (r.right - sRect.left) / uiZoom,
      top: (r.top - sRect.top) / uiZoom,
      bottom: (r.bottom - sRect.top) / uiZoom,
      cx: ((r.left + r.right) / 2 - sRect.left) / uiZoom,
      cy: ((r.top + r.bottom) / 2 - sRect.top) / uiZoom,
    };
  });

  const gapEl = stage.querySelector('.sl-lane-gap');
  const gapMidY = gapEl
    ? ((gapEl.getBoundingClientRect().top + gapEl.getBoundingClientRect().bottom) / 2 - sRect.top) / uiZoom
    : h / 2;

  mode.edges.forEach(edge => {
    const a = rects[edge.from];
    const b = rects[edge.to];
    if (!a || !b) return;

    const getCellMinLeft = box => {
      const children = box.el && box.el.parentElement ? Array.from(box.el.parentElement.children) : [];
      const lefts = children.map(c => rects[c.dataset.slId] && rects[c.dataset.slId].left).filter(v => v !== undefined);
      return lefts.length ? Math.min(...lefts) : box.left;
    };
    const getCellMaxRight = box => {
      const children = box.el && box.el.parentElement ? Array.from(box.el.parentElement.children) : [];
      const rights = children.map(c => rects[c.dataset.slId] && rects[c.dataset.slId].right).filter(v => v !== undefined);
      return rights.length ? Math.max(...rights) : box.right;
    };

    let pts = [];
    if (edge.route === 'v') {
      if (Math.abs(a.cx - b.cx) < 2) {
        pts = [[a.cx, a.bottom], [a.cx, b.top]];
      } else {
        const midY = (a.bottom + b.top) / 2;
        pts = [[a.cx, a.bottom], [a.cx, midY], [b.cx, midY], [b.cx, b.top]];
      }
    } else if (edge.route === 'v-up') {
      if (Math.abs(a.cx - b.cx) < 2) {
        pts = [[a.cx, a.top], [a.cx, b.bottom]];
      } else {
        const midY = (a.top + b.bottom) / 2;
        pts = [[a.cx, a.top], [a.cx, midY], [b.cx, midY], [b.cx, b.bottom]];
      }
    } else if (edge.route === 'h') {
      const yA = a.cy - 3;
      const yB = b.cy - 3;
      if (Math.abs(yA - yB) < 2) {
        pts = [[a.right, yA], [b.left, yA]];
      } else {
        const midX = (a.right + b.left) / 2;
        pts = [[a.right, yA], [midX, yA], [midX, yB], [b.left, yB]];
      }
    } else if (edge.route === 'left-branch') {
      const gx = getCellMinLeft(a) - 10;
      pts = [[a.left, a.cy + 4], [gx, a.cy + 4], [gx, b.cy], [b.left, b.cy]];
    } else if (edge.route === 'right-up') {
      const gx = getCellMaxRight(a) + 10;
      pts = [[a.right, a.cy], [gx, a.cy], [gx, b.cy], [b.right, b.cy]];
    }

    const path = document.createElementNS(ns, 'path');
    path.setAttribute('d', roundedOrthoPath(pts, 7));
    path.setAttribute('fill', 'none');
    path.setAttribute('stroke-width', '1.35');
    path.setAttribute('stroke-linecap', 'round');

    if (edge.style === 'dashed') {
      path.setAttribute('stroke', 'rgba(163, 163, 163, 0.85)');
      path.setAttribute('stroke-dasharray', '4 3');
      path.setAttribute('marker-end', `url(#${dashedId})`);
      svg.appendChild(path);

      const dot = document.createElementNS(ns, 'circle');
      dot.setAttribute('cx', pts[0][0]);
      dot.setAttribute('cy', pts[0][1]);
      dot.setAttribute('r', '2.5');
      dot.setAttribute('fill', '#0b0b0b');
      dot.setAttribute('stroke', '#a3a3a3');
      dot.setAttribute('stroke-width', '1.3');
      svg.appendChild(dot);
    } else {
      path.setAttribute('stroke', '#737373');
      path.setAttribute('marker-end', `url(#${greenId})`);
      svg.appendChild(path);
    }

    if (edge.badge && badgesLayer) {
      const badgeEl = document.createElement('div');
      badgeEl.className = 'sl-wire-badge';
      badgeEl.style.left = `${(pts[0][0] + pts[pts.length - 1][0]) / 2}px`;
      badgeEl.style.top = `${gapMidY}px`;
      badgeEl.textContent = edge.badge.text;
      badgesLayer.appendChild(badgeEl);
    }
  });
}

function selectWorkflowStep(platform, idx) {
  const cfg = GUIDE_WORKFLOWS[platform];
  if (!cfg) return;
  const canvas = document.getElementById(cfg.canvasId);
  const stepsEl = document.getElementById(cfg.stepsId);
  if (!canvas || !stepsEl) return;

  const items = stepsEl.querySelectorAll('.guide-flow-step-item');
  const nodes = canvas.querySelectorAll('[data-sl-step]');
  const already = items[idx] && items[idx].classList.contains('active');

  items.forEach((el, i) => el.classList.toggle('active', !already && i === idx));
  nodes.forEach(n => n.classList.toggle('active', !already && Number(n.dataset.slStep) === idx));
}

function renderSwimlaneCell(col, platform) {
  const alignClass = col.align === 'top' ? 'align-top' : 'align-bottom';
  const items = col.nodes.map(n => {
    const cls = n.kind === 'pill' ? 'sl-node-pill' : 'sl-node-box';
    return `<button type="button" class="${cls}" data-sl-id="${n.id}" data-sl-step="${n.step}" onclick="selectWorkflowStep('${platform}', ${n.step})">${n.label}</button>`;
  }).join('');
  return `<div class="sl-cell ${alignClass}">${items}</div>`;
}

function renderGuideWorkflow(platform) {
  const cfg = GUIDE_WORKFLOWS[platform];
  if (!cfg) return;
  const modeKey = activeWorkflowModes[platform];
  const mode = cfg.modes[modeKey];
  const canvas = document.getElementById(cfg.canvasId);
  const stepsEl = document.getElementById(cfg.stepsId);
  if (!mode || !canvas) return;

  canvas.dataset.platform = platform;
  canvas.dataset.mode = modeKey;

  const summaryEl = document.getElementById(cfg.summaryId);
  if (summaryEl) {
    summaryEl.textContent = mode.summary;
  }

  const colsCount = mode.phases.length;
  const headsHtml = `<div></div>` + mode.phases.map(p => `<div class="sl-head-cell">${p}</div>`).join('');
  const studioHtml = mode.studio.map(col => renderSwimlaneCell(col, platform)).join('');
  const pipeHtml = mode.pipeline.map(col => renderSwimlaneCell(col, platform)).join('');

  canvas.innerHTML = `
    <div class="sl-stage" style="--sl-cols: ${colsCount};">
      <div class="sl-head-row">${headsHtml}</div>
      <div class="sl-lane">
        <div class="sl-lane-grid">
          <div class="sl-lane-rail">Studio</div>
          ${studioHtml}
        </div>
      </div>
      <div class="sl-lane-gap"></div>
      <div class="sl-lane">
        <div class="sl-lane-grid">
          <div class="sl-lane-rail">Pipeline</div>
          ${pipeHtml}
        </div>
      </div>
      <svg class="sl-svg" aria-hidden="true"></svg>
      <div class="sl-badges"></div>
    </div>
  `;

  if (stepsEl) {
    stepsEl.innerHTML = mode.steps.map((s, idx) => {
      const stepNum = idx + 1;
      const pointsHtml = Array.isArray(s.points) && s.points.length
        ? `<ul class="guide-flow-step-points">${s.points.map(pt => `<li>${pt}</li>`).join('')}</ul>`
        : '';
      return `
        <div class="guide-flow-step-item">
          <h3 class="guide-flow-step-title">${stepNum}. ${s.title}</h3>
          <p class="guide-flow-step-detail">${s.detail}</p>
          ${pointsHtml}
        </div>
      `;
    }).join('');
  }

  requestAnimationFrame(() => drawGuideFlowConnectors(canvas));
}

function setWorkflowSubmode(platform, modeKey, btn) {
  activeWorkflowModes[platform] = modeKey;
  if (btn && btn.parentElement) {
    btn.parentElement.querySelectorAll('.guide-submode-btn').forEach(b => {
      b.classList.toggle('active', b === btn);
    });
  }
  renderGuideWorkflow(platform);
}

function redrawVisibleGuideFlows() {
  Object.keys(GUIDE_WORKFLOWS).forEach(plat => {
    const canvas = document.getElementById(GUIDE_WORKFLOWS[plat].canvasId);
    if (canvas && canvas.offsetParent !== null) {
      drawGuideFlowConnectors(canvas);
    }
  });
}

function initGuideWorkflows() {
  Object.keys(GUIDE_WORKFLOWS).forEach(plat => renderGuideWorkflow(plat));
}

window.addEventListener('resize', () => {
  requestAnimationFrame(redrawVisibleGuideFlows);
});

document.addEventListener('DOMContentLoaded', () => {
  initGuideWorkflows();
});

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

function switchGuideTab(tabId, btn, shouldScroll = false, options = {}) {
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
  window.currentGuideTab = tabId;
  if (options.updateUrl !== false && typeof currentMainTab !== 'undefined' && currentMainTab === 'guide' && typeof syncLocationHash === 'function') {
    syncLocationHash(tabId === 'wf-youtube' ? '#guide' : `#guide/${tabId}`);
  }
  updateGuidePill(targetBtn, Boolean(options.immediate));

  document.querySelectorAll('.guide-tab-pane').forEach(p => p.classList.add('hidden'));
  const activePane = document.getElementById(`tab-${tabId}`);
  if (activePane) {
    activePane.classList.remove('hidden');
  }
  updateGuidePager(tabId);
  requestAnimationFrame(redrawVisibleGuideFlows);
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
  if (!document.querySelector('#wfYoutubeCanvas .sl-node-box')) {
    initGuideWorkflows();
  }
  const activeBtn = document.querySelector('#guideTabsBar [aria-selected="true"]')
    || document.querySelector('#guideTabsBar [data-guide-tab]');
  if (activeBtn) {
    updateGuidePill(activeBtn, true);
    if (activeBtn.dataset && activeBtn.dataset.guideTab) {
      updateGuidePager(activeBtn.dataset.guideTab);
    }
  }
  requestAnimationFrame(redrawVisibleGuideFlows);
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
