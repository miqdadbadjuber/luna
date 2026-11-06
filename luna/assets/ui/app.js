// Global application and navigation state
var currentMainTab = 'studio';
var currentActiveProjectId = null;
var vaultItems = [];
var vaultProjects = [];
var nextWorkspaceIndex = 1;
var vaultStats = { storage_root: 'D:\\Luna-Media', total_files: 0, total_bytes: 0, total_mb: 0, total_gb: 0 };
var currentVaultFilter = 'all';
var currentVaultSearch = '';
var deletingItemId = null;
var deletingProjectId = null;
var currentlyPlayingAudioId = null;
var clipperFilesCache = [];

var currentPlatform = 'youtube';
var currentYtSub = 'type_yt_ai_clip';
var currentIgSub = 'type_ig_reels';
var currentTtSub = 'type_tt_video';

var selectedRatio = '9:16';
var selectedClipCount = 5;
var selectedFaceDetect = false;
var selectedQuality = '1080';
var selectedVideoRatio = 'original';
var selectedVideoFps = 'auto';
var selectedTrimRatio = 'original';

// Multi-Segment Trimmer State (Max 24h, 6 digits: HH:MM:SS or MM:SS)
var trimSegments = [
  { id: 'seg_1', start_time: '00:00', end_time: '00:30' }
];

function parseAndFormatTime(str) {
  if (!str) return '00:00';
  str = String(str).trim();
  const pad = (n) => String(n).padStart(2, '0');

  // If user typed with colons
  if (str.includes(':')) {
    const rawParts = str.split(':').filter(p => p.length > 0).map(p => {
      const clean = p.replace(/\D/g, '').slice(0, 2);
      return parseInt(clean, 10) || 0;
    });

    if (rawParts.length === 3) {
      const h = Math.min(23, rawParts[0]);
      const m = Math.min(59, rawParts[1]);
      const s = Math.min(59, rawParts[2]);
      return `${pad(h)}:${pad(m)}:${pad(s)}`;
    } else if (rawParts.length === 2) {
      const m = Math.min(59, rawParts[0]);
      const s = Math.min(59, rawParts[1]);
      return `${pad(m)}:${pad(s)}`;
    } else if (rawParts.length === 1) {
      const m = Math.min(59, rawParts[0]);
      return `${pad(m)}:00`;
    }
  }

  // If user typed raw digits without colon
  const digits = str.replace(/\D/g, '').slice(0, 6);
  if (!digits) return '00:00';

  if (digits.length <= 2) {
    const s = Math.min(59, parseInt(digits, 10) || 0);
    return `00:${pad(s)}`;
  } else if (digits.length <= 4) {
    const m = Math.min(59, parseInt(digits.slice(0, -2), 10) || 0);
    const s = Math.min(59, parseInt(digits.slice(-2), 10) || 0);
    return `${pad(m)}:${pad(s)}`;
  } else {
    const s = Math.min(59, parseInt(digits.slice(-2), 10) || 0);
    const m = Math.min(59, parseInt(digits.slice(-4, -2), 10) || 0);
    const h = Math.min(23, parseInt(digits.slice(0, -4), 10) || 0);
    return `${pad(h)}:${pad(m)}:${pad(s)}`;
  }
}

function timeToSeconds(str) {
  if (!str) return 0;
  const parts = String(str).trim().split(':').map(p => parseInt(p, 10) || 0);
  if (parts.length === 3) return Math.min(86399, parts[0] * 3600 + parts[1] * 60 + parts[2]);
  if (parts.length === 2) return Math.min(86399, parts[0] * 60 + parts[1]);
  return Math.min(86399, parts[0] || 0);
}

function secondsToTime(sec) {
  sec = Math.max(0, Math.min(86399, Math.floor(sec)));
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  const pad = (n) => String(n).padStart(2, '0');
  if (h > 0) {
    return `${pad(h)}:${pad(m)}:${pad(s)}`;
  }
  return `${pad(m)}:${pad(s)}`;
}

function renderTrimSegments() {
  // 1. Sync Row 0 in main toolbar
  const seg0 = trimSegments[0] || { id: 'seg_1', start_time: '00:00', end_time: '00:30' };
  const inStart0 = document.getElementById('trimInputStart_0');
  const inEnd0 = document.getElementById('trimInputEnd_0');
  if (inStart0) inStart0.value = seg0.start_time || '00:00';
  if (inEnd0) inEnd0.value = seg0.end_time || '00:30';

  // 2. Render Extra Rows in #trimExtraSegmentsWrapper
  const wrapper = document.getElementById('trimExtraSegmentsWrapper');
  if (!wrapper) return;
  wrapper.innerHTML = '';

  const hasExtras = trimSegments.length > 1;
  const isTrimmerActive = document.getElementById('drawer-trimmer') && !document.getElementById('drawer-trimmer').classList.contains('hidden');
  wrapper.classList.toggle('hidden', !hasExtras || !isTrimmerActive);

  if (hasExtras && isTrimmerActive) {
    trimSegments.slice(1).forEach((seg) => {
      const row = document.createElement('div');
      row.className = 'trim-extra-row flex items-center gap-1.5 flex-shrink-0';
      row.setAttribute('data-seg-id', seg.id);

      row.innerHTML = `
        <!-- Start Pill -->
        <div class="pill-control !py-0 !px-2.5 flex items-center gap-1 cursor-text flex-shrink-0" title="Start Time" onclick="this.querySelector('input')?.focus()">
          <span class="text-zinc-400 text-[11px] select-none pointer-events-none">Start:</span>
          <input type="text" maxlength="8" value="${escapeHtml(seg.start_time || '00:00')}"
            class="trim-input-field bg-transparent text-white text-xs font-mono text-center focus:outline-none w-[68px] selection:bg-white/20"
            placeholder="00:00" data-seg-id="${seg.id}" data-field="start_time" />
        </div>

        <!-- End Pill -->
        <div class="pill-control !py-0 !px-2.5 flex items-center gap-1 cursor-text flex-shrink-0" title="End Time" onclick="this.querySelector('input')?.focus()">
          <span class="text-zinc-400 text-[11px] select-none pointer-events-none">End:</span>
          <input type="text" maxlength="8" value="${escapeHtml(seg.end_time || '00:30')}"
            class="trim-input-field bg-transparent text-white text-xs font-mono text-center focus:outline-none w-[68px] selection:bg-white/20"
            placeholder="00:30" data-seg-id="${seg.id}" data-field="end_time" />
        </div>

        <!-- Delete Button -->
        <button type="button" onclick="removeTrimSegment('${seg.id}')"
          class="pill-control !w-7 !h-7 !p-0 flex items-center justify-center text-zinc-500 hover:text-red-400 hover:bg-white/[0.08] transition-colors flex-shrink-0"
          title="Delete this clip">
          <i data-lucide="x" class="w-3.5 h-3.5"></i>
        </button>
      `;

      wrapper.appendChild(row);
    });
  }

  bindTrimInputEvents();
  if (window.lucide && typeof window.lucide.createIcons === 'function') {
    window.lucide.createIcons();
  }

  requestAnimationFrame(() => {
    alignExtraTrimSegments();
  });
}

function alignExtraTrimSegments() {
  const startPill = document.getElementById('trimStartPill_0');
  const wrapper = document.getElementById('trimExtraSegmentsWrapper');
  const container = document.getElementById('mainInputCapsuleContainer');
  if (!startPill || !wrapper || !container) return;

  const startRect = startPill.getBoundingClientRect();
  const containerRect = container.getBoundingClientRect();
  const offsetLeft = Math.max(0, Math.round(startRect.left - containerRect.left));

  wrapper.querySelectorAll('.trim-extra-row').forEach(row => {
    row.style.paddingLeft = `${offsetLeft}px`;
  });
}

window.addEventListener('resize', alignExtraTrimSegments);

function addTrimSegmentUI() {
  // Sync row 0 from DOM first
  const inS0 = document.getElementById('trimInputStart_0');
  const inE0 = document.getElementById('trimInputEnd_0');
  if (trimSegments[0]) {
    if (inS0) trimSegments[0].start_time = parseAndFormatTime(inS0.value);
    if (inE0) trimSegments[0].end_time = parseAndFormatTime(inE0.value);
    let s0 = timeToSeconds(trimSegments[0].start_time);
    let e0 = timeToSeconds(trimSegments[0].end_time);
    if (e0 <= s0) {
      trimSegments[0].end_time = secondsToTime(Math.min(86399, s0 + 30));
      if (inE0) inE0.value = trimSegments[0].end_time;
    }
  }

  const lastSeg = trimSegments[trimSegments.length - 1];
  let startSec = 0;
  let endSec = 30;

  if (lastSeg) {
    startSec = timeToSeconds(lastSeg.end_time || '00:30');
    endSec = Math.min(86399, startSec + 30);
  }

  const newId = 'seg_' + Date.now() + '_' + Math.floor(Math.random() * 1000);
  trimSegments.push({
    id: newId,
    start_time: secondsToTime(startSec),
    end_time: secondsToTime(endSec)
  });
  renderTrimSegments();
}

function removeTrimSegment(segId) {
  if (trimSegments.length <= 1) return;
  trimSegments = trimSegments.filter(s => s.id !== segId);
  renderTrimSegments();
}

function renderTimeFromDigits(digits) {
  digits = String(digits || '').replace(/\D/g, '').slice(0, 6);
  const pad = (n) => String(n).padStart(2, '0');

  if (digits.length === 0) {
    return { text: '00:00', cursor: 0 };
  }
  if (digits.length === 1) {
    let m = parseInt(digits, 10) || 0;
    return { text: `${pad(m)}:00`, cursor: 2 };
  }
  if (digits.length === 2) {
    let m = Math.min(59, parseInt(digits, 10) || 0);
    return { text: `${pad(m)}:00`, cursor: 3 };
  }
  if (digits.length === 3) {
    let m = Math.min(59, parseInt(digits.slice(0, 2), 10) || 0);
    let s = Math.min(59, parseInt(digits[2] + '0', 10) || 0);
    return { text: `${pad(m)}:${pad(s)}`, cursor: 4 };
  }
  if (digits.length === 4) {
    let m = Math.min(59, parseInt(digits.slice(0, 2), 10) || 0);
    let s = Math.min(59, parseInt(digits.slice(2, 4), 10) || 0);
    return { text: `${pad(m)}:${pad(s)}`, cursor: 5 };
  }
  if (digits.length === 5) {
    let h = Math.min(23, parseInt(digits[0], 10) || 0);
    let m = Math.min(59, parseInt(digits.slice(1, 3), 10) || 0);
    let s = Math.min(59, parseInt(digits.slice(3, 5), 10) || 0);
    return { text: `${pad(h)}:${pad(m)}:${pad(s)}`, cursor: 7 };
  }
  // 6 digits
  let h = Math.min(23, parseInt(digits.slice(0, 2), 10) || 0);
  let m = Math.min(59, parseInt(digits.slice(2, 4), 10) || 0);
  let s = Math.min(59, parseInt(digits.slice(4, 6), 10) || 0);
  return { text: `${pad(h)}:${pad(m)}:${pad(s)}`, cursor: 8 };
}

function syncTrimModel(input) {
  const segId = input.getAttribute('data-seg-id');
  const segIdx = input.getAttribute('data-seg-idx');
  const field = input.getAttribute('data-field');
  const seg = segId ? trimSegments.find(s => s.id === segId) : (segIdx !== null ? trimSegments[parseInt(segIdx, 10)] : null);
  if (seg) seg[field] = input.value;
}

function bindTrimInputEvents() {
  document.querySelectorAll('.trim-input-field').forEach(input => {
    // Initialize internal digits buffer from current DOM value
    if (typeof input._digits === 'undefined') {
      input._digits = (input.value || '').replace(/\D/g, '');
    }

    input.onfocus = function() {
      this._justFocused = true;
      setTimeout(() => this.select(), 10);
    };

    input.onmouseup = function(e) {
      if (this.selectionStart === 0 && this.selectionEnd === this.value.length) {
        e.preventDefault();
      }
    };

    input.onkeydown = function(e) {
      // Allow navigation & standard control keys
      if (['Tab', 'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Escape'].includes(e.key)) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;

      if (e.key === 'Enter') {
        e.preventDefault();
        this.blur();
        return;
      }

      if (e.key === 'Backspace' || e.key === 'Delete') {
        e.preventDefault();
        if (this._justFocused || (this.selectionStart === 0 && this.selectionEnd === this.value.length)) {
          this._digits = '';
          this._justFocused = false;
        } else {
          this._digits = (this._digits || '').slice(0, -1);
        }
        const res = renderTimeFromDigits(this._digits);
        this.value = res.text;
        try { this.setSelectionRange(res.cursor, res.cursor); } catch (err) {}
        syncTrimModel(this);
        return;
      }

      if (e.key === ':') {
        e.preventDefault();
        this._justFocused = false;
        let d = this._digits || '';
        if (d.length === 1) {
          this._digits = '0' + d;
        } else if (d.length === 3) {
          this._digits = d.slice(0, 2) + '0' + d[2];
        }
        const res = renderTimeFromDigits(this._digits);
        this.value = res.text;
        try { this.setSelectionRange(res.cursor, res.cursor); } catch (err) {}
        syncTrimModel(this);
        return;
      }

      if (/^[0-9]$/.test(e.key)) {
        e.preventDefault();
        if (this._justFocused || (this.selectionStart === 0 && this.selectionEnd === this.value.length)) {
          this._digits = e.key;
          this._justFocused = false;
        } else {
          if ((this._digits || '').length >= 6) return;
          this._digits = (this._digits || '') + e.key;
        }
        const res = renderTimeFromDigits(this._digits);
        this.value = res.text;
        try { this.setSelectionRange(res.cursor, res.cursor); } catch (err) {}
        syncTrimModel(this);
        return;
      }

      // Disallow any other keystroke
      e.preventDefault();
    };

    // Safety fallback for paste
    input.onpaste = function(e) {
      e.preventDefault();
      const pasted = (e.clipboardData || window.clipboardData).getData('text') || '';
      const digits = pasted.replace(/\D/g, '').slice(0, 6);
      if (digits) {
        this._digits = digits;
        this._justFocused = false;
        const res = renderTimeFromDigits(this._digits);
        this.value = res.text;
        try { this.setSelectionRange(res.cursor, res.cursor); } catch (err) {}
        syncTrimModel(this);
      }
    };

    // Safety fallback for mobile/virtual keyboards
    input.oninput = function() {
      if (!this.value.includes(':')) {
        let raw = this.value.replace(/\D/g, '').slice(0, 6);
        this._digits = raw;
        const res = renderTimeFromDigits(raw);
        this.value = res.text;
        try { this.setSelectionRange(res.cursor, res.cursor); } catch (err) {}
      }
      syncTrimModel(this);
    };

    // Validation & Auto-correction: End MUST be strictly greater than Start
    input.onblur = function() {
      this._justFocused = false;
      const formatted = parseAndFormatTime(this.value);
      this.value = formatted;
      this._digits = formatted.replace(/\D/g, '');

      const segId = this.getAttribute('data-seg-id');
      const segIdx = this.getAttribute('data-seg-idx');
      const field = this.getAttribute('data-field');
      const seg = segId ? trimSegments.find(s => s.id === segId) : (segIdx !== null ? trimSegments[parseInt(segIdx, 10)] : null);
      if (!seg) return;
      seg[field] = formatted;

      let stSec = timeToSeconds(seg.start_time || '00:00');
      let etSec = timeToSeconds(seg.end_time || '00:30');

      if (field === 'start_time') {
        if (etSec <= stSec) {
          etSec = Math.min(86399, stSec + 30);
          seg.end_time = secondsToTime(etSec);
          if (segIdx === '0' || segIdx === 0) {
            const inEnd = document.getElementById('trimInputEnd_0');
            if (inEnd) {
              inEnd.value = seg.end_time;
              inEnd._digits = seg.end_time.replace(/\D/g, '');
            }
          } else {
            const row = document.querySelector(`.trim-extra-row[data-seg-id="${seg.id}"]`);
            if (row) {
              const inEnd = row.querySelector('[data-field="end_time"]');
              if (inEnd) {
                inEnd.value = seg.end_time;
                inEnd._digits = seg.end_time.replace(/\D/g, '');
              }
            }
          }
        }
      } else if (field === 'end_time') {
        if (etSec <= stSec) {
          etSec = Math.min(86399, stSec + 30);
          seg.end_time = secondsToTime(etSec);
          this.value = seg.end_time;
          this._digits = seg.end_time.replace(/\D/g, '');
        }
      }
    };
  });
}

function getAllTrimSegments() {
  return trimSegments.map((s, idx) => {
    if (idx === 0) {
      const inS = document.getElementById('trimInputStart_0');
      const inE = document.getElementById('trimInputEnd_0');
      return {
        start_time: parseAndFormatTime(inS ? inS.value : (s.start_time || '00:00')),
        end_time: parseAndFormatTime(inE ? inE.value : (s.end_time || '00:30'))
      };
    }
    return {
      start_time: parseAndFormatTime(s.start_time || '00:00'),
      end_time: parseAndFormatTime(s.end_time || '00:30')
    };
  });
}

// Trim Ratio Selector Handlers
function toggleTrimRatioDropdown(e) {
  if (e) e.stopPropagation();
  const menu = document.getElementById('trimRatioMenu');
  const chev = document.getElementById('trimRatioChevron');
  const btn = document.getElementById('trimRatioDropdownBtn');
  const isClosed = menu?.getAttribute('data-open') !== 'true' && !menu?.classList.contains('open');
  closeAllDropdowns(isClosed ? 'trimRatioMenu' : null);
  if (menu) {
    menu.setAttribute('data-open', isClosed ? 'true' : 'false');
    menu.classList.toggle('open', isClosed);
    if (chev) chev.classList.toggle('rotate-180', isClosed);
    if (btn) {
      btn.setAttribute('aria-expanded', isClosed ? 'true' : 'false');
      btn.classList.toggle('active', isClosed);
    }
    if (isClosed) alignMenuIndicator('trimRatioMenu');
  }
}

function selectTrimRatioFromMenu(r, label) {
  selectedTrimRatio = r;
  const labelEl = document.getElementById('currentTrimRatioLabel');
  if (labelEl) labelEl.innerText = label;

  document.querySelectorAll('#trimRatioMenu .quality-menu-item[data-tratio]').forEach(item => {
    const isAct = item.getAttribute('data-tratio') === r;
    item.classList.toggle('active', isAct);
  });

  closeDropdownSmoothly('trimRatioMenu', 'trimRatioChevron', 'trimRatioDropdownBtn', 80);
}
var currentLang = 'id';

var activeJobId = null;
var pollInterval = null;

if (window.lucide && typeof window.lucide.createIcons === 'function') {
  window.lucide.createIcons();
}

const SUB_FEATURES = {
  youtube: [
    { id: 'type_yt_ai_clip', label: 'AI Short Clips', desc: 'Virality Score & Subtitles', icon: 'clapperboard', btnText: 'Generate', drawer: 'ai-clip' },
    { id: 'type_yt_video', label: 'Full HD Video', desc: '1080p / 720p / 480p MP4', icon: 'film', btnText: 'Download', drawer: 'quality' },
    { id: 'type_yt_short', label: 'YouTube Shorts', desc: 'Direct vertical 1080p', icon: 'zap', btnText: 'Download', drawer: null },
    { id: 'type_yt_mp3', label: 'Audio MP3', desc: '320kbps High Quality', icon: 'music', btnText: 'Download', drawer: null },
    { id: 'type_yt_clip', label: 'Video Trimmer', desc: 'Manually trim video duration', icon: 'scissors', btnText: 'Download', drawer: 'trimmer' }
  ],
  instagram: [
    { id: 'type_ig_reels', label: 'Reels', desc: 'Reels / Video Post', icon: 'film', btnText: 'Download', drawer: null }
  ],
  tiktok: [
    { id: 'type_tt_video', label: 'Video MP4', desc: 'HD Video MP4', icon: 'film', btnText: 'Download', drawer: null },
    { id: 'type_tt_mp3', label: 'Audio MP3', desc: 'TikTok song / soundtrack', icon: 'music', btnText: 'Download', drawer: null }
  ]
};

const mainUrlInput = document.getElementById('mainUrlInput');
const mainBtnText = document.getElementById('mainBtnText');
const mainActionBtn = document.getElementById('mainActionBtn');

function setMainActionLabel(text) {
  const labelEl = document.getElementById('mainBtnText');
  if (labelEl) labelEl.innerText = text;
  else mainActionBtn.textContent = text;
}

const videoInfoCard = document.getElementById('videoInfoCard');
const previewThumb = document.getElementById('previewThumb');
const previewTitle = document.getElementById('previewTitle');
const previewDuration = document.getElementById('previewDuration');
const previewBullet = document.getElementById('previewBullet');
const previewPlatformTag = document.getElementById('previewPlatformTag');

const progressStateCard = document.getElementById('progressStateCard');
const stageMainTitle = document.getElementById('stageMainTitle');
const stageSubTitle = document.getElementById('stageSubTitle');
const jobIdPill = document.getElementById('jobIdPill');

const resultsShowcase = document.getElementById('resultsShowcase');
const shortsGalleryGrid = document.getElementById('shortsGalleryGrid');
const batchZipDownloadBtn = document.getElementById('batchZipDownloadBtn');
const resultsCountNotice = document.getElementById('resultsCountNotice');

// Paste Action
async function pasteMainUrl() {
  try {
    const text = await navigator.clipboard.readText();
    if (text) {
      mainUrlInput.value = text;
      detectUrlPlatform(text);
      fastPreview(text);
      fetchVideoInfo(text, 0);
    }
  } catch (err) {
    console.log(err);
  }
}

function formatPlatformName(platform) {
  if (!platform) return 'Media';
  const p = platform.toLowerCase();
  if (p.includes('youtube')) return 'YouTube';
  if (p.includes('tiktok')) return 'TikTok';
  if (p.includes('instagram') || p.includes('reels')) return 'Instagram';
  return platform.charAt(0).toUpperCase() + platform.slice(1);
}

function extractVideoInfoInstant(url) {
  if (!url) return null;
  const ytMatch = url.match(/(?:youtu\.be\/|youtube\.com\/(?:shorts\/|watch\?v=|embed\/|v\/|live\/))([a-zA-Z0-9_-]{11})/);
  if (ytMatch) {
    return {
      platform: 'YouTube',
      thumbnail: `https://img.youtube.com/vi/${ytMatch[1]}/hqdefault.jpg`,
      title: 'Loading video title...'
    };
  }
  if (url.includes('tiktok.com')) {
    return {
      platform: 'TikTok',
      thumbnail: null,
      title: 'Loading media title...'
    };
  }
  if (url.includes('instagram.com') || url.includes('instagr.am')) {
    return {
      platform: 'Instagram',
      thumbnail: null,
      title: 'Loading Reels title...'
    };
  }
  return null;
}

function formatDuration(seconds) {
  if (!seconds || seconds <= 0 || isNaN(seconds)) return '';
  const totalSec = Math.round(Number(seconds));
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) {
    return `${h}:${m < 10 ? '0' : ''}${m}:${s < 10 ? '0' : ''}${s}`;
  }
  return `${m}:${s < 10 ? '0' : ''}${s}`;
}

function fastPreview(url) {
  if (!url || !url.startsWith('http')) {
    videoInfoCard.classList.add('hidden');
    return;
  }
  const instant = extractVideoInfoInstant(url);
  if (instant) {
    previewPlatformTag.innerText = instant.platform;
    previewDuration.innerText = '';
    previewDuration.classList.add('hidden');
    if (previewBullet) previewBullet.classList.add('hidden');
    previewTitle.innerText = instant.title;
    if (instant.thumbnail) {
      previewThumb.src = instant.thumbnail;
      previewThumb.classList.remove('hidden');
    } else {
      previewThumb.classList.add('hidden');
    }
    videoInfoCard.classList.remove('hidden');
  }

  // Fast instant client-side oEmbed query (sub-100ms) so real title appears immediately
  const ytMatch = url.match(/(?:youtu\.be\/|youtube\.com\/(?:shorts\/|watch\?v=|embed\/|v\/|live\/))([a-zA-Z0-9_-]{11})/);
  if (ytMatch) {
    const vidId = ytMatch[1];
    fetch(`https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v=${vidId}&format=json`)
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data && data.title && mainUrlInput.value.includes(vidId)) {
          previewTitle.innerText = data.title;
          previewPlatformTag.innerText = 'YouTube';
          if (data.thumbnail_url) {
            previewThumb.src = data.thumbnail_url;
            previewThumb.classList.remove('hidden');
          }
        }
      })
      .catch(() => {});
  } else if (url.includes('tiktok.com')) {
    fetch(`https://www.tiktok.com/oembed?url=${encodeURIComponent(url)}`)
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data && data.title) {
          previewTitle.innerText = data.title;
          previewPlatformTag.innerText = 'TikTok';
          if (data.thumbnail_url) {
            previewThumb.src = data.thumbnail_url;
            previewThumb.classList.remove('hidden');
          }
        }
      })
      .catch(() => {});
  }
}

mainUrlInput.addEventListener('input', (e) => {
  const url = e.target.value.trim();
  detectUrlPlatform(url);
  fastPreview(url);
  fetchVideoInfo(url, 150);
});

mainUrlInput.addEventListener('paste', () => {
  setTimeout(() => {
    const url = mainUrlInput.value.trim();
    detectUrlPlatform(url);
    fastPreview(url);
    fetchVideoInfo(url, 0);
  }, 0);
});

mainUrlInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    e.preventDefault();
    triggerAction();
  }
});

function detectUrlPlatform(url) {
  const lower = url.toLowerCase();
  if (lower.includes('tiktok.com')) {
    switchPlatform('tiktok', false);
  } else if (lower.includes('instagram.com') || lower.includes('instagr.am')) {
    switchPlatform('instagram', false);
  } else if (lower.includes('youtube.com') || lower.includes('youtu.be')) {
    switchPlatform('youtube', false);
  }
}

let debounceTimer = null;
function fetchVideoInfo(url, delay = 150) {
  clearTimeout(debounceTimer);
  if (!url || !url.startsWith('http')) {
    videoInfoCard.classList.add('hidden');
    return;
  }
  debounceTimer = setTimeout(async () => {
    try {
      const res = await fetch('/api/info', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url })
      });
      if (res.ok) {
        const data = await res.json();
        if (data.title && data.title !== 'Media Item') {
          latestVideoTitle = { url, title: data.title };
          previewTitle.innerText = data.title;
          const durText = formatDuration(data.duration);
          if (durText) {
            previewDuration.innerText = durText;
            previewDuration.classList.remove('hidden');
            if (previewBullet) previewBullet.classList.remove('hidden');
          } else {
            previewDuration.innerText = '';
            previewDuration.classList.add('hidden');
            if (previewBullet) previewBullet.classList.add('hidden');
          }
          previewPlatformTag.innerText = formatPlatformName(data.platform);

          if (data.thumbnail) {
            previewThumb.src = data.thumbnail;
            previewThumb.classList.remove('hidden');
          }
          videoInfoCard.classList.remove('hidden');
        }
      }
    } catch (e) {
      console.log(e);
    }
  }, delay);
}

// Gliding dropdown indicator on hover
function attachGlidingListener(menu) {
  if (!menu) return;
  let indicator = menu.querySelector('.gliding-menu-indicator');
  if (!indicator) {
    indicator = document.createElement('span');
    indicator.className = 'gliding-menu-indicator pointer-events-none absolute left-[3px] right-[3px] rounded-[6px] bg-white/[0.08] border border-white/[0.10] z-[1]';
    indicator.style.opacity = '0';
    indicator.style.transition = 'top 220ms cubic-bezier(0.23,1,0.32,1), height 220ms cubic-bezier(0.23,1,0.32,1), opacity 150ms ease';
    menu.insertBefore(indicator, menu.firstChild);
  }

  const getItems = () => menu.querySelectorAll('.platform-menu-item, .sub-menu-item, .aspect-menu-item, .count-menu-item, .fd-menu-item, .quality-menu-item');

  const moveToItem = (item) => {
    if (!item || !indicator) return;
    indicator.style.top = `${item.offsetTop}px`;
    indicator.style.height = `${item.offsetHeight}px`;
    indicator.style.opacity = '1';
  };

  getItems().forEach(item => {
    item.onmouseenter = (e) => {
      e.stopPropagation();
      moveToItem(item);
    };
  });

  menu.onmouseleave = () => {
    const active = menu.querySelector('.active');
    if (active) {
      moveToItem(active);
    } else {
      indicator.style.opacity = '0';
    }
  };
}

function alignMenuIndicator(menuId) {
  const menu = document.getElementById(menuId);
  if (!menu) return;
  attachGlidingListener(menu);
  const indicator = menu.querySelector('.gliding-menu-indicator');
  const active = menu.querySelector('.active') || menu.querySelector('.platform-menu-item, .sub-menu-item, .aspect-menu-item, .count-menu-item, .fd-menu-item, .quality-menu-item');
  if (indicator && active) {
    indicator.style.transition = 'none';
    indicator.style.top = `${active.offsetTop}px`;
    indicator.style.height = `${active.offsetHeight}px`;
    indicator.style.opacity = '1';
    void indicator.offsetHeight;
    indicator.style.transition = 'top 220ms cubic-bezier(0.23,1,0.32,1), height 220ms cubic-bezier(0.23,1,0.32,1), opacity 150ms ease';
  }
}

function initAllGlidingIndicators() {
  ['platformMenu', 'subFeatureMenu', 'aspectRatioMenu', 'clipCountMenu', 'faceDetectMenu', 'qualityMenu', 'videoRatioMenu', 'videoFpsMenu', 'trimRatioMenu'].forEach(id => {
    const m = document.getElementById(id);
    if (m) attachGlidingListener(m);
  });
}

// Dropdown Toggles
function togglePlatformDropdown(e) {
  if (e) e.stopPropagation();
  const menu = document.getElementById('platformMenu');
  const chev = document.getElementById('platformChevron');
  const btn = document.getElementById('platformDropdownBtn');
  const isClosed = menu?.getAttribute('data-open') !== 'true' && !menu?.classList.contains('open');
  closeAllDropdowns(isClosed ? 'platformMenu' : null);
  if (menu) {
    menu.setAttribute('data-open', isClosed ? 'true' : 'false');
    menu.classList.toggle('open', isClosed);
    if (chev) chev.classList.toggle('rotate-180', isClosed);
    if (btn) {
      btn.setAttribute('aria-expanded', isClosed ? 'true' : 'false');
      btn.classList.toggle('active', isClosed);
    }
    if (isClosed) alignMenuIndicator('platformMenu');
  }
}

function closeDropdownSmoothly(menuId, chevId, btnId, delay = 80) {
  setTimeout(() => {
    const menu = document.getElementById(menuId);
    const chev = chevId ? document.getElementById(chevId) : null;
    const btn = btnId ? document.getElementById(btnId) : null;
    if (menu) {
      menu.setAttribute('data-open', 'false');
      menu.classList.remove('open');
    }
    if (chev) chev.classList.remove('rotate-180');
    if (btn) {
      btn.setAttribute('aria-expanded', 'false');
      btn.classList.remove('active');
    }
  }, delay);
}

function selectPlatformFromMenu(plat) {
  switchPlatform(plat, true);
  closeDropdownSmoothly('platformMenu', 'platformChevron', 'platformDropdownBtn', 80);
}

function selectPlatformBadge(plat) {
  switchPlatform(plat, true);
}

// Platform Switcher
function switchPlatform(plat, manualSwitch = false) {
  currentPlatform = plat;

  if (manualSwitch) {
    mainUrlInput.value = '';
    videoInfoCard.classList.add('hidden');
  }

  // Highlight active platform badge
  document.querySelectorAll('.platform-badge').forEach(item => {
    item.classList.toggle('active', item.id === `badge-${plat}`);
  });

  const labels = {
    youtube: 'YouTube',
    instagram: 'Reels',
    tiktok: 'TikTok'
  };
  const icons = {
    youtube: '/assets/youtube-logo.svg?v=3',
    instagram: '/assets/instagram-logo.svg?v=3',
    tiktok: '/assets/tiktok-logo.svg?v=3'
  };

  const labelEl = document.getElementById('currentPlatformLabel');
  const iconEl = document.getElementById('currentPlatformIcon');
  if (labelEl) labelEl.innerText = labels[plat] || plat;
  if (iconEl) iconEl.src = icons[plat] || '/assets/youtube-logo.svg?v=3';

  // Highlight active item in platform dropdown
  document.querySelectorAll('.platform-menu-item[data-plat]').forEach(item => {
    const isAct = item.getAttribute('data-plat') === plat;
    item.classList.toggle('active', isAct);
  });

  // Populate sub-features menu for this platform
  populateSubFeatureMenu(plat);

  // Select default sub-feature
  const defaultSub = plat === 'youtube' ? currentYtSub : (plat === 'instagram' ? currentIgSub : currentTtSub);
  selectSubFeature(defaultSub, false);

  // Handle sub-feature chevron and interactivity for single-option platforms (Reels)
  const subChev = document.getElementById('subChevron');
  const subBtn = document.getElementById('subFeatureDropdownBtn');
  if (plat === 'instagram') {
    if (subChev) subChev.classList.add('hidden');
    if (subBtn) subBtn.style.cursor = 'default';
  } else {
    if (subChev) subChev.classList.remove('hidden');
    if (subBtn) subBtn.style.cursor = 'pointer';
  }

  // Update placeholder
  if (plat === 'youtube') mainUrlInput.placeholder = 'Paste a YouTube link';
  else if (plat === 'instagram') mainUrlInput.placeholder = 'Paste link Reels';
  else if (plat === 'tiktok') mainUrlInput.placeholder = 'Paste link TikTok';
}

function populateSubFeatureMenu(plat) {
  const menu = document.getElementById('subFeatureMenu');
  if (!menu) return;
  menu.innerHTML = '<span class="gliding-menu-indicator pointer-events-none absolute left-[3px] right-[3px] rounded-[6px] bg-white/[0.08] border border-white/[0.10] z-[1]" style="opacity: 0; transition: top 220ms cubic-bezier(0.23,1,0.32,1), height 220ms cubic-bezier(0.23,1,0.32,1), opacity 150ms ease;"></span>';
  const list = SUB_FEATURES[plat] || [];

  list.forEach(item => {
    const el = document.createElement('div');
    el.className = 'sub-menu-item group flex items-center transition cursor-pointer select-none';
    el.setAttribute('data-sub', item.id);
    el.onclick = () => selectSubFeature(item.id, true);

    el.innerHTML = `
      <span class="sub-item-title truncate text-[#d4d4d8]">${escapeHtml(item.label)}</span>
    `;
    menu.appendChild(el);
  });

  attachGlidingListener(menu);
  lucide.createIcons();
}

function selectSubFeature(subId, closeMenu = true) {
  if (currentPlatform === 'youtube') currentYtSub = subId;
  else if (currentPlatform === 'instagram') currentIgSub = subId;
  else if (currentPlatform === 'tiktok') currentTtSub = subId;

  const features = SUB_FEATURES[currentPlatform] || [];
  const feat = features.find(f => f.id === subId) || features[0];
  if (!feat) return;

  const subLabel = document.getElementById('currentSubFeatureLabel');
  if (subLabel) subLabel.innerText = feat.label;

  if (mainBtnText) {
    mainBtnText.innerText = feat.btnText;
  }

  // Highlight in sub-feature menu
  document.querySelectorAll('.sub-menu-item').forEach(item => {
    const isAct = item.getAttribute('data-sub') === feat.id;
    const titleEl = item.querySelector('.sub-item-title');
    const iconEl = item.querySelector('.sub-icon');

    item.classList.toggle('active', isAct);
    if (iconEl) {
      iconEl.classList.toggle('text-white', isAct);
      iconEl.classList.toggle('text-[#a1a1aa]', !isAct);
      iconEl.classList.remove('text-white', 'text-[#71717a]');
    }
    if (titleEl) {
      titleEl.classList.toggle('text-white', isAct);
      titleEl.classList.toggle('text-[#d4d4d8]', !isAct);
      titleEl.classList.remove('text-[#a1a1aa]');
    }
  });

  // Update Options Drawer
  updateDrawer(feat);

  if (closeMenu) {
    closeDropdownSmoothly('subFeatureMenu', 'subChevron', 'subFeatureDropdownBtn', 80);
  }

  lucide.createIcons();
}

function updateDrawer(feat) {
  const drawerAi = document.getElementById('drawer-ai-clip');
  const drawerQuality = document.getElementById('drawer-quality');
  const drawerTrimmer = document.getElementById('drawer-trimmer');
  const extraTrimmer = document.getElementById('trimExtraSegmentsWrapper');

  [drawerAi, drawerQuality, drawerTrimmer, extraTrimmer].forEach(el => {
    if (el) el.classList.add('hidden');
  });

  if (feat.drawer === 'ai-clip') {
    if (drawerAi) drawerAi.classList.remove('hidden');
  } else if (feat.drawer === 'quality') {
    if (drawerQuality) drawerQuality.classList.remove('hidden');
  } else if (feat.drawer === 'trimmer') {
    if (drawerTrimmer) drawerTrimmer.classList.remove('hidden');
    renderTrimSegments();
  }
}

// Central Dropdown Manager (Prevents overlapping/collision)
function closeAllDropdowns(exceptId = null) {
  const menus = ['subFeatureMenu', 'aspectRatioMenu', 'clipCountMenu', 'faceDetectMenu', 'qualityMenu', 'videoRatioMenu', 'videoFpsMenu', 'trimRatioMenu', 'platformMenu'];
  const chevrons = {
    subFeatureMenu: 'subChevron',
    aspectRatioMenu: 'aspectChevron',
    clipCountMenu: 'countChevron',
    faceDetectMenu: 'faceChevron',
    qualityMenu: 'qualityChevron',
    videoRatioMenu: 'videoRatioChevron',
    videoFpsMenu: 'videoFpsChevron',
    trimRatioMenu: 'trimRatioChevron',
    platformMenu: 'platformChevron'
  };
  const triggerBtns = {
    subFeatureMenu: 'subFeatureDropdownBtn',
    aspectRatioMenu: 'aspectRatioDropdownBtn',
    clipCountMenu: 'clipCountDropdownBtn',
    faceDetectMenu: 'faceDetectDropdownBtn',
    qualityMenu: 'qualityDropdownBtn',
    videoRatioMenu: 'videoRatioDropdownBtn',
    videoFpsMenu: 'videoFpsDropdownBtn',
    trimRatioMenu: 'trimRatioDropdownBtn',
    platformMenu: 'platformDropdownBtn'
  };
  menus.forEach(id => {
    if (id !== exceptId) {
      const menu = document.getElementById(id);
      if (menu) {
        menu.setAttribute('data-open', 'false');
        menu.classList.remove('open');
      }
      const chevId = chevrons[id];
      if (chevId) document.getElementById(chevId)?.classList.remove('rotate-180');
      const btnId = triggerBtns[id];
      if (btnId) {
        const btn = document.getElementById(btnId);
        if (btn) {
          btn.setAttribute('aria-expanded', 'false');
          btn.classList.remove('active');
        }
      }
    }
  });
}

function toggleSubFeatureDropdown(e) {
  if (e) e.stopPropagation();
  if (currentPlatform === 'instagram') return;
  const menu = document.getElementById('subFeatureMenu');
  const chev = document.getElementById('subChevron');
  const btn = document.getElementById('subFeatureDropdownBtn');
  const isClosed = menu?.getAttribute('data-open') !== 'true' && !menu?.classList.contains('open');
  closeAllDropdowns(isClosed ? 'subFeatureMenu' : null);
  if (menu) {
    menu.setAttribute('data-open', isClosed ? 'true' : 'false');
    menu.classList.toggle('open', isClosed);
    if (chev) chev.classList.toggle('rotate-180', isClosed);
    if (btn) {
      btn.setAttribute('aria-expanded', isClosed ? 'true' : 'false');
      btn.classList.toggle('active', isClosed);
    }
    if (isClosed) alignMenuIndicator('subFeatureMenu');
  }
}

// Ratio Dropdown Handlers
function toggleAspectRatioDropdown(e) {
  if (e) e.stopPropagation();
  const menu = document.getElementById('aspectRatioMenu');
  const chev = document.getElementById('aspectChevron');
  const btn = document.getElementById('aspectRatioDropdownBtn');
  const isClosed = menu?.getAttribute('data-open') !== 'true' && !menu?.classList.contains('open');
  closeAllDropdowns(isClosed ? 'aspectRatioMenu' : null);
  if (menu) {
    menu.setAttribute('data-open', isClosed ? 'true' : 'false');
    menu.classList.toggle('open', isClosed);
    if (chev) chev.classList.toggle('rotate-180', isClosed);
    if (btn) {
      btn.setAttribute('aria-expanded', isClosed ? 'true' : 'false');
      btn.classList.toggle('active', isClosed);
    }
    if (isClosed) alignMenuIndicator('aspectRatioMenu');
  }
}

function selectRatioFromMenu(r, label) {
  selectedRatio = r;
  const labelEl = document.getElementById('currentAspectRatioLabel');
  if (labelEl) labelEl.innerText = label;

  document.querySelectorAll('.aspect-menu-item[data-ratio]').forEach(item => {
    const isAct = item.getAttribute('data-ratio') === r;
    item.classList.toggle('active', isAct);
  });

  closeDropdownSmoothly('aspectRatioMenu', 'aspectChevron', 'aspectRatioDropdownBtn', 80);
}

function setRatio(r) {
  const labels = {
    '9:16': '9:16 Vertical',
    '16:9': '16:9 Wide',
    '1:1': '1:1 Square',
    '3:4': '3:4 Portrait'
  };
  selectRatioFromMenu(r, labels[r] || r);
}

// Clip Count Dropdown Handlers
function toggleClipCountDropdown(e) {
  if (e) e.stopPropagation();
  const menu = document.getElementById('clipCountMenu');
  const chev = document.getElementById('countChevron');
  const btn = document.getElementById('clipCountDropdownBtn');
  const isClosed = menu?.getAttribute('data-open') !== 'true' && !menu?.classList.contains('open');
  closeAllDropdowns(isClosed ? 'clipCountMenu' : null);
  if (menu) {
    menu.setAttribute('data-open', isClosed ? 'true' : 'false');
    menu.classList.toggle('open', isClosed);
    if (chev) chev.classList.toggle('rotate-180', isClosed);
    if (btn) {
      btn.setAttribute('aria-expanded', isClosed ? 'true' : 'false');
      btn.classList.toggle('active', isClosed);
    }
    if (isClosed) alignMenuIndicator('clipCountMenu');
  }
}

function selectClipCountFromMenu(cnt, label) {
  selectedClipCount = Number(cnt);
  const labelEl = document.getElementById('currentClipCountLabel');
  if (labelEl) labelEl.innerText = label;

  document.querySelectorAll('.count-menu-item[data-count]').forEach(item => {
    const isAct = Number(item.getAttribute('data-count')) === Number(cnt);
    item.classList.toggle('active', isAct);
  });

  closeDropdownSmoothly('clipCountMenu', 'countChevron', 'clipCountDropdownBtn', 80);
}

function setClipCount(cnt) {
  selectClipCountFromMenu(cnt, `${cnt} Clips`);
}

// Face Detect Dropdown Handlers
function toggleFaceDetectDropdown(e) {
  if (e) e.stopPropagation();
  const menu = document.getElementById('faceDetectMenu');
  const chev = document.getElementById('faceChevron');
  const btn = document.getElementById('faceDetectDropdownBtn');
  const isClosed = menu?.getAttribute('data-open') !== 'true' && !menu?.classList.contains('open');
  closeAllDropdowns(isClosed ? 'faceDetectMenu' : null);
  if (menu) {
    menu.setAttribute('data-open', isClosed ? 'true' : 'false');
    menu.classList.toggle('open', isClosed);
    if (chev) chev.classList.toggle('rotate-180', isClosed);
    if (btn) {
      btn.setAttribute('aria-expanded', isClosed ? 'true' : 'false');
      btn.classList.toggle('active', isClosed);
    }
    if (isClosed) alignMenuIndicator('faceDetectMenu');
  }
}

function selectFaceDetectFromMenu(val, label) {
  selectedFaceDetect = (val === true || val === 'true');
  const labelEl = document.getElementById('currentFaceDetectLabel');
  const iconEl = document.getElementById('currentFaceDetectIcon');
  if (labelEl) labelEl.innerText = label;
  if (iconEl) {
    iconEl.innerHTML = selectedFaceDetect
      ? '<i data-lucide="scan-face" class="w-3.5 h-3.5"></i>'
      : '<i data-lucide="crop" class="w-3.5 h-3.5"></i>';
  }

  document.querySelectorAll('.fd-menu-item[data-fd]').forEach(item => {
    const isAct = (item.getAttribute('data-fd') === 'true') === selectedFaceDetect;
    const icon = item.querySelector('.fd-icon');
    item.classList.toggle('active', isAct);
    if (icon) {
      icon.classList.toggle('text-white', isAct);
      icon.classList.toggle('text-[#a1a1aa]', !isAct);
      icon.classList.remove('text-white', 'text-[#71717a]');
    }
  });

  closeDropdownSmoothly('faceDetectMenu', 'faceChevron', 'faceDetectDropdownBtn', 80);
  lucide.createIcons();
}

function setFaceDetect(val) {
  const isTrue = (val === true || val === 'true');
  selectFaceDetectFromMenu(isTrue, isTrue ? 'Face Track' : 'Center Crop');
}

// Quality Dropdown Handlers
function toggleQualityDropdown(e) {
  if (e) e.stopPropagation();
  const menu = document.getElementById('qualityMenu');
  const chev = document.getElementById('qualityChevron');
  const btn = document.getElementById('qualityDropdownBtn');
  const isClosed = menu?.getAttribute('data-open') !== 'true' && !menu?.classList.contains('open');
  closeAllDropdowns(isClosed ? 'qualityMenu' : null);
  if (menu) {
    menu.setAttribute('data-open', isClosed ? 'true' : 'false');
    menu.classList.toggle('open', isClosed);
    if (chev) chev.classList.toggle('rotate-180', isClosed);
    if (btn) {
      btn.setAttribute('aria-expanded', isClosed ? 'true' : 'false');
      btn.classList.toggle('active', isClosed);
    }
    if (isClosed) alignMenuIndicator('qualityMenu');
  }
}

function selectQualityFromMenu(q, label) {
  selectedQuality = q;
  const labelEl = document.getElementById('currentQualityLabel');
  if (labelEl) labelEl.innerText = label;

  document.querySelectorAll('.quality-menu-item[data-quality]').forEach(item => {
    const isAct = item.getAttribute('data-quality') === q;
    item.classList.toggle('active', isAct);
  });

  closeDropdownSmoothly('qualityMenu', 'qualityChevron', 'qualityDropdownBtn', 80);
}

    // Video Ratio Dropdown Handlers
function toggleVideoRatioDropdown(e) {
  if (e) e.stopPropagation();
  const menu = document.getElementById('videoRatioMenu');
  const chev = document.getElementById('videoRatioChevron');
  const btn = document.getElementById('videoRatioDropdownBtn');
  const isClosed = menu?.getAttribute('data-open') !== 'true' && !menu?.classList.contains('open');
  closeAllDropdowns(isClosed ? 'videoRatioMenu' : null);
  if (menu) {
    menu.setAttribute('data-open', isClosed ? 'true' : 'false');
    menu.classList.toggle('open', isClosed);
    if (chev) chev.classList.toggle('rotate-180', isClosed);
    if (btn) {
      btn.setAttribute('aria-expanded', isClosed ? 'true' : 'false');
      btn.classList.toggle('active', isClosed);
    }
    if (isClosed) alignMenuIndicator('videoRatioMenu');
  }
}

function selectVideoRatioFromMenu(r, label) {
  selectedVideoRatio = r;
  const labelEl = document.getElementById('currentVideoRatioLabel');
  if (labelEl) labelEl.innerText = label;

  document.querySelectorAll('#videoRatioMenu .quality-menu-item[data-vratio]').forEach(item => {
    const isAct = item.getAttribute('data-vratio') === r;
    item.classList.toggle('active', isAct);
  });

  closeDropdownSmoothly('videoRatioMenu', 'videoRatioChevron', 'videoRatioDropdownBtn', 80);
}

// Video FPS Dropdown Handlers
function toggleVideoFpsDropdown(e) {
  if (e) e.stopPropagation();
  const menu = document.getElementById('videoFpsMenu');
  const chev = document.getElementById('videoFpsChevron');
  const btn = document.getElementById('videoFpsDropdownBtn');
  const isClosed = menu?.getAttribute('data-open') !== 'true' && !menu?.classList.contains('open');
  closeAllDropdowns(isClosed ? 'videoFpsMenu' : null);
  if (menu) {
    menu.setAttribute('data-open', isClosed ? 'true' : 'false');
    menu.classList.toggle('open', isClosed);
    if (chev) chev.classList.toggle('rotate-180', isClosed);
    if (btn) {
      btn.setAttribute('aria-expanded', isClosed ? 'true' : 'false');
      btn.classList.toggle('active', isClosed);
    }
    if (isClosed) alignMenuIndicator('videoFpsMenu');
  }
}

function selectVideoFpsFromMenu(fps, label) {
  selectedVideoFps = fps;
  const labelEl = document.getElementById('currentVideoFpsLabel');
  if (labelEl) labelEl.innerText = label;

  document.querySelectorAll('#videoFpsMenu .quality-menu-item[data-vfps]').forEach(item => {
    const isAct = item.getAttribute('data-vfps') === fps;
    item.classList.toggle('active', isAct);
  });

  closeDropdownSmoothly('videoFpsMenu', 'videoFpsChevron', 'videoFpsDropdownBtn', 80);
}

function setQuality(q) {
  const labels = { '1080': '1080p FHD', '720': '720p HD', '480': '480p SD' };
  selectQualityFromMenu(q, labels[q] || `${q}p`);
}

// Trim Ratio Selector (Chips)
function setTrimRatio(r) {
  selectedTrimRatio = r;
  ['916', '169', '34'].forEach(tr => {
    const btn = document.getElementById(`trimR-${tr}`);
    if (btn) btn.classList.remove('active');
  });
  const active = document.getElementById(`trimR-${r.replace(':', '')}`);
  if (active) active.classList.add('active');
}

// Close dropdowns when clicked outside
document.addEventListener('click', (e) => {
  const isDropdownClick = e.target.closest(
    '#platformDropdownBtn, #platformMenu, #subFeatureDropdownBtn, #subFeatureMenu, ' +
    '#aspectRatioDropdownBtn, #aspectRatioMenu, #clipCountDropdownBtn, #clipCountMenu, ' +
    '#faceDetectDropdownBtn, #faceDetectMenu, #qualityDropdownBtn, #qualityMenu, #videoRatioDropdownBtn, #videoRatioMenu, #videoFpsDropdownBtn, #videoFpsMenu, #trimRatioDropdownBtn, #trimRatioMenu'
  );
  if (!isDropdownClick) {
    closeAllDropdowns(null);
  }
  const isWsDropdownClick = e.target.closest('#wsDropdownWrapper');
  if (!isWsDropdownClick && typeof closeWsDropdown === 'function') {
    closeWsDropdown();
  }
});

function setLang(lang) {
  currentLang = lang || 'id';
}

// Initialize Default Platform & Sub-features
switchPlatform('youtube', false);
setLang('id');

// Transitions.dev task configurations and dynamic task rows
const TASK_CONFIGS = {
  type_yt_ai_clip: [
    {
      key: 'ingest',
      label: 'Ingest Video',
      amount: 'Source Video',
      details: [
        { label: 'Video and audio streams', meta: 'Chosen quality' },
        { label: 'Demux audio and video streams', meta: 'Direct Stream' }
      ]
    },
    {
      key: 'check_sub',
      label: 'Checking transcript',
      amount: 'YouTube API',
      details: [
        { label: 'Searching for auto-captions and official subtitles', meta: 'Auto API' },
        { label: 'Reading subtitle timestamps', meta: 'Per segment' }
      ]
    },
    {
      key: 'whisper',
      label: 'Audio transcription',
      amount: 'Cloud API',
      details: [
        { label: 'Speech-to-text fallback', meta: 'When no subtitles' },
        { label: 'Groq, Gemini or local Faster-Whisper', meta: 'Many languages' }
      ]
    },
    {
      key: 'virality',
      label: 'Viral Potential & Hook Analysis',
      amount: 'Hook Scoring',
      details: [
        { label: 'Viral potential and retention score', meta: 'Top Hooks' },
        { label: 'Vertical framing and hook detection', meta: '9:16' }
      ]
    },
    {
      key: 'render',
      label: 'Render Vertical Clips',
      amount: 'H.264',
      details: [
        { label: 'Hardware encoder when available', meta: 'AMF, MF or x264' },
        { label: 'Multi-clip MP4 encoding', meta: 'H.264 MP4' }
      ]
    }
  ],

  type_yt_video: [
    {
      key: 'download',
      label: 'Downloading Video 1080p',
      amount: '1080p FHD',
      details: [
        { label: 'High-speed video and audio stream', meta: 'Direct Stream' },
        { label: 'Lossless merge into MP4', meta: 'Lossless' }
      ]
    },
    {
      key: 'vault',
      label: 'Saving to Media Vault',
      amount: 'Waiting',
      details: [
        { label: 'Adding to the local storage catalog', meta: 'Waiting' },
        { label: 'Files are ready to play or download', meta: 'Ready' }
      ]
    }
  ],

  type_yt_mp3: [
    {
      key: 'extract',
      label: 'Downloading source audio',
      amount: 'HQ Audio',
      details: [
        { label: 'Extracting full-resolution audio', meta: 'Opus/M4A' },
        { label: 'Normalizing stereo channels', meta: 'Stereo' }
      ]
    },
    {
      key: 'vault',
      label: 'Convert to 320 kbps MP3 & Save',
      amount: 'Waiting',
      details: [
        { label: 'High-quality FFmpeg LAME encoding', meta: 'CBR 320k' },
        { label: 'Saving to the local Media Vault', meta: 'Waiting' }
      ]
    }
  ],

  type_yt_clip: [
    {
      key: 'trim',
      label: 'Trimming video segments',
      amount: 'Custom Range',
      details: [
        { label: 'Validating clip time range', meta: 'Keyframe' },
        { label: 'Hardware-accelerated segment extraction', meta: 'Fast Cut' }
      ]
    },
    {
      key: 'vault',
      label: 'Saving to Media Vault',
      amount: 'Waiting',
      details: [
        { label: 'Adding the trimmed video to the library', meta: 'Waiting' },
        { label: 'File is ready to share', meta: 'Ready' }
      ]
    }
  ],

  type_ig_reels: [
    {
      key: 'download',
      label: 'Downloading Instagram Reels',
      amount: 'Reel Stream',
      details: [
        { label: 'Download video without a watermark', meta: 'Lossless' },
        { label: 'Verifying MP4 stream integrity', meta: 'Checked' }
      ]
    },
    {
      key: 'vault',
      label: 'Saving to Media Vault',
      amount: 'Waiting',
      details: [
        { label: 'Saving to the Instagram folder', meta: 'Waiting' },
        { label: 'File is ready for offline viewing', meta: 'Ready' }
      ]
    }
  ],

  type_tt_video: [
    {
      key: 'download',
      label: 'Downloading TikTok video (no watermark)',
      amount: 'TikTok HD',
      details: [
        { label: 'Bypass lapisan watermark TikTok', meta: 'HD Clean' },
        { label: 'Mux into a full-resolution MP4 container', meta: 'Ready' }
      ]
    },
    {
      key: 'vault',
      label: 'Saving to Media Vault',
      amount: 'Waiting',
      details: [
        { label: 'Saving to the TikTok folder', meta: 'Waiting' },
        { label: 'File is ready to use', meta: 'Ready' }
      ]
    }
  ],

  type_tt_mp3: [
    {
      key: 'extract',
      label: 'Downloading TikTok audio',
      amount: 'Sound Track',
      details: [
        { label: 'Extracting audio from the TikTok stream', meta: 'HQ Audio' },
        { label: 'Normalizing dynamics and volume', meta: 'Balanced' }
      ]
    },
    {
      key: 'vault',
      label: 'Convert to 320 kbps MP3 & Save',
      amount: 'Waiting',
      details: [
        { label: 'Encoding FFmpeg LAME 320kbps', meta: 'MP3' },
        { label: 'Saving to the local Media Vault', meta: 'Waiting' }
      ]
    }
  ]
};

let currentActionType = 'type_yt_video';
let currentTaskRows = [];
let highestJobProgress = 0;

function initTaskRows(action) {
  currentActionType = action || 'type_yt_video';
  highestJobProgress = 0;
  const template = TASK_CONFIGS[currentActionType] || TASK_CONFIGS.type_yt_video;
  currentTaskRows = template.map((t, idx) => ({
    key: t.key,
    label: t.label,
    amount: t.amount,
    status: idx === 0 ? 'running' : 'pending',
    step: idx + 1,
    details: t.details || []
  }));

  const container = document.getElementById('taskRowsContainer');
  if (!container) return;

  container.innerHTML = currentTaskRows.map((row, idx) => {
    const badgeHtml = getBadgeHtml(row.status, row.step);
    const pillHtml = getPillHtml(row.status);

    const detailsHtml = (row.details || []).map(d => `
      <div class="flex items-center justify-between text-[11.5px]">
        <span class="text-zinc-300">${escapeHtml(d.label)}</span>
        <span class="font-mono text-[11px] text-zinc-500 tabular-nums">${escapeHtml(d.meta)}</span>
      </div>
    `).join('');

    return `
      <div 
        id="task-row-${row.key}"
        class="task-row-card self-stretch overflow-hidden border border-white/[0.08] bg-white/[0.025] hover:bg-white/[0.05] transition-all duration-300 relative flex flex-col"
        style="border-radius: 20px; animation: fade-up 450ms cubic-bezier(0.23,1,0.32,1) ${idx * 80}ms both;"
      >
        <button
          type="button"
          id="task-btn-${row.key}"
          aria-expanded="false"
          onclick="toggleTaskRowAccordion('${row.key}')"
          class="flex h-11 w-full items-center gap-2.5 px-3 text-left cursor-pointer select-none bg-transparent border-none"
        >
          <span id="task-badge-${row.key}" class="flex size-6 shrink-0 items-center justify-center">
            ${badgeHtml}
          </span>
          <span id="task-label-${row.key}" class="min-w-0 flex-1 truncate text-[13px] font-medium ${row.status === 'done' ? 'text-white' : (row.status === 'running' ? 'text-zinc-200' : 'text-zinc-400')}">
            ${escapeHtml(row.label)}
          </span>
          <span id="task-amount-${row.key}" class="text-[11.5px] text-zinc-400 tabular-nums font-mono">${escapeHtml(row.amount)}</span>
          <span id="task-pill-${row.key}">
            ${pillHtml}
          </span>
          <span
            aria-hidden="true"
            class="-ml-1 flex size-7 shrink-0 items-center justify-center rounded-full text-zinc-400 transition-colors hover:text-white"
          >
            <svg
              id="task-chevron-${row.key}"
              width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"
              class="transition-transform duration-300"
              style="transform: rotate(0deg);"
            >
              <path d="M6 9l6 6 6-6" />
            </svg>
          </span>
        </button>

        <!-- Dedicated progress indicator area: Enlarges card height specifically for the indicator, inset with side padding -->
        <div id="task-progress-box-${row.key}" class="px-3.5 pb-2.5 pt-0.5 ${row.status === 'running' ? '' : 'hidden'}">
          <div class="flex items-center justify-between text-[11px] mb-1.5 font-mono">
            <div class="flex items-center gap-2 min-w-0">
              <span id="task-progress-pct-${row.key}" class="text-emerald-400 font-semibold tabular-nums text-[11.5px] ${row.key === 'download' || row.key === 'ingest' ? '' : 'hidden'}">0%</span>
              <span id="task-progress-stage-${row.key}" class="text-zinc-300 text-[11px] font-sans truncate ${row.key === 'download' || row.key === 'ingest' ? 'hidden' : ''}">Preparing...</span>
            </div>
            <div class="flex items-center gap-2.5 text-zinc-400 tabular-nums text-[11px] shrink-0">
              <span id="task-progress-meta-${row.key}">Connecting to stream...</span>
              <span id="task-stopwatch-${row.key}" class="inline-flex items-center gap-1 text-zinc-300 font-mono text-[11px] pl-1.5 border-l border-white/10">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" class="text-emerald-400 shrink-0">
                  <circle cx="12" cy="12" r="10"></circle>
                  <polyline points="12 6 12 12 16 14"></polyline>
                </svg>
                <span id="task-stopwatch-val-${row.key}">00:00</span>
              </span>
            </div>
          </div>
          <div class="w-full h-1.5 bg-white/[0.07] rounded-full overflow-hidden p-[1px] relative">
            <div id="task-progress-fill-${row.key}" class="h-full bg-emerald-400 rounded-full transition-all duration-300 ${row.key === 'download' || row.key === 'ingest' ? '' : 'task-indeterminate-bar'}" style="width: ${row.key === 'download' || row.key === 'ingest' ? '0%' : '35%'};"></div>
          </div>
        </div>

        <div
          id="task-details-${row.key}"
          class="task-details-grid grid transition-[grid-template-rows,opacity] duration-300"
          style="grid-template-rows: 0fr; opacity: 0; transition-timing-function: cubic-bezier(0.23, 1, 0.32, 1);"
        >
          <div class="overflow-hidden">
            <div class="mb-2.5 grid grid-cols-[24px_1fr] gap-2.5 px-3">
              <span aria-hidden="true" class="mx-auto h-full w-px bg-white/10"></span>
              <div class="flex flex-col gap-1.5 pt-0.5 pb-1">
                ${detailsHtml}
              </div>
            </div>
          </div>
        </div>
      </div>
    `;
  }).join('');
}

function toggleTaskRowAccordion(key) {
  const detailsEl = document.getElementById(`task-details-${key}`);
  const chevEl = document.getElementById(`task-chevron-${key}`);
  const cardEl = document.getElementById(`task-row-${key}`);
  const btnEl = document.getElementById(`task-btn-${key}`);
  if (!detailsEl) return;

  const isOpen = detailsEl.style.gridTemplateRows === '1fr';
  if (isOpen) {
    detailsEl.style.gridTemplateRows = '0fr';
    detailsEl.style.opacity = '0';
    if (chevEl) chevEl.style.transform = 'rotate(0deg)';
    if (cardEl) cardEl.style.borderRadius = '20px';
    if (btnEl) btnEl.setAttribute('aria-expanded', 'false');
  } else {
    detailsEl.style.gridTemplateRows = '1fr';
    detailsEl.style.opacity = '1';
    if (chevEl) chevEl.style.transform = 'rotate(180deg)';
    if (cardEl) cardEl.style.borderRadius = '14px';
    if (btnEl) btnEl.setAttribute('aria-expanded', 'true');
  }
}

let taskStartTimestamps = {};
let taskDurations = {};
let taskElapsedTimer = null;

function formatStopwatch(ms) {
  const totalSec = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m < 10 ? '0' : ''}${m}:${s < 10 ? '0' : ''}${s}`;
}

function ensureStopwatchRunning() {
  if (taskElapsedTimer) return;
  taskElapsedTimer = setInterval(() => {
    const now = Date.now();
    currentTaskRows.forEach(row => {
      if (row.status === 'running' && taskStartTimestamps[row.key]) {
        const elapsedMs = now - taskStartTimestamps[row.key];
        const swEl = document.getElementById(`task-stopwatch-val-${row.key}`);
        if (swEl) swEl.innerText = formatStopwatch(elapsedMs);
      }
    });
  }, 1000);
}

function setTaskStatuses(statusArr, progressData, computedProgressPct) {
  statusArr.forEach((newStatus, idx) => {
    const row = currentTaskRows[idx];
    if (!row) return;

    const statusChanged = row.status !== newStatus;
    row.status = newStatus;
    const badgeEl = document.getElementById(`task-badge-${row.key}`);
    const pillEl = document.getElementById(`task-pill-${row.key}`);
    const labelEl = document.getElementById(`task-label-${row.key}`);
    const progressBoxEl = document.getElementById(`task-progress-box-${row.key}`);
    const progressPctEl = document.getElementById(`task-progress-pct-${row.key}`);
    const progressStageEl = document.getElementById(`task-progress-stage-${row.key}`);
    const progressMetaEl = document.getElementById(`task-progress-meta-${row.key}`);
    const progressFillEl = document.getElementById(`task-progress-fill-${row.key}`);

    if (statusChanged && badgeEl) {
      badgeEl.innerHTML = getBadgeHtml(newStatus, row.step);
    }
    if (statusChanged && pillEl) {
      pillEl.innerHTML = getPillHtml(newStatus);
    }
    if (statusChanged && labelEl) {
      labelEl.className = `min-w-0 flex-1 truncate text-[13px] font-medium ${
        newStatus === 'done' ? 'text-white' : (newStatus === 'running' ? 'text-zinc-200' : 'text-zinc-400')
      }`;
    }

    const currentStage = (progressData && progressData.stage) || '';
    const amountEl = document.getElementById(`task-amount-${row.key}`);

    if (newStatus === 'running') {
      if (!taskStartTimestamps[row.key]) {
        taskStartTimestamps[row.key] = Date.now();
        ensureStopwatchRunning();
      }
    } else if (newStatus === 'done') {
      if (taskStartTimestamps[row.key] && !taskDurations[row.key]) {
        const elapsedSec = Math.max(1, Math.round((Date.now() - taskStartTimestamps[row.key]) / 1000));
        taskDurations[row.key] = elapsedSec < 60 ? `${elapsedSec}s` : `${Math.floor(elapsedSec / 60)}m ${elapsedSec % 60}s`;
        if (amountEl) {
          amountEl.innerText = taskDurations[row.key];
        }
      }
    }

    if (amountEl && !taskDurations[row.key]) {
      if (row.key === 'vault') {
        if (newStatus === 'done') {
          amountEl.innerText = 'Saved';
        } else if (newStatus === 'running') {
          amountEl.innerText = 'Saving...';
        } else if (newStatus === 'failed') {
          amountEl.innerText = 'Failed';
        } else {
          amountEl.innerText = 'Waiting';
        }
      } else if (row.key === 'check_sub') {
        if (newStatus === 'done') {
          amountEl.innerText = currentStage === 'transcript_found' ? 'Found' : 'Checked';
        } else if (newStatus === 'running') {
          amountEl.innerText = 'Checking...';
        }
      } else if (row.key === 'whisper') {
        if (currentStage === 'transcript_found') {
          amountEl.innerText = 'Available';
        } else if (newStatus === 'running') {
          amountEl.innerText = 'Transcribing...';
        } else if (newStatus === 'done') {
          amountEl.innerText = 'Complete';
        }
      }
    }

    // Dedicated indicator box handling
    if (progressBoxEl) {
      if (newStatus === 'running') {
        progressBoxEl.classList.remove('hidden');
        const isDownload = (row.key === 'download' || row.key === 'ingest');

        if (isDownload) {
          if (progressPctEl) progressPctEl.classList.remove('hidden');
          if (progressStageEl) progressStageEl.classList.add('hidden');
          if (progressFillEl) progressFillEl.classList.remove('task-indeterminate-bar');

          const pctVal = typeof computedProgressPct === 'number' ? computedProgressPct : 0;
          const pctFormatted = `${pctVal.toFixed(pctVal % 1 === 0 ? 0 : 1)}%`;
          if (progressPctEl) progressPctEl.innerText = pctFormatted;

          const speed = (progressData && progressData.download_speed) || '';
          const eta = (progressData && progressData.download_eta) ? `ETA ${progressData.download_eta}` : '';
          const metaStr = [speed, eta].filter(Boolean).join(' • ') || 'Connecting to stream...';
          if (progressMetaEl) {
            progressMetaEl.innerText = metaStr;
            progressMetaEl.classList.remove('hidden');
          }

          if (progressFillEl) {
            progressFillEl.style.width = `${Math.min(100, Math.max(0, pctVal))}%`;
          }
        } else {
          // Indeterminate: No misleading percentage number! Clean active beam & description
          if (progressPctEl) progressPctEl.classList.add('hidden');
          if (progressStageEl) {
            progressStageEl.classList.remove('hidden');
            progressStageEl.innerText = (progressData && progressData.stage_detail) || 'Processing...';
          }
          if (progressMetaEl) progressMetaEl.classList.add('hidden');
          if (progressFillEl) {
            progressFillEl.classList.add('task-indeterminate-bar');
          }
        }
      } else {
        progressBoxEl.classList.add('hidden');
        if (progressFillEl) {
          progressFillEl.classList.remove('task-indeterminate-bar');
          progressFillEl.style.width = newStatus === 'done' ? '100%' : '0%';
        }
      }
    }
  });
}

function getBadgeHtml(status, step) {
  if (status === 'done') {
    return `
      <span class="flex w-[22px] h-[22px] shrink-0 items-center justify-center rounded-full text-black bg-emerald-400" style="animation: pop-in 300ms cubic-bezier(0.23,1,0.32,1) both;">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M20 6L9 17l-5-5"/>
        </svg>
      </span>
    `;
  } else if (status === 'running') {
    const size = 24, stroke = 2;
    const r = (size - stroke) / 2;
    const c = 2 * Math.PI * r;
    return `
      <span class="relative inline-flex shrink-0 items-center justify-center" style="width: 24px; height: 24px;">
        <svg width="24" height="24" class="absolute inset-0 animate-spin">
          <circle cx="12" cy="12" r="${r}" fill="none" stroke="rgba(255,255,255,0.12)" stroke-width="${stroke}" />
          <circle cx="12" cy="12" r="${r}" fill="none" stroke="#ffffff" stroke-width="${stroke}" stroke-linecap="round" stroke-dasharray="${(c * 0.28).toFixed(1)} ${(c * 0.72).toFixed(1)}" />
        </svg>
        <span class="relative text-[10.5px] font-semibold tabular-nums text-white">${step}</span>
      </span>
    `;
  } else if (status === 'failed') {
    return `
      <span class="flex w-[22px] h-[22px] shrink-0 items-center justify-center rounded-full text-white bg-rose-500 shadow-sm" style="animation: pop-in 300ms cubic-bezier(0.23,1,0.32,1) both;">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.5" stroke-linecap="round">
          <path d="M18 6L6 18M6 6l12 12"/>
        </svg>
      </span>
    `;
  } else {
    const size = 24, stroke = 2;
    const r = (size - stroke) / 2;
    return `
      <span class="relative inline-flex shrink-0 items-center justify-center" style="width: 24px; height: 24px;">
        <svg width="24" height="24" class="absolute inset-0">
          <circle cx="12" cy="12" r="${r}" fill="none" stroke="rgba(255,255,255,0.10)" stroke-width="${stroke}" />
        </svg>
        <span class="relative text-[10.5px] font-semibold tabular-nums text-zinc-500">${step}</span>
      </span>
    `;
  }
}

function getPillHtml(status) {
  if (status === 'done') {
    return `
      <span class="inline-flex h-5 items-center rounded-full bg-emerald-500/15 border border-emerald-500/30 px-2 text-[10.5px] font-medium text-emerald-400" style="animation: pop-in 250ms ease-out both;">
        Completed
      </span>
    `;
  } else if (status === 'failed') {
    return `
      <span class="inline-flex h-5 items-center gap-1.5 rounded-full bg-rose-500/15 border border-rose-500/25 px-2 text-[10.5px] font-medium text-rose-400" style="animation: pop-in 200ms ease-out both;">
        Failed
      </span>
    `;
  }
  return '';
}

// Workspace Confirmation & Trigger Action
function getPipelineLabel(act) {
  if (act === 'type_yt_ai_clip' || act === 'ai_clip') return 'AI Shorts 9:16 Virality';
  if (act === 'type_yt_video') return `YouTube Full Video (${selectedQuality}p)`;
  if (act === 'type_yt_short') return 'YouTube Shorts Clean';
  if (act === 'type_yt_mp3' || act === 'type_tt_mp3') return 'Audio MP3 320kbps';
  if (act === 'type_yt_clip') return 'Manual Video Trimmer';
  if (act === 'type_ig_reels') return 'Instagram Reels Full HD';
  if (act === 'type_tt_video') return 'TikTok Clean (No Watermark)';
  return 'Media Download';
}

function showNoticeModal(heading, desc) {
  const modal = document.getElementById('noticeModal');
  const box = document.getElementById('noticeModalBox');
  const h = document.getElementById('noticeModalHeading');
  const p = document.getElementById('noticeModalDesc');
  if (!modal || !box) return;
  if (h) h.innerText = heading || 'Notice';
  if (p) p.innerText = desc || '';
  modal.classList.remove('hidden');
  requestAnimationFrame(() => {
    box.classList.remove('scale-95', 'opacity-0');
    box.classList.add('scale-100', 'opacity-100');
  });
}

function closeNoticeModal() {
  const modal = document.getElementById('noticeModal');
  const box = document.getElementById('noticeModalBox');
  if (box) {
    box.classList.remove('scale-100', 'opacity-100');
    box.classList.add('scale-95', 'opacity-0');
  }
  setTimeout(() => {
    if (modal) modal.classList.add('hidden');
  }, 150);
}

function showConfirmModal(heading, desc, proceedLabel) {
  return new Promise((resolve) => {
    const modal = document.getElementById('confirmModal');
    const box = document.getElementById('confirmModalBox');
    const h = document.getElementById('confirmModalHeading');
    const p = document.getElementById('confirmModalDesc');
    const cancelBtn = document.getElementById('confirmModalCancelBtn');
    const proceedBtn = document.getElementById('confirmModalProceedBtn');
    if (!modal || !box) {
      resolve(true);
      return;
    }
    if (h) h.innerText = heading || 'Confirmation';
    if (p) p.innerText = desc || '';
    if (proceedBtn) proceedBtn.innerText = proceedLabel || 'Continue';
    modal.classList.remove('hidden');
    requestAnimationFrame(() => {
      box.classList.remove('scale-95', 'opacity-0');
      box.classList.add('scale-100', 'opacity-100');
    });

    const cleanup = (result) => {
      box.classList.remove('scale-100', 'opacity-100');
      box.classList.add('scale-95', 'opacity-0');
      setTimeout(() => {
        modal.classList.add('hidden');
        resolve(result);
      }, 150);
    };

    if (cancelBtn) cancelBtn.onclick = () => cleanup(false);
    if (proceedBtn) proceedBtn.onclick = () => cleanup(true);
  });
}

function isValidMediaUrl(str) {
  if (!str) return false;
  const s = str.trim();
  if (!s.startsWith('http://') && !s.startsWith('https://')) return false;
  try {
    const u = new URL(s);
    return Boolean(u.hostname && u.hostname.includes('.'));
  } catch (_) {
    return false;
  }
}

function triggerAction() {
  if (activeJobId || isProcessStarting) {
    showNoticeModal('A job is in progress', 'Another job is running. Wait for it to finish or cancel it before starting a new one.');
    return;
  }
  const url = mainUrlInput.value.trim();
  if (!url) {
    mainUrlInput.focus();
    mainUrlInput.classList.add('ring-2', 'ring-red-500/60');
    setTimeout(() => mainUrlInput.classList.remove('ring-2', 'ring-red-500/60'), 1500);
    showNoticeModal('URL is required', 'Enter a YouTube, Instagram, or TikTok video URL.');
    return;
  }

  if (!isValidMediaUrl(url)) {
    mainUrlInput.focus();
    mainUrlInput.classList.add('ring-2', 'ring-red-500/60');
    setTimeout(() => mainUrlInput.classList.remove('ring-2', 'ring-red-500/60'), 1500);
    showNoticeModal('Invalid URL', 'The video URL is invalid or incomplete. Make sure it starts with https:// and belongs to a supported platform.');
    return;
  }

  let action = '';
  if (currentPlatform === 'youtube') action = currentYtSub;
  else if (currentPlatform === 'instagram') action = currentIgSub;
  else if (currentPlatform === 'tiktok') action = currentTtSub;

  openWorkspaceModal(action);
}

async function fetchNextWorkspaceIndex(action) {
  try {
    const res = await fetch('/api/vault/projects');
    if (res.ok) {
      const data = await res.json();
      if (data.next_workspace_index) return data.next_workspace_index;
      if (data.projects && data.projects.length > 0) return data.projects.length + 1;
    }
  } catch (e) {
    console.warn('fetchNextWorkspaceIndex error:', e);
  }
  return nextWorkspaceIndex || 1;
}

window.checkDuplicateWorkspaceName = function (val) {
  const notice = document.getElementById('wsDuplicateNotice');
  if (!notice) return;
  const cleanVal = (val || '').trim().toLowerCase();
  if (!cleanVal) {
    notice.classList.add('hidden');
    return;
  }
  const exists = (vaultProjects || []).some(p => (p.workspace_name || '').trim().toLowerCase() === cleanVal);
  if (exists) {
    notice.classList.remove('hidden');
  } else {
    notice.classList.add('hidden');
  }
};

let latestVideoTitle = { url: '', title: '' };
let currentWorkspaceMode = 'new';
let currentJobProjectId = null;
let currentJobWorkspaceName = null;

window.setWorkspaceMode = function (mode) {
  currentWorkspaceMode = mode;
  const btnNew = document.getElementById('wsModeNewBtn');
  const btnExisting = document.getElementById('wsModeExistingBtn');
  const containerNew = document.getElementById('wsNewContainer');
  const containerExisting = document.getElementById('wsExistingContainer');
  const inputNew = document.getElementById('wsModalInput');
  const selectExisting = document.getElementById('wsExistingSelect');

  if (mode === 'new') {
    if (btnNew) {
      btnNew.className = 'flex-1 py-1.5 px-3 rounded-lg text-xs font-semibold transition cursor-pointer bg-white/[0.08] text-white shadow-sm flex items-center justify-center gap-1.5';
    }
    if (btnExisting) {
      btnExisting.className = 'flex-1 py-1.5 px-3 rounded-lg text-xs font-medium transition cursor-pointer text-zinc-400 hover:text-white flex items-center justify-center gap-1.5';
    }
    if (containerNew) containerNew.classList.remove('hidden');
    if (containerExisting) containerExisting.classList.add('hidden');
    if (inputNew) {
      setTimeout(() => {
        inputNew.focus();
        try { inputNew.select(); } catch (e) {}
      }, 50);
    }
  } else {
    if (btnExisting) {
      btnExisting.className = 'flex-1 py-1.5 px-3 rounded-lg text-xs font-semibold transition cursor-pointer bg-white/[0.08] text-white shadow-sm flex items-center justify-center gap-1.5';
    }
    if (btnNew) {
      btnNew.className = 'flex-1 py-1.5 px-3 rounded-lg text-xs font-medium transition cursor-pointer text-zinc-400 hover:text-white flex items-center justify-center gap-1.5';
    }
    if (containerNew) containerNew.classList.add('hidden');
    if (containerExisting) containerExisting.classList.remove('hidden');
    const trigger = document.getElementById('wsDropdownTrigger');
    if (trigger) trigger.focus();
  }
  lucide.createIcons();
};

window.toggleWsDropdown = function (e) {
  if (e) {
    e.stopPropagation();
    e.preventDefault();
  }
  const menu = document.getElementById('wsDropdownMenu');
  const chevron = document.getElementById('wsDropdownChevron');
  if (!menu) return;
  const isHidden = menu.classList.contains('hidden');
  if (isHidden) {
    menu.classList.remove('hidden');
    if (chevron) chevron.classList.add('rotate-180');
  } else {
    menu.classList.add('hidden');
    if (chevron) chevron.classList.remove('rotate-180');
  }
};

window.closeWsDropdown = function () {
  const menu = document.getElementById('wsDropdownMenu');
  const chevron = document.getElementById('wsDropdownChevron');
  if (menu) menu.classList.add('hidden');
  if (chevron) chevron.classList.remove('rotate-180');
};

document.addEventListener('click', (e) => {
  const wrap = document.getElementById('wsDropdownWrapper');
  if (wrap && !wrap.contains(e.target)) {
    closeWsDropdown();
  }
});

window.selectCustomWorkspace = function (wsName) {
  const hiddenInput = document.getElementById('wsExistingSelect');
  if (hiddenInput) hiddenInput.value = wsName;

  const proj = vaultProjects.find(p => p.workspace_name === wsName);
  const count = proj && proj.files ? proj.files.length : 0;

  const selectedText = document.getElementById('wsDropdownSelectedText');
  const selectedBadge = document.getElementById('wsDropdownSelectedBadge');
  if (selectedText) selectedText.innerText = wsName;
  if (selectedBadge) {
    selectedBadge.innerText = `${count} file`;
    selectedBadge.classList.remove('hidden');
  }

  closeWsDropdown();
  populateExistingWorkspacesSelect(wsName);
};

window.populateExistingWorkspacesSelect = function (preselectedName = null) {
  const hiddenInput = document.getElementById('wsExistingSelect');
  const listContainer = document.getElementById('wsDropdownList');
  const selectedText = document.getElementById('wsDropdownSelectedText');
  const selectedBadge = document.getElementById('wsDropdownSelectedBadge');
  const triggerBtn = document.getElementById('wsDropdownTrigger');
  if (!listContainer) return;

  listContainer.innerHTML = '';

  if (vaultProjects.length === 0) {
    if (hiddenInput) hiddenInput.value = '';
    if (selectedText) selectedText.innerText = 'No workspaces in Media Vault yet';
    if (selectedBadge) selectedBadge.classList.add('hidden');
    if (triggerBtn) triggerBtn.disabled = true;

    const emptyItem = document.createElement('div');
    emptyItem.className = 'px-3 py-3 text-center text-xs text-zinc-500 font-sans';
    emptyItem.innerText = 'No workspaces in Media Vault yet';
    listContainer.appendChild(emptyItem);
    return;
  }

  if (triggerBtn) triggerBtn.disabled = false;

  let activeName = preselectedName || (hiddenInput ? hiddenInput.value : '');
  if (!activeName || !vaultProjects.some(p => p.workspace_name === activeName)) {
    activeName = vaultProjects[0].workspace_name;
  }
  if (hiddenInput) hiddenInput.value = activeName;

  const activeProj = vaultProjects.find(p => p.workspace_name === activeName) || vaultProjects[0];
  const activeCount = (activeProj && activeProj.files) ? activeProj.files.length : 0;
  if (selectedText) selectedText.innerText = activeProj.workspace_name;
  if (selectedBadge) {
    selectedBadge.innerText = `${activeCount} file`;
    selectedBadge.classList.remove('hidden');
  }

  vaultProjects.forEach(p => {
    const isSelected = p.workspace_name === activeName;
    const count = (p.files || []).length;
    const itemBtn = document.createElement('button');
    itemBtn.type = 'button';
    itemBtn.className = `w-full px-2.5 py-1.5 rounded-lg flex items-center justify-between text-left text-[11px] transition cursor-pointer group ${isSelected
      ? 'bg-white/10 text-zinc-100 font-semibold border border-white/20'
      : 'text-zinc-300 hover:bg-white/[0.06] hover:text-white border border-transparent'
      }`;
    itemBtn.onclick = () => selectCustomWorkspace(p.workspace_name);

    itemBtn.innerHTML = `
      <div class="flex items-center gap-2 truncate min-w-0 pr-2">
        <i data-lucide="folder" class="w-3.5 h-3.5 ${isSelected ? 'text-white' : 'text-zinc-500 group-hover:text-white'} shrink-0 transition-colors"></i>
        <span class="truncate">${escapeHtml(p.workspace_name)}</span>
      </div>
      <span class="text-[9.5px] font-mono ${isSelected ? 'text-white bg-white/10' : 'text-zinc-500 bg-white/[0.04]'} px-1.5 py-0.5 rounded shrink-0">${count} file</span>
    `;
    listContainer.appendChild(itemBtn);
  });
  lucide.createIcons();
};

async function openWorkspaceModal(action) {
  const modal = document.getElementById('workspaceConfirmModal');
  const wsInput = document.getElementById('wsModalInput');
  const pipelineSummary = document.getElementById('wsModalPipelineSummary');
  const notice = document.getElementById('wsDuplicateNotice');
  if (notice) notice.classList.add('hidden');

  if (pipelineSummary) {
    pipelineSummary.innerText = getPipelineLabel(action);
  }

  let nextNum = nextWorkspaceIndex || 1;

  // Refresh vault projects list to have the freshest workspaces
  try {
    const res = await fetch('/api/vault/projects');
    if (res.ok) {
      const data = await res.json();
      vaultProjects = data.projects || [];
      if (data.next_workspace_index) {
        nextNum = data.next_workspace_index;
        nextWorkspaceIndex = data.next_workspace_index;
      } else if (vaultProjects.length > 0) {
        nextNum = vaultProjects.length + 1;
        nextWorkspaceIndex = nextNum;
      }
    }
  } catch (e) {
    console.warn('Failed fetching vault projects for modal:', e);
  }

  try {
    populateExistingWorkspacesSelect();
    setWorkspaceMode('new');

    const nextNumStr = String(nextNum).padStart(2, '0');
    if (wsInput) {
      const currentUrl = mainUrlInput.value.trim();
      // shortcut: falls back to the numbered name if the preview has not loaded yet
      wsInput.value = latestVideoTitle.url === currentUrl ? latestVideoTitle.title : `Workspace ${nextNumStr}`;
      checkDuplicateWorkspaceName(wsInput.value);
    }
  } catch (err) {
    console.warn('Error setting up workspace inputs:', err);
  }

  if (modal) {
    modal.classList.remove('hidden');
    setTimeout(() => {
      if (wsInput) {
        wsInput.focus();
        try { wsInput.select(); } catch (e) {}
      }
    }, 50);
  }
  lucide.createIcons();
}

function closeWorkspaceModal() {
  if (typeof closeWsDropdown === 'function') closeWsDropdown();
  const modal = document.getElementById('workspaceConfirmModal');
  if (modal) modal.classList.add('hidden');
}

let isProcessStarting = false;

async function confirmAndStartProcess() {
  if (isProcessStarting) return;

  let chosenWs = '';
  if (currentWorkspaceMode === 'existing') {
    const select = document.getElementById('wsExistingSelect');
    chosenWs = select ? select.value.trim() : '';
  } else {
    const wsInput = document.getElementById('wsModalInput');
    chosenWs = wsInput ? wsInput.value.trim() : '';
  }
  if (!chosenWs) {
    chosenWs = `Workspace ${String(nextWorkspaceIndex || 1).padStart(2, '0')}`;
  }
  closeWorkspaceModal();
  await executeActualProcess(chosenWs);
}

async function executeActualProcess(workspaceName) {
  if (isProcessStarting) return;
  isProcessStarting = true;

  try {
    const url = mainUrlInput.value.trim();
    if (!url || !isValidMediaUrl(url)) {
      showNoticeModal('Invalid URL', 'The video URL is invalid or incomplete. Make sure it starts with https:// and belongs to a supported platform.');
      return;
    }

    let action = '';
    if (currentPlatform === 'youtube') action = currentYtSub;
    else if (currentPlatform === 'instagram') action = currentIgSub;
    else if (currentPlatform === 'tiktok') action = currentTtSub;

    if (action === 'type_yt_ai_clip') {
      const origBtnText = mainBtnText ? mainBtnText.innerText : mainActionBtn.textContent;
      mainActionBtn.disabled = true;
      setMainActionLabel('Checking transcript...');
      try {
        const chkRes = await fetch(`/api/check-transcript?url=${encodeURIComponent(url)}`);
        if (chkRes.ok) {
          const chkData = await chkRes.json();
          if (chkData.has_transcript === false) {
            const proceed = await showConfirmModal(
              'No built-in transcript available',
              'This YouTube video has no official transcript. AI audio transcription will take longer. Continue?'
            );
            if (!proceed) {
              mainActionBtn.disabled = false;
              mainActionBtn.classList.remove('opacity-50', 'cursor-not-allowed');
              setMainActionLabel(origBtnText);
              return;
            }
          }
        }
      } catch (e) {
        console.warn('Transcript check error, proceeding:', e);
      } finally {
        setMainActionLabel(origBtnText);
      }
    }

    currentJobWorkspaceName = workspaceName;
    currentJobProjectId = null;

    mainActionBtn.disabled = true;
    mainActionBtn.classList.add('opacity-50', 'cursor-not-allowed');

    progressStateCard.classList.remove('hidden');
    setCancelButtonVisible(true, 'Cancel');
    progressStateCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
    resultsShowcase.classList.add('hidden');

    const compBanner = document.getElementById('progressCompletionBanner');
    if (compBanner) compBanner.classList.add('hidden');

    shortsGalleryGrid.innerHTML = '';

    initTaskRows(action);
    updateProgressUI('queued');

    const payload = {
      url: url,
      action: action,
      workspace_name: workspaceName,
      num_clips: selectedClipCount,
      aspect_ratio: action === 'type_yt_clip' ? selectedTrimRatio : (action === 'type_yt_video' ? selectedVideoRatio : selectedRatio),
      fps: action === 'type_yt_video' ? selectedVideoFps : 'auto',
      use_face_detect: selectedFaceDetect,
      quality: selectedQuality,
      start_time: action === 'type_yt_clip' ? (getAllTrimSegments()[0]?.start_time || '00:00') : '00:00',
      end_time: action === 'type_yt_clip' ? (getAllTrimSegments()[0]?.end_time || '00:30') : '00:30',
      segments: action === 'type_yt_clip' ? getAllTrimSegments() : undefined,
    };

    try {
      const res = await fetch('/api/process', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Could not start the job');
      }

      const data = await res.json();
      activeJobId = data.job_id;
      try {
        localStorage.setItem('luna_active_job_id', activeJobId);
        if (workspaceName) localStorage.setItem('luna_active_ws', workspaceName);
        if (action) localStorage.setItem('luna_active_action', action);
      } catch (e) {}
      jobIdPill.innerText = `JOB-${activeJobId}`;
      startPolling(activeJobId);

    } catch (err) {
      try {
        localStorage.removeItem('luna_active_job_id');
        localStorage.removeItem('luna_active_ws');
        localStorage.removeItem('luna_active_action');
      } catch (e) {}
      mainActionBtn.disabled = false;
      mainActionBtn.classList.remove('opacity-50', 'cursor-not-allowed');
      progressStateCard.classList.add('hidden');
      showNoticeModal('Could not start processing', err.message || 'An error occurred while processing the request.');
    }
  } finally {
    isProcessStarting = false;
  }
}

function setCancelButtonVisible(visible, label) {
  const btn = document.getElementById('btnCancelJob');
  if (!btn) return;
  btn.classList.toggle('hidden', !visible);
  btn.disabled = !visible;
  const text = btn.querySelector('span');
  if (text && label) text.textContent = label;
}

async function cancelActiveJob() {
  try {
    localStorage.removeItem('luna_active_job_id');
    localStorage.removeItem('luna_active_ws');
    localStorage.removeItem('luna_active_action');
  } catch (e) {}

  if (!activeJobId) {
    if (pollInterval) {
      clearInterval(pollInterval);
      pollInterval = null;
    }
    if (taskElapsedTimer) {
      clearInterval(taskElapsedTimer);
      taskElapsedTimer = null;
    }
    progressStateCard.classList.add('hidden');
    setCancelButtonVisible(false);
    mainActionBtn.disabled = false;
    mainActionBtn.classList.remove('opacity-50', 'cursor-not-allowed');
    return;
  }

  try {
    await fetch(`/api/cancel/${activeJobId}`, { method: 'POST' });
  } catch (e) {
    console.warn('Cancel error:', e);
    showToast('The server could not be reached, but the job was stopped locally.', true);
  }

  if (pollInterval) {
    clearInterval(pollInterval);
    pollInterval = null;
  }
  if (taskElapsedTimer) {
    clearInterval(taskElapsedTimer);
    taskElapsedTimer = null;
  }

  currentTaskRows.forEach(r => {
    if (r.status === 'running') {
      r.status = 'failed';
      const b = document.getElementById(`task-badge-${r.key}`);
      const p = document.getElementById(`task-pill-${r.key}`);
      const pBox = document.getElementById(`task-progress-box-${r.key}`);
      if (b) b.innerHTML = getBadgeHtml('failed', r.step);
      if (p) p.innerHTML = getPillHtml('failed');
      if (pBox) pBox.classList.add('hidden');
    }
  });

  activeJobId = null;
  progressStateCard.classList.add('hidden');
  setCancelButtonVisible(false);
  mainActionBtn.disabled = false;
  mainActionBtn.classList.remove('opacity-50', 'cursor-not-allowed');
}

function startPolling(jobId) {
  if (pollInterval) clearInterval(pollInterval);
  if (taskElapsedTimer) {
    clearInterval(taskElapsedTimer);
    taskElapsedTimer = null;
  }
  taskStartTimestamps = {};
  taskDurations = {};
  highestJobProgress = 0;

  const intervalId = setInterval(async () => {
    // Ignore late responses from a job that is no longer the active one.
    if (jobId !== activeJobId) {
      clearInterval(intervalId);
      return;
    }
    try {
      const res = await fetch(`/api/status/${jobId}`);
      // Jobs live in server memory, so a restart loses them and they will never report again.
      if (res.status === 404) {
        try {
          localStorage.removeItem('luna_active_job_id');
          localStorage.removeItem('luna_active_ws');
          localStorage.removeItem('luna_active_action');
        } catch (e) {}
        clearInterval(pollInterval);
        pollInterval = null;
        if (taskElapsedTimer) {
          clearInterval(taskElapsedTimer);
          taskElapsedTimer = null;
        }
        activeJobId = null;
        progressStateCard.classList.add('hidden');
        mainActionBtn.disabled = false;
        mainActionBtn.classList.remove('opacity-50', 'cursor-not-allowed');
        showToast('This job was lost because the server restarted. Please start it again.', true);
        return;
      }
      if (!res.ok) return;
      const data = await res.json();

      // Re-check after the await: the active job may have changed while this response was in flight.
      if (jobId !== activeJobId) {
        clearInterval(intervalId);
        return;
      }

      if (data.status === 'cancelled') {
        try {
          localStorage.removeItem('luna_active_job_id');
          localStorage.removeItem('luna_active_ws');
          localStorage.removeItem('luna_active_action');
        } catch (e) {}
        clearInterval(pollInterval);
        pollInterval = null;
        if (taskElapsedTimer) {
          clearInterval(taskElapsedTimer);
          taskElapsedTimer = null;
        }
        activeJobId = null;
        progressStateCard.classList.add('hidden');
        mainActionBtn.disabled = false;
        mainActionBtn.classList.remove('opacity-50', 'cursor-not-allowed');
        return;
      }

      updateProgressUI(data.stage, data);

      if (data.status === 'completed') {
        try {
          localStorage.removeItem('luna_active_job_id');
          localStorage.removeItem('luna_active_ws');
          localStorage.removeItem('luna_active_action');
        } catch (e) {}
        clearInterval(pollInterval);
        pollInterval = null;
        if (taskElapsedTimer) {
          clearInterval(taskElapsedTimer);
          taskElapsedTimer = null;
        }
        activeJobId = null;
        setCancelButtonVisible(false);
        updateProgressUI('done', data);

        currentJobProjectId = data.project_id || null;
        currentJobWorkspaceName = data.workspace_name || null;
        const wsLabel = document.getElementById('completionWsLabel');
        if (wsLabel) wsLabel.innerText = data.workspace_name || 'Workspace';

        const compBanner = document.getElementById('progressCompletionBanner');
        if (compBanner) compBanner.classList.remove('hidden');

        renderOpusResults(data);
        updateVaultBadge();
        mainActionBtn.disabled = false;
        mainActionBtn.classList.remove('opacity-50', 'cursor-not-allowed');
      } else if (data.status === 'failed') {
        try {
          localStorage.removeItem('luna_active_job_id');
          localStorage.removeItem('luna_active_ws');
          localStorage.removeItem('luna_active_action');
        } catch (e) {}
        clearInterval(pollInterval);
        pollInterval = null;
        if (taskElapsedTimer) {
          clearInterval(taskElapsedTimer);
          taskElapsedTimer = null;
        }
        activeJobId = null;
        // Keep a way out: the job is gone, but the failed card must be dismissable.
        setCancelButtonVisible(true, 'Close');
        currentTaskRows.forEach(r => {
          if (r.status === 'running') {
            r.status = 'failed';
            const b = document.getElementById(`task-badge-${r.key}`);
            const p = document.getElementById(`task-pill-${r.key}`);
            const pBox = document.getElementById(`task-progress-box-${r.key}`);
            if (b) b.innerHTML = getBadgeHtml('failed', r.step);
            if (p) p.innerHTML = getPillHtml('failed');
            if (pBox) pBox.classList.add('hidden');
          }
        });
        mainActionBtn.disabled = false;
        mainActionBtn.classList.remove('opacity-50', 'cursor-not-allowed');
        let errMsg = data.error || 'An error occurred during processing. Check your connection or the link.';
        if (errMsg.includes('This video is unavailable') || errMsg.includes('This video is unavailable')) {
          errMsg = 'This YouTube video may be private, deleted, or restricted. Try another video.';
        }
        if (/getaddrinfo|name resolution|name or service|timed out|timeout|urlopen|unable to download|connection (was )?(reset|aborted|refused)|network is unreachable|errno 2\]/i.test(errMsg)) {
          errMsg = 'The download was interrupted. Check your internet connection and try again.';
        }
        if (data.retryable) {
          offerRetry(data.id, errMsg);
        } else {
          showNoticeModal('Processing failed', errMsg);
        }
      }
    } catch (e) {
      console.log(e);
    }
  }, 850);
  pollInterval = intervalId;
}

function updateProgressUI(stage, data) {
  const pData = data || {};
  const rawPct = (typeof pData.progress === 'number') ? pData.progress : 0;
  const isDownloadStage = (stage === 'queued' || stage === 'downloading');

  let downloadPct = rawPct;
  if (pData.download_eta && pData.download_eta !== '00:00' && pData.download_eta !== '0' && pData.download_eta !== '00:01') {
    if (downloadPct > 95.0) downloadPct = 95.0;
  }
  if (isDownloadStage) {
    highestJobProgress = Math.max(highestJobProgress, downloadPct);
  }
  const progressPct = isDownloadStage ? Math.min(100, Math.max(0, highestJobProgress)) : 0;

  if (currentActionType === 'type_yt_ai_clip') {
    if (stage === 'queued' || stage === 'downloading') {
      stageMainTitle.innerText = 'Downloading source video';
      stageSubTitle.innerText = 'Downloading the full-resolution video stream';
      setTaskStatuses(['running', 'pending', 'pending', 'pending', 'pending'], pData, progressPct);
    } else if (stage === 'checking_transcript') {
      stageMainTitle.innerText = 'Checking transcript';
      stageSubTitle.innerText = 'Checking for auto-captions or official subtitles';
      setTaskStatuses(['done', 'running', 'pending', 'pending', 'pending'], pData, 0);
    } else if (stage === 'transcript_found') {
      stageMainTitle.innerText = 'Official transcript found';
      stageSubTitle.innerText = 'Built-in transcript extracted';
      setTaskStatuses(['done', 'done', 'done', 'pending', 'pending'], pData, 0);
    } else if (stage === 'transcribing' || stage === 'transcribing_groq' || stage === 'transcribing_local' || stage === 'extracting_audio' || stage === 'uploading') {
      stageMainTitle.innerText = 'Audio transcription';
      stageSubTitle.innerText = 'Processing audio with AI speech-to-text';
      setTaskStatuses(['done', 'done', 'running', 'pending', 'pending'], pData, 0);
    } else if (stage === 'detecting_highlights' || stage === 'ranking_highlights') {
      stageMainTitle.innerText = 'Viral Potential & Hook Analysis';
      stageSubTitle.innerText = 'Finding the strongest moments';
      setTaskStatuses(['done', 'done', 'done', 'running', 'pending'], pData, 0);
    } else if (stage === 'clipping' || stage === 'rendering') {
      stageMainTitle.innerText = 'Render Vertical Clips';
      stageSubTitle.innerText = 'Encoding 9:16 clips';
      setTaskStatuses(['done', 'done', 'done', 'done', 'running'], pData, 0);
    } else if (stage === 'saving') {
      stageMainTitle.innerText = 'Saving to Media Vault';
      stageSubTitle.innerText = 'Adding clips to the Media Vault workspace';
      setTaskStatuses(['done', 'done', 'done', 'done', 'running'], pData, 0);
    } else if (stage === 'done') {
      stageMainTitle.innerText = 'Clip generation complete';
      stageSubTitle.innerText = 'Clips are ready to post';
      setTaskStatuses(['done', 'done', 'done', 'done', 'done'], pData, 100);
    }
  } else {
    // Direct Video, Audio, or Trimmer: strictly 2 tasks top-to-bottom
    const isAudio = currentActionType === 'type_yt_mp3' || currentActionType === 'type_tt_mp3';
    const isClip = currentActionType === 'type_yt_clip';

    if (stage === 'queued') {
      stageMainTitle.innerText = 'Preparing download';
      stageSubTitle.innerText = 'Connecting to the media source';
      setTaskStatuses(['running', 'pending'], pData, progressPct);
    } else if (stage === 'downloading') {
      stageMainTitle.innerText = isAudio
        ? 'Downloading audio'
        : (isClip ? 'Downloading source segments' : 'Downloading video');
      stageSubTitle.innerText = isAudio
        ? 'Downloading bitstream audio fidelitas tinggi'
        : (isClip ? 'Downloading video segments from the source' : 'Downloading the full-resolution video');
      setTaskStatuses(['running', 'pending'], pData, progressPct);
    } else if (stage === 'clipping') {
      stageMainTitle.innerText = 'Trimming video segments';
      stageSubTitle.innerText = 'Trimming timestamps with FFmpeg';
      setTaskStatuses(['running', 'pending'], pData, progressPct);
    } else if (stage === 'rendering') {
      stageMainTitle.innerText = 'Re-encoding video';
      stageSubTitle.innerText = 'Re-encoding to the requested ratio and frame rate before saving';
      const vaultRow = currentTaskRows[1];
      const vaultLabel = document.getElementById('task-label-vault');
      if (vaultRow && vaultLabel) vaultLabel.innerText = 'Re-encoding video';
      setTaskStatuses(['done', 'running'], pData, 100);
    } else if (stage === 'saving') {
      stageMainTitle.innerText = 'Saving to Media Vault';
      stageSubTitle.innerText = 'Finishing processing and organizing media';
      const vaultRow = currentTaskRows[1];
      const vaultLabel = document.getElementById('task-label-vault');
      if (vaultRow && vaultLabel) vaultLabel.innerText = vaultRow.label;
      setTaskStatuses(['done', 'running'], pData, progressPct);
    } else if (stage === 'done') {
      stageMainTitle.innerText = 'Download complete';
      stageSubTitle.innerText = 'Files are saved and ready to play or download';
      setTaskStatuses(['done', 'done'], pData, 100);
    }
  }
}

async function goToCurrentJobWorkspace() {
  try {
    const res = await fetch('/api/vault/projects');
    if (res.ok) {
      const data = await res.json();
      vaultProjects = data.projects || [];
      nextWorkspaceIndex = data.next_workspace_index || 1;
      vaultStats = data.stats || vaultStats;
      updateVaultStatsUI();
    }
  } catch (e) {
    console.warn('Failed refreshing vault projects:', e);
  }

  let targetProject = null;
  if (currentJobProjectId) {
    targetProject = vaultProjects.find(it => it.project_id === currentJobProjectId);
  }
  if (!targetProject && currentJobWorkspaceName) {
    targetProject = vaultProjects.find(it => (it.workspace_name || '').trim().toLowerCase() === currentJobWorkspaceName.trim().toLowerCase());
  }

  switchMainTab('vault');

  if (targetProject) {
    await openProjectPage(targetProject.project_id);
  } else {
    showToast('Saved to Media Vault');
  }
}

function renderOpusResults(data) {
  shortsGalleryGrid.innerHTML = '';
  const items = data.results || [];
  const isSingle = items.length === 1;

  if (items.length === 0) {
    batchZipDownloadBtn.classList.add('hidden');
    shortsGalleryGrid.classList.add('hidden');
    resultsCountNotice.innerText = 'No files were produced. Check the job log and try again.';
  } else if (items.length > 1) {
    batchZipDownloadBtn.href = `/api/download-zip/${data.id}`;
    batchZipDownloadBtn.classList.remove('hidden');
    shortsGalleryGrid.classList.remove('hidden');
    resultsCountNotice.innerText = `${items.length} media files are ready to play and download.`;
    shortsGalleryGrid.className = 'grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5 items-start';
  } else {
    batchZipDownloadBtn.classList.add('hidden');
    shortsGalleryGrid.classList.remove('hidden');
    resultsCountNotice.innerText = `1 media files are ready to play and download.`;
    shortsGalleryGrid.className = 'flex justify-center w-full max-w-4xl mx-auto';
  }

  const waveformHeights = [20, 45, 75, 30, 85, 55, 95, 70, 40, 90, 100, 65, 45, 80, 60, 35, 75, 50, 25, 15, 35, 65, 80, 45, 70, 90, 40, 20];

  items.forEach((item, idx) => {
    const card = document.createElement('div');
    card.id = `studio-card-${idx}`;
    const downloadUrl = item.download_url || `/api/download-file/${data.id}/${item.filename}`;
    const startSec = (typeof item.start_time === 'number') ? item.start_time : (item.start_time ? timeToSeconds(item.start_time) : NaN);
    const endSec = (typeof item.end_time === 'number') ? item.end_time : (item.end_time ? timeToSeconds(item.end_time) : NaN);
    const hasRange = isFinite(startSec) && isFinite(endSec) && endSec > startSec;
    const durationLabel = hasRange ? `${Math.round(endSec - startSec)}s` : (item.quality ? item.quality + 'p' : 'HD');

    if (item.type === 'audio') {
      const fileId = `studio-aud-${idx}`;
      const waveformBarsHtml = waveformHeights.map(h => `<span class="waveform-bar w-[3px] rounded-full bg-zinc-600/70" style="height: ${h}%;"></span>`).join('');

      if (isSingle) {
        card.className = 't-rec-card single-result-card flex flex-col justify-between w-full max-w-xl mx-auto shadow-2xl';
        card.innerHTML = `
          <div class="audio-card-showcase relative bg-[#121212] border-b border-white/[0.06] p-7 flex flex-col items-center justify-center overflow-hidden select-none">
            <div class="absolute inset-0 bg-radial from-white/[0.08] via-transparent to-transparent pointer-events-none"></div>

            <div class="absolute top-3.5 right-3.5 flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-white/[0.06] border border-white/10 text-[11px] font-mono text-zinc-300">
              <span class="w-2 h-2 rounded-full bg-white shadow-[0_0_8px_rgba(255,255,255,0.8)]"></span>
              <span>320 KBPS MP3</span>
            </div>

            <!-- Vinyl Disc Graphic (Enlarged) -->
            <div class="relative my-3 flex items-center justify-center">
              <div id="vinyl-disc-${fileId}" class="vinyl-disc w-28 h-28 rounded-full bg-[#0a0a0a] border border-zinc-700/60 shadow-[0_12px_32px_rgba(0,0,0,0.8)] relative flex items-center justify-center transition-transform">
                <div class="absolute inset-2 rounded-full border border-white/[0.06]"></div>
                <div class="absolute inset-4 rounded-full border border-white/[0.04]"></div>
                <div class="absolute inset-6 rounded-full border border-white/[0.05]"></div>
                <div class="w-9 h-9 rounded-full bg-zinc-800 border border-white/20 flex items-center justify-center shadow-inner">
                  <div class="w-2.5 h-2.5 rounded-full bg-[#0a0a0a] border border-white/40"></div>
                </div>
              </div>
            </div>

            <!-- Waveform Visualizer (Enlarged) -->
            <div id="waveform-bars-${fileId}" class="waveform-bars flex items-end justify-center gap-[3px] h-8 w-full max-w-[280px] mt-2 mb-2 px-2">
              ${waveformBarsHtml}
            </div>

            <!-- Custom Controls -->
            <div class="w-full mt-4 pt-4 border-t border-white/[0.06] space-y-2.5">
              <audio id="audio-el-${fileId}" src="${item.url}" preload="metadata" class="hidden"></audio>

              <div class="flex items-center gap-2.5 text-xs font-mono text-zinc-400">
                <span id="audio-time-${fileId}">0:00</span>
                <div 
                  class="relative flex-1 h-2 rounded-full bg-white/10 hover:bg-white/20 transition cursor-pointer overflow-hidden group/scrubber" 
                  onclick="seekCustomAudio(event, '${fileId}')"
                  title="Seek">
                  <div id="audio-progress-${fileId}" class="h-full bg-white rounded-full w-0 transition-[width] duration-75"></div>
                </div>
                <span id="audio-dur-${fileId}">--:--</span>
              </div>

              <div class="flex items-center justify-between pt-1">
                <div class="flex items-center gap-2.5">
                  <button 
                    type="button" 
                    id="audio-play-btn-${fileId}" 
                    onclick="toggleCustomAudioPlay('${fileId}')" 
                    class="w-8 h-8 rounded-full bg-white text-black hover:bg-zinc-200 active:scale-95 transition-all flex items-center justify-center shadow cursor-pointer"
                    title="Play / Pause">
                    <i data-lucide="play" class="w-4 h-4 ml-0.5"></i>
                  </button>
                  <span class="text-xs font-mono text-zinc-300" id="audio-status-${fileId}">Audio Track</span>
                </div>

                <button 
                  type="button" 
                  onclick="toggleCustomAudioMute('${fileId}')" 
                  id="audio-mute-btn-${fileId}"
                  class="p-1.5 rounded-lg text-zinc-400 hover:text-white hover:bg-white/[0.06] transition cursor-pointer" 
                  title="Mute / Unmute">
                  <i data-lucide="volume-2" class="w-4 h-4"></i>
                </button>
              </div>
            </div>
          </div>

          <div class="p-5 flex-1 flex flex-col justify-between">
            <div>
              <h4 class="text-base font-semibold text-white line-clamp-2 mb-1.5" title="${escapeHtml(item.title)}">
                ${escapeHtml(item.title)}
              </h4>
              <div class="flex items-center gap-2 text-xs text-zinc-400 font-mono mb-4">
                <span class="px-2 py-0.5 rounded bg-white/[0.04] border border-white/[0.06]">320 kbps MP3</span>
              </div>
            </div>

            <div class="pt-3 border-t border-white/[0.06]">
              <a href="${downloadUrl}" download="${escapeHtml(item.filename || 'audio.mp3')}" class="t-btn t-btn-primary w-full !h-10 text-[13px] font-semibold flex items-center justify-center gap-2" title="Download File">
                <i data-lucide="download" class="w-4 h-4"></i>
                <span>Download Audio MP3</span>
              </a>
            </div>
          </div>
        `;
      } else {
        card.className = 't-rec-card flex flex-col justify-between';
        card.innerHTML = `
          <div class="audio-card-showcase relative bg-[#121212] border-b border-white/[0.06] p-5 flex flex-col items-center justify-center overflow-hidden select-none">
            <div class="absolute inset-0 bg-radial from-white/[0.07] via-transparent to-transparent pointer-events-none"></div>

            <div class="absolute top-2.5 right-2.5 flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-white/[0.04] border border-white/10 text-[10px] font-mono text-zinc-400">
              <span class="w-1.5 h-1.5 rounded-full bg-white"></span>
              <span>320 KBPS MP3</span>
            </div>

            <!-- Vinyl Disc Graphic -->
            <div class="relative my-2 flex items-center justify-center">
              <div id="vinyl-disc-${fileId}" class="vinyl-disc w-20 h-20 rounded-full bg-[#0a0a0a] border border-zinc-700/60 shadow-[0_8px_25px_rgba(0,0,0,0.8)] relative flex items-center justify-center transition-transform">
                <div class="absolute inset-1.5 rounded-full border border-white/[0.06]"></div>
                <div class="absolute inset-3 rounded-full border border-white/[0.04]"></div>
                <div class="absolute inset-4.5 rounded-full border border-white/[0.05]"></div>
                <div class="w-7 h-7 rounded-full bg-zinc-800 border border-white/20 flex items-center justify-center shadow-inner">
                  <div class="w-2 h-2 rounded-full bg-[#0a0a0a] border border-white/40"></div>
                </div>
              </div>
            </div>

            <!-- Waveform Visualizer -->
            <div id="waveform-bars-${fileId}" class="waveform-bars flex items-end justify-center gap-[3px] h-6 w-full max-w-[200px] mt-1 mb-1 px-2">
              ${waveformBarsHtml.slice(0, 20).join('')}
            </div>

            <!-- Custom Controls -->
            <div class="w-full mt-3 pt-3 border-t border-white/[0.06] space-y-2">
              <audio id="audio-el-${fileId}" src="${item.url}" preload="metadata" class="hidden"></audio>

              <div class="flex items-center gap-2 text-[11px] font-mono text-zinc-400">
                <span id="audio-time-${fileId}">0:00</span>
                <div 
                  class="relative flex-1 h-1.5 rounded-full bg-white/10 hover:bg-white/20 transition cursor-pointer overflow-hidden group/scrubber" 
                  onclick="seekCustomAudio(event, '${fileId}')"
                  title="Seek">
                  <div id="audio-progress-${fileId}" class="h-full bg-white rounded-full w-0 transition-[width] duration-75"></div>
                </div>
                <span id="audio-dur-${fileId}">--:--</span>
              </div>

              <div class="flex items-center justify-between pt-0.5">
                <div class="flex items-center gap-2">
                  <button 
                    type="button" 
                    id="audio-play-btn-${fileId}" 
                    onclick="toggleCustomAudioPlay('${fileId}')" 
                    class="w-7 h-7 rounded-full bg-white text-black hover:bg-zinc-200 active:scale-95 transition-all flex items-center justify-center shadow cursor-pointer"
                    title="Play / Pause">
                    <i data-lucide="play" class="w-3.5 h-3.5 ml-0.5"></i>
                  </button>
                  <span class="text-[11px] font-mono text-zinc-400" id="audio-status-${fileId}">Audio Track</span>
                </div>

                <button 
                  type="button" 
                  onclick="toggleCustomAudioMute('${fileId}')" 
                  id="audio-mute-btn-${fileId}"
                  class="p-1 rounded-md text-zinc-400 hover:text-white hover:bg-white/[0.06] transition cursor-pointer" 
                  title="Mute / Unmute">
                  <i data-lucide="volume-2" class="w-3.5 h-3.5"></i>
                </button>
              </div>
            </div>
          </div>

          <div class="p-4 flex-1 flex flex-col justify-between">
            <div>
              <h4 class="text-sm font-medium text-white line-clamp-2 mb-1" title="${escapeHtml(item.title)}">
                ${escapeHtml(item.title)}
              </h4>
              <div class="flex items-center gap-2 text-[11px] text-zinc-400 font-mono mb-4">
                <span>320 kbps MP3</span>
              </div>
            </div>

            <div class="pt-2 border-t border-white/[0.06]">
              <a href="${downloadUrl}" download="${escapeHtml(item.filename || 'audio.mp3')}" class="t-btn t-btn-primary w-full text-[12px] flex items-center justify-center gap-1.5" title="Download File">
                <i data-lucide="download" class="w-3.5 h-3.5"></i>
                <span>Download Audio MP3</span>
              </a>
            </div>
          </div>
        `;
      }
      setTimeout(() => initAudioEvents(fileId), 20);
    } else {
      const fileId = `studio-vid-${idx}`;
      const isPortraitDefault = currentPlatform === 'tiktok' || currentPlatform === 'instagram' || currentActionType === 'type_yt_ai_clip' || currentActionType === 'type_yt_short';
      const itemMeta = ratioMetaFromValue(item.aspect_ratio) || ratioMetaFromFilename(item.filename) || {
        label: isPortraitDefault ? '9:16 Portrait' : '16:9 Landscape',
        kind: isPortraitDefault ? 'portrait' : 'landscape',
        icon: isPortraitDefault ? 'smartphone' : 'tv',
      };
      const itemIsWide = itemMeta.kind === 'landscape';

      const captionBox = item.caption ? `
        <div class="mt-2.5">
          <span class="text-[10px] font-mono text-zinc-400 block mb-1">Viral Hook & Caption:</span>
          <p class="text-xs text-zinc-300 leading-relaxed bg-[#121212] p-2.5 rounded-lg border border-white/5 select-all line-clamp-3">
            ${escapeHtml(item.caption)}
          </p>
        </div>
      ` : '';

      const copyBtn = item.caption ? `
        <button 
          type="button"
          onclick="copyText('${escapeQuotes(item.caption)}', this)" 
          class="t-btn t-btn-secondary ${isSingle ? '!h-10 px-4 text-xs' : 'px-3 py-2 text-[12px]'} flex items-center justify-center gap-1.5 cursor-pointer">
          <i data-lucide="copy" class="w-3.5 h-3.5 text-white"></i>
          <span>Copy</span>
        </button>
      ` : '';

      if (isSingle) {
        card.className = `t-rec-card single-result-card flex flex-col justify-between w-full ${itemIsWide ? 'max-w-3xl' : 'max-w-md'} mx-auto shadow-2xl`;
        card.innerHTML = `
          <div class="video-preview-wrapper relative bg-[#09090b] w-full overflow-hidden border-b border-white/[0.06] flex items-center justify-center ${ratioAspectClass(itemMeta)} ${itemIsWide ? 'max-h-[520px]' : 'max-h-[580px]'}" style="aspect-ratio: ${ratioAspectStyle(itemMeta)}" data-file-id="${fileId}">
            <div class="ambient-glow absolute inset-0 opacity-15 pointer-events-none filter blur-2xl scale-125 bg-gradient-to-t from-white/10 via-white/5 to-transparent"></div>

            <div class="ratio-pill absolute top-3 left-3 z-20 flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-black/60 backdrop-blur-md border border-white/10 text-[11px] font-mono text-zinc-300 pointer-events-none">
              <i data-lucide="${itemMeta.icon}" class="w-3.5 h-3.5 ${itemIsWide ? 'text-zinc-400' : 'text-white'}"></i>
              <span class="ratio-text">${itemMeta.label}</span>
            </div>

            <media-theme-sutro style="width:100%; height:100%;" data-player-size="large">
              <video 
                slot="media"
                preload="metadata" 
                playsinline 
                class="w-full h-full object-contain relative z-10" 
                src="${item.url}" 
                onloadedmetadata="handleVaultVideoMetadata(this, '${fileId}')">
              </video>
            </media-theme-sutro>
          </div>

          <div class="p-5 flex-1 flex flex-col justify-between">
            <div>
              <div class="flex items-center justify-between mb-2">
                <span class="text-xs font-mono font-medium text-white">${item.start_time ? `Clip #${idx + 1}` : 'Video'}</span>
                <span class="text-xs font-mono text-zinc-400 px-2 py-0.5 rounded bg-white/[0.04] border border-white/[0.06]">${durationLabel}</span>
              </div>
              <h4 class="text-base sm:text-lg font-semibold text-white line-clamp-2 mb-1.5" title="${escapeHtml(item.title)}">
                ${escapeHtml(item.title)}
              </h4>
              ${captionBox}
            </div>

            <div class="flex items-center gap-2.5 pt-3 border-t border-white/[0.06] mt-4">
              ${copyBtn}
              <a href="${downloadUrl}" download="${escapeHtml(item.filename || 'video.mp4')}" class="t-btn t-btn-primary flex-1 !h-10 text-[13px] font-semibold flex items-center justify-center gap-2" title="Download File">
                <i data-lucide="download" class="w-4 h-4"></i>
                <span>Download MP4</span>
              </a>
            </div>
          </div>
        `;
      } else {
        card.className = 't-rec-card flex flex-col justify-between';
        card.innerHTML = `
          <div class="video-preview-wrapper relative bg-[#09090b] w-full overflow-hidden border-b border-white/[0.06] flex items-center justify-center ${ratioAspectClass(itemMeta)} ${itemIsWide ? 'max-h-[460px]' : ''}" style="aspect-ratio: ${ratioAspectStyle(itemMeta)}" data-file-id="${fileId}">
            <div class="ambient-glow absolute inset-0 opacity-15 pointer-events-none filter blur-2xl scale-125 bg-gradient-to-t from-white/10 via-white/5 to-transparent"></div>

            <div class="ratio-pill absolute top-2.5 left-2.5 z-20 flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-black/60 backdrop-blur-md border border-white/10 text-[10px] font-mono text-zinc-300 pointer-events-none">
              <i data-lucide="${itemMeta.icon}" class="w-3 h-3 ${itemIsWide ? 'text-zinc-400' : 'text-white'}"></i>
              <span class="ratio-text">${itemMeta.label}</span>
            </div>

            <media-theme-sutro style="width:100%; height:100%;" data-player-size="mini">
              <video 
                slot="media"
                preload="metadata" 
                playsinline 
                class="w-full h-full object-contain relative z-10" 
                src="${item.url}" 
                onloadedmetadata="handleVaultVideoMetadata(this, '${fileId}')">
              </video>
            </media-theme-sutro>
          </div>

          <div class="p-4 flex-1 flex flex-col justify-between">
            <div>
              <div class="flex items-center justify-between mb-1.5">
                <span class="text-[11px] font-mono font-medium text-white">${item.start_time ? `Clip #${idx + 1}` : 'Video'}</span>
                <span class="text-[11px] font-mono text-zinc-500">${durationLabel}</span>
              </div>
              <h4 class="text-sm font-medium text-white line-clamp-2 mb-1" title="${escapeHtml(item.title)}">
                ${escapeHtml(item.title)}
              </h4>
              ${captionBox}
            </div>

            <div class="flex items-center gap-2 pt-2 border-t border-white/[0.06] mt-3">
              ${copyBtn}
              <a href="${downloadUrl}" download="${escapeHtml(item.filename || 'video.mp4')}" class="t-btn t-btn-primary flex-1 text-[12px] flex items-center justify-center gap-1.5" title="Download File">
                <i data-lucide="download" class="w-3.5 h-3.5"></i>
                <span>Download MP4</span>
              </a>
            </div>
          </div>
        `;
      }
    }

    shortsGalleryGrid.appendChild(card);
  });

  resultsShowcase.classList.remove('hidden');
  lucide.createIcons();
  setTimeout(compactSutroPlayers, 30);
  setTimeout(compactSutroPlayers, 150);
  setTimeout(compactSutroPlayers, 500);
}



function copyText(text, btn) {
  navigator.clipboard.writeText(text).then(() => {
    const span = btn.querySelector('span');
    const original = span.innerText;
    span.innerText = 'Copied! ✓';
    btn.classList.add('bg-white', 'text-white');
    setTimeout(() => {
      span.innerText = original;
      btn.classList.remove('bg-white', 'text-white');
    }, 2000);
  });
}

function escapeHtml(str) {
  return (str || '').replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}

function escapeQuotes(str) {
  return (str || '')
    .replace(/&/g, '&amp;')
    .replace(/\\/g, '\\\\')
    .replace(/'/g, "\\'")
    .replace(/"/g, '&quot;')
    .replace(/[\r\n]+/g, ' ');
}

// Media vault methods

function updateTabsPill(immediate = false) {
  const pill = document.getElementById('mainTabsPill');
  const btnStudio = document.getElementById('tabBtnStudio');
  const btnVault = document.getElementById('tabBtnVault');
  if (!pill) return;

  if (currentMainTab === 'settings' || currentMainTab === 'guide') {
    pill.style.opacity = '0';
    pill.style.width = '0px';
    if (btnStudio) {
      btnStudio.classList.remove('active');
      btnStudio.setAttribute('aria-selected', 'false');
    }
    if (btnVault) {
      btnVault.classList.remove('active');
      btnVault.setAttribute('aria-selected', 'false');
    }
    return;
  }

  pill.style.opacity = '1';
  const activeTab = currentMainTab === 'vault' ? btnVault : btnStudio;
  if (!activeTab) return;

  if (btnStudio) {
    btnStudio.classList.toggle('active', currentMainTab === 'studio');
    btnStudio.setAttribute('aria-selected', currentMainTab === 'studio' ? 'true' : 'false');
  }
  if (btnVault) {
    btnVault.classList.toggle('active', currentMainTab === 'vault');
    btnVault.setAttribute('aria-selected', currentMainTab === 'vault' ? 'true' : 'false');
  }

  if (immediate) {
    pill.style.transition = 'none';
    pill.style.transform = `translateX(${activeTab.offsetLeft}px)`;
    pill.style.width = `${activeTab.offsetWidth}px`;
    void pill.offsetHeight;
    pill.style.transition = '';
  } else {
    pill.style.transform = `translateX(${activeTab.offsetLeft}px)`;
    pill.style.width = `${activeTab.offsetWidth}px`;
  }
}

function switchMainTab(tab) {
  try {
    currentMainTab = tab;
    document.body.classList.remove('tab-studio', 'tab-vault', 'tab-settings');
    document.body.classList.add('tab-' + tab);
    if (tab !== 'vault') {
      document.body.classList.remove('in-workspace');
      if (currentActiveProjectId) {
        closeProjectPage();
      }
    } else if (!currentActiveProjectId) {
      document.body.classList.remove('in-workspace');
    }

    const sectionStudio = document.getElementById('section-studio');
    const sectionVault = document.getElementById('section-vault');
    const sectionSettings = document.getElementById('section-settings');
    const btnNavSettings = document.getElementById('btnNavSettings');
    const pill = document.getElementById('mainTabsPill');

    // Running WebGL Background active ONLY in Studio
    const bgContainer = document.getElementById('studioBackgroundContainer');
    const curtainsCanvas = document.getElementById('curtains-canvas');
    if (tab === 'studio') {
      if (window.location.hash) {
        history.replaceState(null, '', window.location.pathname);
      }
      if (bgContainer) {
        bgContainer.classList.remove('is-hidden');
        bgContainer.style.opacity = '1';
        bgContainer.style.visibility = 'visible';
        bgContainer.style.pointerEvents = 'none';
        bgContainer.style.removeProperty('display');
      }
      if (curtainsCanvas) {
        curtainsCanvas.style.opacity = '1';
        curtainsCanvas.style.visibility = 'visible';
        curtainsCanvas.style.pointerEvents = 'none';
        curtainsCanvas.style.removeProperty('display');
      }
      if (typeof window.resumeUnicornStudio === 'function') {
        window.resumeUnicornStudio();
      }
    } else {
      if (bgContainer) {
        bgContainer.classList.add('is-hidden');
        bgContainer.style.opacity = '0';
        bgContainer.style.visibility = 'hidden';
        bgContainer.style.pointerEvents = 'none';
      }
      if (curtainsCanvas) {
        curtainsCanvas.style.opacity = '0';
        curtainsCanvas.style.visibility = 'hidden';
        curtainsCanvas.style.pointerEvents = 'none';
      }
      if (typeof window.pauseUnicornStudio === 'function') {
        window.pauseUnicornStudio();
      }
    }

    const sectionGuide = document.getElementById('section-guide');
    const btnNavGuide = document.getElementById('btnNavGuide');

    if (tab === 'settings') {
      if (sectionStudio) sectionStudio.classList.add('hidden');
      if (sectionVault) sectionVault.classList.add('hidden');
      if (sectionGuide) sectionGuide.classList.add('hidden');
      if (sectionSettings) sectionSettings.classList.remove('hidden');

      if (btnNavSettings) {
        btnNavSettings.classList.add('text-white', 'active');
        btnNavSettings.classList.remove('text-zinc-400');
      }
      if (btnNavGuide) {
        btnNavGuide.classList.remove('text-white', 'active');
      }

      if (pill) {
        pill.style.opacity = '0';
        pill.style.width = '0px';
      }

      document.title = 'Luna: Settings';
      try {
        if (typeof loadSettingsData === 'function') loadSettingsData();
      } catch (e) {
        console.error('[Settings] Load error:', e);
      }
    } else if (tab === 'guide') {
      if (sectionStudio) sectionStudio.classList.add('hidden');
      if (sectionVault) sectionVault.classList.add('hidden');
      if (sectionSettings) sectionSettings.classList.add('hidden');
      if (sectionGuide) sectionGuide.classList.remove('hidden');

      if (btnNavGuide) {
        btnNavGuide.classList.add('text-white', 'active');
      }
      if (btnNavSettings) {
        btnNavSettings.classList.remove('text-white', 'active');
        btnNavSettings.classList.add('text-zinc-400');
      }

      if (pill) {
        pill.style.opacity = '0';
        pill.style.width = '0px';
      }

      document.title = 'Luna: User Guide';
      if (typeof initGuidePill === 'function') {
        requestAnimationFrame(() => initGuidePill());
      }
    } else {
      if (sectionSettings) sectionSettings.classList.add('hidden');
      if (sectionGuide) sectionGuide.classList.add('hidden');

      if (btnNavSettings) {
        btnNavSettings.classList.remove('text-white', 'active');
        btnNavSettings.classList.add('text-zinc-400');
      }
      if (btnNavGuide) {
        btnNavGuide.classList.remove('text-white', 'active');
      }

      if (tab === 'studio') {
        if (sectionStudio) sectionStudio.classList.remove('hidden');
        if (sectionVault) sectionVault.classList.add('hidden');
        document.title = 'Luna: AI Video Clipper & Downloader';
      } else if (tab === 'vault') {
        if (sectionStudio) sectionStudio.classList.add('hidden');
        if (sectionVault) sectionVault.classList.remove('hidden');
        document.title = 'Luna: Media Vault';

        if (!currentActiveProjectId) {
          const listView = document.getElementById('vaultProjectsListView');
          const detailView = document.getElementById('vaultProjectDetailView');
          if (listView) listView.classList.remove('hidden');
          if (detailView) detailView.classList.add('hidden');
        }

        try {
          if (typeof loadVaultItems === 'function') loadVaultItems();
        } catch (e) {
          console.error('[Vault] Load error:', e);
        }
      }
    }

    updateTabsPill(false);

    if (window.lucide && typeof window.lucide.createIcons === 'function') {
      window.lucide.createIcons();
    }
  } catch (err) {
    console.error('[switchMainTab error]', err);
  }
}

// Settings page methods
function triggerInputError(wrapId, msgId, message) {
  const wrap = document.getElementById(wrapId);
  if (!wrap) return;
  const box = wrap.querySelector('.t-input');
  const msg = document.getElementById(msgId);

  if (message && msg) msg.innerText = message;

  if (box) {
    box.classList.remove('is-shaking');
    void box.offsetWidth;
    box.classList.add('is-error', 'is-shaking');
  }
  wrap.classList.add('is-error');

  setTimeout(() => {
    if (box) box.classList.remove('is-shaking');
  }, 280);

  if (wrap._revertTimer) clearTimeout(wrap._revertTimer);
  wrap._revertTimer = setTimeout(() => {
    wrap.classList.remove('is-error');
    if (box) box.classList.remove('is-error');
  }, 3000);
}

function showToast(message, isError = false) {
  const toast = document.getElementById('toastNotification');
  const msgEl = document.getElementById('toastMessage');
  const icon = document.getElementById('toastIcon');
  if (!toast || !msgEl) return;
  msgEl.innerText = message;

  if (isError) {
    if (icon) {
      icon.setAttribute('data-lucide', 'alert-circle');
      icon.className = 'w-3.5 h-3.5 text-red-400 shrink-0';
    }
  } else {
    if (icon) {
      icon.setAttribute('data-lucide', 'check');
      icon.className = 'w-3.5 h-3.5 text-emerald-400 shrink-0';
    }
  }
  lucide.createIcons();

  toast.classList.remove('translate-y-12', 'opacity-0', 'pointer-events-none');
  if (toast._hideTimer) clearTimeout(toast._hideTimer);
  toast._hideTimer = setTimeout(() => {
    toast.classList.add('translate-y-12', 'opacity-0', 'pointer-events-none');
  }, 2400);
}

function toggleSecret(inputId, iconId) {
  const el = document.getElementById(inputId);
  const icon = document.getElementById(iconId);
  if (!el || !icon) return;

  if (el.type === 'password') {
    el.type = 'text';
    icon.setAttribute('data-lucide', 'eye-off');
  } else {
    el.type = 'password';
    icon.setAttribute('data-lucide', 'eye');
  }
  lucide.createIcons();
}

let currentStorageDir = '';
const providerKeyUi = {
  openai: { configured: false, editing: true, validated: false, hint: '' },
  gemini: { configured: false, editing: true, validated: false, hint: '' },
  groq: { configured: false, editing: true, validated: false, hint: '' }
};
const providerKeyFields = { openai: 'inputOpenai', gemini: 'inputGemini', groq: 'inputGroq' };
const providerKeyPlaceholders = { openai: 'Enter your API key...', gemini: 'Enter your Gemini API key...', groq: 'Enter your Groq API key...' };

function updateProviderKeyUI(provider) {
  const state = providerKeyUi[provider];
  const input = document.getElementById(providerKeyFields[provider]);
  if (!state || !input) return;
  const locked = state.configured && !state.editing;
  input.disabled = locked;
  input.placeholder = locked ? `Key saved ····${state.hint}` : providerKeyPlaceholders[provider];
  input.parentElement?.querySelector('button[title="Show / Hide"]')?.classList.toggle('hidden', locked);
  document.getElementById(`change${provider[0].toUpperCase()}${provider.slice(1)}Key`)?.classList.toggle('hidden', !state.configured || state.editing);
  const hasSecondaryAction = state.configured || state.validated;
  const showActionDot = provider === 'openai'
    ? hasSecondaryAction
    : ((state.configured && !state.editing) || state.validated);
  document.getElementById(`${provider}KeyActionDot`)?.classList.toggle('hidden', !showActionDot);
  const saveButton = document.getElementById(`save${provider[0].toUpperCase()}${provider.slice(1)}Key`);
  if (saveButton) {
    saveButton.classList.toggle('hidden', !state.editing || !state.validated);
    saveButton.disabled = !state.validated;
    saveButton.classList.toggle('text-emerald-400/50', !state.validated);
    saveButton.classList.toggle('text-emerald-400', state.validated);
  }
  document.getElementById(`cancel${provider[0].toUpperCase()}${provider.slice(1)}Key`)?.classList.toggle('hidden', !state.editing || !state.configured);
  const stateLabel = document.getElementById(`${provider}KeyState`);
  if (stateLabel) stateLabel.textContent = locked ? 'API key is saved. Use Test Connection to check it, or Change Key to replace it.' : (state.configured ? 'Enter a replacement key. The current key stays active until you save.' : 'No API key saved yet. Test the key, then save it.');
}

function beginKeyChange(provider) {
  const state = providerKeyUi[provider];
  if (!state) return;
  state.editing = true;
  state.validated = false;
  const input = document.getElementById(providerKeyFields[provider]);
  if (input) input.value = '';
  const statusId = { openai: 'statusOpenai', gemini: 'statusGemini', groq: 'statusGroq' }[provider];
  const status = document.getElementById(statusId);
  if (status) status.textContent = '';
  updateProviderKeyUI(provider);
  input?.focus();
}

function cancelKeyChange(provider) {
  const state = providerKeyUi[provider];
  if (!state || !state.configured) return;
  state.editing = false;
  state.validated = false;
  const input = document.getElementById(providerKeyFields[provider]);
  if (input) input.value = '';
  updateProviderKeyUI(provider);
  const status = document.getElementById(`${provider === 'openai' ? 'statusOpenai' : provider === 'gemini' ? 'statusGemini' : 'statusGroq'}`);
  if (status) status.textContent = '';
}

function providerKeyInputChanged(provider) {
  const state = providerKeyUi[provider];
  if (!state?.editing) return;
  state.validated = false;
  const statusId = { openai: 'statusOpenai', gemini: 'statusGemini', groq: 'statusGroq' }[provider];
  const status = document.getElementById(statusId);
  if (status) status.textContent = '';
  updateProviderKeyUI(provider);
}

async function saveProviderKey(provider) {
  const state = providerKeyUi[provider];
  const input = document.getElementById(providerKeyFields[provider]);
  if (!state?.editing || !state.validated || !input?.value.trim()) return;
  const field = { openai: 'openai_api_key', gemini: 'gemini_api_key', groq: 'groq_api_key' }[provider];
  const payload = { [field]: input.value.trim() };
  if (provider === 'openai') {
    payload.openai_base_url = document.getElementById('inputOpenaiBase')?.value.trim();
    payload.openai_model = document.getElementById('inputOpenaiModel')?.value.trim();
  }
  try {
    const res = await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Could not save API key');
    state.configured = true;
    state.editing = false;
    state.validated = false;
    showToast(`${provider.toUpperCase()} API key saved`);
    await loadSettingsData();
  } catch (err) {
    showToast(err.message || 'Could not save API key', true);
  }
}

// ---- Logo dropdowns (clip provider, transcription provider, model) ----
// Every dropdown keeps its real value in a hidden input, so the settings save path
// is unchanged. The menu is a fixed popover so a scrolling card cannot clip it.
const openMenus = new Map(); // menuId -> triggerId

function positionMenu(trigger, menu) {
  const rect = trigger.getBoundingClientRect();
  const menuHeight = Math.min(280, menu.scrollHeight || 180);
  const menuWidth = Math.max(rect.width, 200);
  const roomBelow = window.innerHeight - rect.bottom;
  menu.style.width = `${menuWidth}px`;
  menu.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - menuWidth - 8))}px`;
  menu.style.top = roomBelow < menuHeight + 16
    ? `${Math.max(8, rect.top - menuHeight - 6)}px`
    : `${rect.bottom + 6}px`;
}

function closeMenu(menuId) {
  const trigger = document.getElementById(openMenus.get(menuId) || '');
  const menu = document.getElementById(menuId);
  if (menu) menu.classList.add('hidden');
  if (trigger) trigger.setAttribute('aria-expanded', 'false');
  openMenus.delete(menuId);
}

function closeAllMenus() {
  Array.from(openMenus.keys()).forEach(closeMenu);
}

function toggleMenu(triggerId, menuId, force) {
  const trigger = document.getElementById(triggerId);
  const menu = document.getElementById(menuId);
  if (!trigger || !menu) return;
  const open = typeof force === 'boolean' ? force : !openMenus.has(menuId);
  if (!open) {
    closeMenu(menuId);
    return;
  }
  closeAllMenus();
  menu.classList.remove('hidden');
  positionMenu(trigger, menu);
  trigger.setAttribute('aria-expanded', 'true');
  openMenus.set(menuId, triggerId);
  attachSettingsGliding(menu);
  alignSettingsIndicator(menuId);
}

// Smooth hover highlight, same motion as the Studio dropdowns (220ms glide).
function ensureMenuIndicator(menu) {
  let indicator = menu.querySelector('.gliding-menu-indicator');
  if (!indicator) {
    indicator = document.createElement('span');
    indicator.className = 'gliding-menu-indicator';
    menu.insertBefore(indicator, menu.firstChild);
  }
  return indicator;
}

function moveIndicatorTo(menu, item) {
  const indicator = ensureMenuIndicator(menu);
  if (!item) {
    indicator.style.opacity = '0';
    return;
  }
  indicator.style.top = `${item.offsetTop}px`;
  indicator.style.height = `${item.offsetHeight}px`;
  indicator.style.opacity = '1';
}

function attachSettingsGliding(menu) {
  if (!menu) return;
  ensureMenuIndicator(menu);
  menu.querySelectorAll('.settings-menu-item').forEach((item) => {
    item.onmouseenter = (event) => {
      event.stopPropagation();
      moveIndicatorTo(menu, item);
    };
  });
  menu.onmouseleave = () => {
    moveIndicatorTo(menu, menu.querySelector('[aria-selected="true"]'));
  };
}

// Snap the indicator onto the selected row when the menu opens (no glide from 0).
function alignSettingsIndicator(menuId) {
  const menu = document.getElementById(menuId);
  if (!menu) return;
  const indicator = ensureMenuIndicator(menu);
  const active = menu.querySelector('[aria-selected="true"]');
  if (!active) {
    indicator.style.opacity = '0';
    return;
  }
  indicator.style.transition = 'none';
  indicator.style.top = `${active.offsetTop}px`;
  indicator.style.height = `${active.offsetHeight}px`;
  indicator.style.opacity = '1';
  void indicator.offsetHeight;
  indicator.style.transition = '';
}

// Paints the trigger label and marks the active row from the hidden input.
function syncLogoSelect(config) {
  const input = document.getElementById(config.hiddenId);
  const menu = document.getElementById(config.menuId);
  if (!input || !menu) return;
  const value = input.value || '';
  const rows = Array.from(menu.querySelectorAll('[data-value]'));
  let active = rows.find((row) => (row.getAttribute('data-value') || '') === value);
  if (!active && rows.length) active = rows[0];
  const labelBox = document.getElementById(config.labelId);
  if (labelBox) labelBox.textContent = active ? (active.getAttribute('data-label') || '') : '';
  rows.forEach((row) => {
    const isActive = row === active;
    row.setAttribute('aria-selected', isActive ? 'true' : 'false');
    const check = row.querySelector('.select-check');
    if (check) check.classList.toggle('hidden', !isActive);
  });
  alignSettingsIndicator(config.menuId);
}

function syncLlmProviderUI() {
  syncLogoSelect({
    hiddenId: 'selectLlmProvider', menuId: 'llmProviderMenu',
    labelId: 'llmProviderTriggerLabel',
  });
}

function syncTranscribeUI() {
  syncLogoSelect({
    hiddenId: 'selectTranscribeProvider', menuId: 'transcribeMenu',
    labelId: 'transcribeTriggerLabel',
  });
}

function syncModelMenu() {
  syncLogoSelect({
    hiddenId: 'selectOpenaiModel', menuId: 'openaiModelMenu',
    labelId: 'openaiModelTriggerLabel',
  });
}

function setLlmProvider(value) {
  const input = document.getElementById('selectLlmProvider');
  if (input) input.value = value || '';
  syncLlmProviderUI();
  closeMenu('llmProviderMenu');
  if ((value || '') === 'openai' && typeof loadOpenaiModels === 'function') loadOpenaiModels();
}

function selectTranscribe(value) {
  const input = document.getElementById('selectTranscribeProvider');
  if (input) input.value = value || '';
  syncTranscribeUI();
  closeMenu('transcribeMenu');
}

function toggleLlmProviderMenu(force) { toggleMenu('llmProviderTrigger', 'llmProviderMenu', force); }
function closeLlmProviderMenu() { closeMenu('llmProviderMenu'); }

const CUSTOM_MODEL = '__custom__';
const CHECK_ICON_SVG = '<svg class="select-check ml-auto w-3.5 h-3.5 text-emerald-400 hidden" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>';

// Model IDs come from a third party, so the label is set with textContent, not HTML.
function buildSelectRow(value, label, onSelect) {
  const row = document.createElement('button');
  row.type = 'button';
  row.setAttribute('role', 'option');
  row.setAttribute('data-value', value);
  row.setAttribute('data-label', label);
  row.className = 'settings-menu-item relative z-[2] w-full flex items-center rounded-lg px-2.5 py-2 text-xs text-zinc-200 transition cursor-pointer';

  const text = document.createElement('span');
  text.className = 'truncate';
  text.textContent = label;

  row.append(text);
  row.insertAdjacentHTML('beforeend', CHECK_ICON_SVG);
  row.addEventListener('click', onSelect);
  return row;
}

function renderOpenaiModelItems(names) {
  const items = document.getElementById('openaiModelItems');
  if (!items) return;
  items.replaceChildren();
  names.forEach((name) => {
    items.appendChild(buildSelectRow(name, name, () => selectOpenaiModel(name)));
  });
  items.appendChild(buildSelectRow(CUSTOM_MODEL, 'Custom...', () => selectOpenaiModel(CUSTOM_MODEL)));
  attachSettingsGliding(document.getElementById('openaiModelMenu'));
  syncModelMenu();
}

function selectOpenaiModel(value) {
  const hidden = document.getElementById('selectOpenaiModel');
  if (hidden) hidden.value = value;
  const isCustom = value === CUSTOM_MODEL;
  const wrap = document.getElementById('wrapOpenaiModelCustom');
  if (wrap) wrap.classList.toggle('hidden', !isCustom);
  const customInput = document.getElementById('inputOpenaiModel');
  if (customInput) {
    if (isCustom) customInput.focus();
    else customInput.value = value;
  }
  syncModelMenu();
  closeMenu('openaiModelMenu');
}

document.addEventListener('click', (event) => {
  if (!(event.target instanceof Node)) return;
  Array.from(openMenus.keys()).forEach((menuId) => {
    const menu = document.getElementById(menuId);
    const trigger = document.getElementById(openMenus.get(menuId) || '');
    if ((menu && menu.contains(event.target)) || (trigger && trigger.contains(event.target))) return;
    closeMenu(menuId);
  });
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') closeAllMenus();
});
window.addEventListener('scroll', () => {
  if (openMenus.size) closeAllMenus();
}, { passive: true });
window.addEventListener('resize', () => {
  if (openMenus.size) closeAllMenus();
});

syncLlmProviderUI();
syncTranscribeUI();

// While "Custom..." is active, the trigger should mirror what is typed.
const customModelInput = document.getElementById('inputOpenaiModel');
if (customModelInput) {
  customModelInput.addEventListener('input', () => {
    const hidden = document.getElementById('selectOpenaiModel');
    if (hidden && hidden.value === CUSTOM_MODEL) {
      const label = document.getElementById('openaiModelTriggerLabel');
      if (label) label.textContent = customModelInput.value.trim() || 'Custom...';
    }
  });
}

async function loadSettingsData() {
  try {
    const res = await fetch('/api/settings');
    if (!res.ok) throw new Error('Could not load settings');
    const data = await res.json();

    const openaiFields = {
      selectLlmProvider: data.llm_provider,
      selectTranscribeProvider: data.transcribe_provider,
      inputOpenaiBase: data.openai_base_url,
      inputOpenaiModel: data.openai_model
    };
    for (const [id, value] of Object.entries(openaiFields)) {
      const el = document.getElementById(id);
      if (el && value !== undefined) el.value = value;
    }
    // The dropdowns render from their hidden input values.
    if (typeof syncLlmProviderUI === 'function') syncLlmProviderUI();
    if (typeof syncTranscribeUI === 'function') syncTranscribeUI();
    // Secrets come back masked, never as the key itself. Show the hint as a
    // placeholder and leave the field empty, so saving cannot overwrite the key.
    const inputOpenai = document.getElementById('inputOpenai');
    providerKeyUi.openai.configured = Boolean(data.has_openai_api_key);
    providerKeyUi.openai.hint = String(data.openai_api_key || '').slice(-4);
    providerKeyUi.openai.editing = !providerKeyUi.openai.configured;
    providerKeyUi.openai.validated = false;
    if (inputOpenai) inputOpenai.value = '';
    updateProviderKeyUI('openai');
    loadOpenaiModels();

    const inputGemini = document.getElementById('inputGemini');
    const labelGeminiModel = document.getElementById('labelGeminiModel');
    const inputGroq = document.getElementById('inputGroq');
    const labelGroqModel = document.getElementById('labelGroqModel');
    const inputStorage = document.getElementById('inputStorage');
    providerKeyUi.gemini.configured = Boolean(data.has_gemini_api_key);
    providerKeyUi.gemini.hint = String(data.gemini_api_key || '').slice(-4);
    providerKeyUi.gemini.editing = !providerKeyUi.gemini.configured;
    providerKeyUi.gemini.validated = false;
    if (inputGemini) inputGemini.value = '';
    updateProviderKeyUI('gemini');
    if (labelGeminiModel && data.gemini_model) labelGeminiModel.innerText = data.gemini_model;
    providerKeyUi.groq.configured = Boolean(data.has_groq_api_key);
    providerKeyUi.groq.hint = String(data.groq_api_key || '').slice(-4);
    providerKeyUi.groq.editing = !providerKeyUi.groq.configured;
    providerKeyUi.groq.validated = false;
    if (inputGroq) inputGroq.value = '';
    updateProviderKeyUI('groq');
    if (labelGroqModel && data.groq_model) labelGroqModel.innerText = data.groq_model;
    if (inputStorage && data.storage_dir) {
      inputStorage.value = data.storage_dir;
      currentStorageDir = data.storage_dir;
    }
    if (typeof updateVaultStatsUI === 'function') updateVaultStatsUI();

    // System status
    if (data.status) {
      const s = data.status;

      // FFmpeg
      const chkFfmpeg = document.getElementById('chkFfmpeg');
      const statusFfmpeg = document.getElementById('statusFfmpeg');
      if (chkFfmpeg) {
        chkFfmpeg.setAttribute('data-lucide', s.ffmpeg ? 'check' : 'x');
        chkFfmpeg.className = s.ffmpeg ? 'w-4 h-4 text-emerald-400' : 'w-4 h-4 text-red-400';
      }
      if (statusFfmpeg) statusFfmpeg.innerText = s.ffmpeg ? 'Available' : 'Not found';

      // yt-dlp
      const chkYtdlp = document.getElementById('chkYtdlp');
      const statusYtdlp = document.getElementById('statusYtdlp');
      if (chkYtdlp) {
        chkYtdlp.setAttribute('data-lucide', 'check');
        chkYtdlp.className = 'w-4 h-4 text-emerald-400';
      }
      if (statusYtdlp) statusYtdlp.innerText = s.ytdlp || 'Available';

      // OpenCV
      const chkOpencv = document.getElementById('chkOpencv');
      const statusOpencv = document.getElementById('statusOpencv');
      if (chkOpencv) {
        chkOpencv.setAttribute('data-lucide', s.opencv ? 'check' : 'alert-circle');
        chkOpencv.className = s.opencv ? 'w-4 h-4 text-emerald-400' : 'w-4 h-4 text-amber-400';
      }
      if (statusOpencv) statusOpencv.innerText = s.opencv ? 'Active' : 'Inactive';

      // Storage
      const chkStorage = document.getElementById('chkStorage');
      const statusStorageAccess = document.getElementById('statusStorageAccess');
      if (chkStorage) {
        chkStorage.setAttribute('data-lucide', s.storage ? 'check' : 'x');
        chkStorage.className = s.storage ? 'w-4 h-4 text-emerald-400' : 'w-4 h-4 text-red-400';
      }
      if (statusStorageAccess) statusStorageAccess.innerText = s.storage ? 'Writable' : 'Access denied';

      // Cookies
      const chkCookies = document.getElementById('chkCookies');
      const cookieFileDetail = document.getElementById('cookieFileDetail');
      const cookieStatusBadge = document.getElementById('cookieStatusBadge');
      if (s.cookies && s.cookies.exists) {
        if (chkCookies) {
          chkCookies.setAttribute('data-lucide', 'check');
          chkCookies.className = 'w-4 h-4 text-emerald-400';
        }
        if (cookieFileDetail) cookieFileDetail.innerText = `(${s.cookies.name || 'cookies.txt'} • ${s.cookies.size || ''})`;
        if (cookieStatusBadge) cookieStatusBadge.innerText = 'Installed';
      } else {
        if (chkCookies) {
          chkCookies.setAttribute('data-lucide', 'alert-circle');
          chkCookies.className = 'w-4 h-4 text-zinc-500';
        }
        if (cookieFileDetail) cookieFileDetail.innerText = '(cookies.txt not found)';
        if (cookieStatusBadge) cookieStatusBadge.innerText = 'Empty';
      }
    }
    lucide.createIcons();
  } catch (err) {
    console.error('[Settings Load Error]', err);
  }
}

async function saveSettings() {
  const storageInput = document.getElementById('inputStorage');
  if (!storageInput || !storageInput.value.trim()) {
    triggerInputError('wrapStorage', 'errStorage', 'Storage directory is required.');
    return;
  }

  const isPathChanged = Boolean(currentStorageDir && storageInput.value.trim().toLowerCase() !== currentStorageDir.toLowerCase());
  const payload = {
    storage_dir: storageInput.value.trim(),
    migrate_files: isPathChanged,
    llm_provider: document.getElementById('selectLlmProvider')?.value,
    transcribe_provider: document.getElementById('selectTranscribeProvider')?.value,
    openai_base_url: document.getElementById('inputOpenaiBase')?.value.trim(),
    openai_model: document.getElementById('inputOpenaiModel')?.value.trim(),
  };

  try {
    const res = await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || 'Could not save settings');
    }

    currentStorageDir = storageInput.value.trim();

    const label = document.getElementById('saveLabel');
    const iconContainer = document.getElementById('saveIconContainer');

    if (label) label.innerText = 'Saved';
    if (iconContainer) {
      iconContainer.innerHTML = `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="text-emerald-400">
          <polyline points="20 6 9 17 4 12"></polyline>
        </svg>
      `;
    }

    if (data.migrated && data.migrated.migrated_files > 0) {
      showToast(`Settings saved. ${data.migrated.migrated_files} files moved to the new folder.`);
    } else {
      showToast('Settings saved successfully');
    }

    if (data.stats) {
      const filesEl = document.getElementById('settingsTotalFiles');
      const sizeEl = document.getElementById('settingsTotalSize');
      if (filesEl) filesEl.innerText = `${data.stats.total_files || 0} files`;
      if (sizeEl) sizeEl.innerText = `${data.stats.total_size_mb || 0} MB`;
    }

    setTimeout(() => {
      if (label) label.innerText = 'Save';
      if (iconContainer) {
        iconContainer.innerHTML = `
          <svg id="saveIcon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-zinc-200">
            <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path>
            <polyline points="17 21 17 13 7 13 7 21"></polyline>
            <polyline points="7 3 7 8 15 8"></polyline>
          </svg>
        `;
      }
    }, 2500);

    // Update local vaultStats storage root if changed
    if (payload.storage_dir && vaultStats) {
      vaultStats.storage_root = payload.storage_dir;
      updateVaultStatsUI();
    }
  } catch (err) {
    if (err.message && err.message.toLowerCase().includes('directory')) {
      triggerInputError('wrapStorage', 'errStorage', err.message);
    }
    showToast(err.message || 'Could not save settings', true);
  }
}

// Model IDs come from a third party, so rows are built with textContent, not HTML.
window.loadOpenaiModels = async function () {
  const hidden = document.getElementById('selectOpenaiModel');
  const input = document.getElementById('inputOpenaiModel');
  const status = document.getElementById('statusOpenaiModels');
  if (!hidden || !input) return;
  const apiKey = document.getElementById('inputOpenai')?.value.trim();
  const current = input.value.trim();
  let models = [];

  // Paint the current model immediately so the trigger is never blank while the
  // provider request is in flight (or when no key is present yet).
  renderOpenaiModelItems(current ? [current] : []);

  // With no typed key the server uses the saved one, for the saved base URL only.
  if (apiKey || providerKeyUi.openai.configured) {
    status.innerText = 'Loading models...';
    try {
      const res = await fetch('/api/settings/openai-models', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          api_key: apiKey,
          base_url: document.getElementById('inputOpenaiBase')?.value.trim()
        })
      });
      if (!res.ok) throw new Error(String(res.status));
      models = (await res.json()).models || [];
      status.innerText = `${models.length} models`;
    } catch (err) {
      status.innerText = 'Could not load models';
    }
  } else {
    status.innerText = providerKeyUi.openai.configured
      ? 'Saved key is hidden; change it to refresh models'
      : 'Add an API key to list models';
  }

  const names = current && !models.includes(current) ? [current, ...models] : models;
  renderOpenaiModelItems(names);
  hidden.value = current || CUSTOM_MODEL;
  const wrap = document.getElementById('wrapOpenaiModelCustom');
  if (wrap) wrap.classList.toggle('hidden', hidden.value !== CUSTOM_MODEL);
  syncModelMenu();
};

async function testApiKey(provider, wrapId, inputId, statusElId, btn) {
  const inputEl = document.getElementById(inputId);
  const statusEl = document.getElementById(statusElId);
  const icon = btn ? btn.querySelector('i') : null;
  const state = providerKeyUi[provider];
  const candidateKey = inputEl?.value.trim() || '';

  if (!inputEl || !state || (state.editing && !candidateKey) || (!state.editing && !state.configured)) {
    triggerInputError(wrapId, wrapId.replace('wrap', 'err'), `Key ${provider} cannot be empty.`);
    if (statusEl) statusEl.innerHTML = '';
    return;
  }

  if (state.editing) {
    state.validated = false;
    updateProviderKeyUI(provider);
  }

  if (icon) icon.classList.add('animate-pulse', 'text-amber-400');
  if (statusEl) statusEl.innerHTML = '<span class="text-zinc-500">Testing...</span>';

  try {
    const res = await fetch('/api/settings/test-key', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider: provider.toLowerCase(),
        api_key: state.editing ? candidateKey : '',
        base_url: provider === 'openai' ? document.getElementById('inputOpenaiBase')?.value.trim() : undefined
      })
    });
    const data = await res.json();
    if (icon) icon.classList.remove('animate-pulse', 'text-amber-400');

    if (res.ok && data.valid) {
      if (state.editing) {
        state.validated = true;
        updateProviderKeyUI(provider);
        if (statusEl) statusEl.innerHTML = '<span class="text-emerald-400">✓ Connection valid · click Save Key to apply</span>';
        showToast(`${provider.toUpperCase()} key verified. Save it to apply.`);
      } else {
        if (statusEl) statusEl.innerHTML = '<span class="text-emerald-400">✓ Saved key connection is valid</span>';
        showToast(`${provider.toUpperCase()} saved key connection is valid`);
      }
      if (provider === 'openai') loadOpenaiModels();
    } else {
      const errMsg = data.message || 'Invalid key';
      if (statusEl) statusEl.innerHTML = `<span class="text-red-400">✗ ${errMsg}</span>`;
      triggerInputError(wrapId, wrapId.replace('wrap', 'err'), `Key ${provider} is invalid: ${errMsg}`);
      showToast(`Key ${provider.toUpperCase()} is invalid`, true);
    }
  } catch (err) {
    if (icon) icon.classList.remove('animate-pulse', 'text-amber-400');
    if (statusEl) statusEl.innerHTML = `<span class="text-red-400">✗ Error jaringan</span>`;
    showToast(`Could not reach the server: ${err.message}`, true);
  }
}

async function runSystemCheck(btn) {
  const icon = document.getElementById('refreshIcon');
  if (icon) icon.classList.add('animate-spin');

  const chkFfmpeg = document.getElementById('chkFfmpeg');
  const statusFfmpeg = document.getElementById('statusFfmpeg');
  const chkYtdlp = document.getElementById('chkYtdlp');
  const statusYtdlp = document.getElementById('statusYtdlp');
  const chkOpencv = document.getElementById('chkOpencv');
  const statusOpencv = document.getElementById('statusOpencv');
  const chkStorage = document.getElementById('chkStorage');
  const statusStorageAccess = document.getElementById('statusStorageAccess');

  // Show a live validation indicator on each item row
  if (statusFfmpeg) statusFfmpeg.innerHTML = '<span class="text-amber-400 animate-pulse font-mono text-[11px]">Checking...</span>';
  if (statusYtdlp) statusYtdlp.innerHTML = '<span class="text-amber-400 animate-pulse font-mono text-[11px]">Checking...</span>';
  if (statusOpencv) statusOpencv.innerHTML = '<span class="text-amber-400 animate-pulse font-mono text-[11px]">Checking...</span>';
  if (statusStorageAccess) statusStorageAccess.innerHTML = '<span class="text-amber-400 animate-pulse font-mono text-[11px]">Checking...</span>';

  [chkFfmpeg, chkYtdlp, chkOpencv, chkStorage].forEach(el => {
    if (el) {
      el.setAttribute('data-lucide', 'loader-2');
      el.className = 'w-4 h-4 text-amber-400 animate-spin';
    }
  });
  lucide.createIcons();

  try {
    const res = await fetch('/api/settings/check-system', { method: 'POST' });
    if (!res.ok) throw new Error('Could not check the system');
    const data = await res.json();

    // FFmpeg
    if (chkFfmpeg) {
      chkFfmpeg.setAttribute('data-lucide', data.ffmpeg ? 'check' : 'x');
      chkFfmpeg.className = data.ffmpeg ? 'w-4 h-4 text-emerald-400' : 'w-4 h-4 text-red-400';
    }
    if (statusFfmpeg) statusFfmpeg.innerText = data.ffmpeg_version || (data.ffmpeg ? 'Available' : 'Not found');

    // yt-dlp
    if (chkYtdlp) {
      chkYtdlp.setAttribute('data-lucide', 'check');
      chkYtdlp.className = 'w-4 h-4 text-emerald-400';
    }
    if (statusYtdlp) statusYtdlp.innerText = data.ytdlp || 'Available';

    // OpenCV
    if (chkOpencv) {
      chkOpencv.setAttribute('data-lucide', data.opencv ? 'check' : 'alert-circle');
      chkOpencv.className = data.opencv ? 'w-4 h-4 text-emerald-400' : 'w-4 h-4 text-amber-400';
    }
    if (statusOpencv) statusOpencv.innerText = data.opencv_version || (data.opencv ? 'Active' : 'Inactive');

    // Storage
    if (chkStorage) {
      chkStorage.setAttribute('data-lucide', data.storage ? 'check' : 'x');
      chkStorage.className = data.storage ? 'w-4 h-4 text-emerald-400' : 'w-4 h-4 text-red-400';
    }
    if (statusStorageAccess) statusStorageAccess.innerText = data.storage ? 'Read/write ready' : 'Access denied';

    lucide.createIcons();
    showToast('Dependency check complete: all utilities are ready');
  } catch (e) {
    showToast(`Dependency check failed: ${e.message}`, true);
  } finally {
    if (icon) icon.classList.remove('animate-spin');
  }
}

async function browseStorageFolder() {
  const btn = document.getElementById('btnBrowseFolder');
  const originalHtml = btn ? btn.innerHTML : '';
  try {
    if (btn) {
      btn.innerHTML = '<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin text-white"></i><span>Opening...</span>';
      lucide.createIcons({ root: btn });
    }
    const res = await fetch('/api/settings/browse-folder', { method: 'POST' });
    if (res.ok) {
      const data = await res.json();
      if (data.path) {
        const newPath = data.path;
        const inputStorage = document.getElementById('inputStorage');
        if (inputStorage) {
          inputStorage.value = newPath;
        }

        // Immediately move the files and save the settings
        if (btn) {
          btn.innerHTML = '<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin text-white"></i><span>Moving...</span>';
          lucide.createIcons({ root: btn });
        }

        showToast(`Moving Media Vault to ${newPath}...`);

        const saveRes = await fetch('/api/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            storage_dir: newPath,
            migrate_files: true
          })
        });

        const saveResult = await saveRes.json();
        if (!saveRes.ok) {
          throw new Error(saveResult.detail || 'Could not move files to the new folder');
        }

        currentStorageDir = newPath;
        if (saveResult.stats) {
          const filesEl = document.getElementById('settingsTotalFiles');
          const sizeEl = document.getElementById('settingsTotalSize');
          if (filesEl) filesEl.innerText = `${saveResult.stats.total_files || 0} files`;
          if (sizeEl) sizeEl.innerText = `${saveResult.stats.total_size_mb || 0} MB`;
        }

        const migratedCount = saveResult.migrated ? (saveResult.migrated.migrated_files || 0) : 0;
        showToast(`Storage moved to ${newPath} (${migratedCount} items moved)`);

        // Sync the Media Vault list.
        if (typeof loadVaultItems === 'function') loadVaultItems();
      }
    } else {
      showToast('Could not open the folder picker', true);
    }
  } catch (err) {
    showToast(`Could not move files: ${err.message}`, true);
  } finally {
    if (btn) {
      btn.innerHTML = originalHtml;
      lucide.createIcons({ root: btn });
    }
  }
}

async function openExplorer() {
  const inputStorage = document.getElementById('inputStorage');
  const folderVal = inputStorage ? inputStorage.value.trim() : '';
  try {
    const res = await fetch('/api/vault/open-folder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder: folderVal })
    });
    if (res.ok) {
      showToast('Opening the storage folder');
    } else {
      showToast('Could not open the folder in Explorer', true);
    }
  } catch (err) {
    showToast('Could not open the folder in Explorer', true);
  }
}

async function handleCookieUpload(input) {
  if (input.files && input.files[0]) {
    const file = input.files[0];
    try {
      const text = await file.text();
      const res = await fetch('/api/settings/upload-cookies', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: file.name, content: text })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Could not upload cookies');

      const detailEl = document.getElementById('cookieFileDetail');
      const badgeEl = document.getElementById('cookieStatusBadge');
      const chkCookies = document.getElementById('chkCookies');

      if (detailEl) detailEl.innerText = `(${data.filename || file.name} • ${data.size || ''})`;
      if (badgeEl) badgeEl.innerText = 'Installed';
      if (chkCookies) {
        chkCookies.setAttribute('data-lucide', 'check');
        chkCookies.className = 'w-4 h-4 text-emerald-400';
      }
      lucide.createIcons();
      showToast(`File ${file.name} uploaded successfully`);
    } catch (err) {
      showToast(`Could not load cookies: ${err.message}`, true);
    }
  }
}


async function loadVaultItems() {
  const loadingEl = document.getElementById('vaultLoadingState');
  if (loadingEl && vaultProjects.length === 0) loadingEl.classList.remove('hidden');

  try {
    const res = await fetch('/api/vault/projects');
    if (!res.ok) throw new Error('Could not load Media Vault');
    const data = await res.json();
    vaultProjects = data.projects || [];
    nextWorkspaceIndex = data.next_workspace_index || 1;
    vaultStats = data.stats || vaultStats;

    vaultItems = [];
    vaultProjects.forEach(p => {
      if (p.files && Array.isArray(p.files)) {
        vaultItems.push(...p.files);
      }
    });

    updateVaultStatsUI();
    renderVaultGallery();
  } catch (err) {
    console.error('[Vault Load Error]', err);
  } finally {
    if (loadingEl) loadingEl.classList.add('hidden');
  }
}

async function updateVaultBadge() {
  try {
    const res = await fetch('/api/vault/projects');
    if (res.ok) {
      const data = await res.json();
      vaultProjects = data.projects || [];
      nextWorkspaceIndex = data.next_workspace_index || 1;
      vaultStats = data.stats || vaultStats;
      vaultItems = [];
      vaultProjects.forEach(p => {
        if (p.files && Array.isArray(p.files)) {
          vaultItems.push(...p.files);
        }
      });
      updateVaultStatsUI();
    }
  } catch (e) {
    console.warn('Could not auto-fetch vault count', e);
  }
}

function updateVaultStatsUI() {
  const totalCount = vaultStats.total_files !== undefined ? vaultStats.total_files : vaultItems.length;

  const totalFiles = document.getElementById('vaultTotalFiles');
  if (totalFiles) totalFiles.innerText = totalCount;

  const settingsFiles = document.getElementById('settingsTotalFiles');
  if (settingsFiles) settingsFiles.innerText = `${totalCount} files`;

  let sizeStr = '0 MB';
  if (vaultStats.total_gb && vaultStats.total_gb >= 1.0) {
    sizeStr = `${vaultStats.total_gb} GB`;
  } else {
    sizeStr = `${vaultStats.total_mb || 0} MB`;
  }

  const totalSize = document.getElementById('vaultTotalSize');
  if (totalSize) totalSize.innerText = sizeStr;

  const settingsSize = document.getElementById('settingsTotalSize');
  if (settingsSize) settingsSize.innerText = sizeStr;

  const storagePath = document.getElementById('vaultStoragePath');
  if (storagePath && vaultStats.storage_root) {
    storagePath.innerText = vaultStats.storage_root;
  }

  if (currentMainTab === 'vault') {
    requestAnimationFrame(() => updateTabsPill(false));
  }
}

function setVaultFilter(filter, btn) {
  currentVaultFilter = filter;
  const chips = document.querySelectorAll('.vault-chip-btn');
  chips.forEach(c => {
    c.className = 'vault-chip-btn px-3.5 py-1.5 rounded-xl font-sans text-xs font-medium transition cursor-pointer bg-white/[0.04] border border-white/[0.08] text-zinc-400 hover:text-white hover:bg-white/[0.08]';
  });
  if (btn) {
    btn.className = 'vault-chip-btn px-3.5 py-1.5 rounded-xl font-sans text-xs font-semibold transition cursor-pointer active bg-white text-black shadow-[0_2px_12px_rgba(255,255,255,0.2)]';
  }
  renderVaultGallery();
}

function onVaultSearchInput(val) {
  currentVaultSearch = (val || '').toLowerCase().trim();
  const clearBtn = document.getElementById('vaultSearchClearBtn');
  if (clearBtn) {
    if (currentVaultSearch) clearBtn.classList.remove('hidden');
    else clearBtn.classList.add('hidden');
  }
  renderVaultGallery();
}

function clearVaultSearch() {
  const searchInput = document.getElementById('vaultSearchInput');
  if (searchInput) searchInput.value = '';
  currentVaultSearch = '';
  const clearBtn = document.getElementById('vaultSearchClearBtn');
  if (clearBtn) clearBtn.classList.add('hidden');
  renderVaultGallery();
}

function matchesFilter(item) {
  const cat = (item.category || '').toLowerCase();
  const act = (item.action || '').toLowerCase();
  const plat = (item.platform || '').toLowerCase();
  const fname = (item.filename || '').toLowerCase();
  const isAudio = cat.includes('audio') || act.includes('mp3') || item.type === 'audio' || fname.endsWith('.mp3');
  const isClip = cat.includes('clip') || act.includes('ai_clip') || (item.id && item.id.startsWith('clip_'));

  if (currentVaultFilter === 'youtube') return plat === 'youtube' && !isClip && !isAudio;
  if (currentVaultFilter === 'instagram') return plat === 'instagram' || cat.includes('instagram') || cat.includes('reels');
  if (currentVaultFilter === 'tiktok') return plat === 'tiktok' || cat.includes('tiktok');
  if (currentVaultFilter === 'clips') return isClip;
  if (currentVaultFilter === 'audio') return isAudio;
  return true;
}

function matchesProjectFilter(proj) {
  const plat = (proj.platform || '').toLowerCase();
  const act = (proj.action || '').toLowerCase();
  const isClip = act.includes('ai_clip') || act.includes('clip') || plat.includes('clip');
  const isAudio = act.includes('mp3') || plat.includes('audio');

  if (currentVaultFilter === 'youtube') return plat.includes('youtube') && !isClip && !isAudio;
  if (currentVaultFilter === 'instagram') return plat.includes('instagram') || act.includes('reels');
  if (currentVaultFilter === 'tiktok') return plat.includes('tiktok');
  if (currentVaultFilter === 'clips') return isClip;
  if (currentVaultFilter === 'audio') return isAudio;
  return true;
}

function matchesSearch(item) {
  if (!currentVaultSearch) return true;
  const title = (item.title || '').toLowerCase();
  const fname = (item.filename || '').toLowerCase();
  const caption = (item.caption || '').toLowerCase();
  const plat = (item.platform || '').toLowerCase();
  return title.includes(currentVaultSearch) ||
    fname.includes(currentVaultSearch) ||
    caption.includes(currentVaultSearch) ||
    plat.includes(currentVaultSearch);
}

function matchesProjectSearch(proj) {
  if (!currentVaultSearch) return true;
  const ws = (proj.workspace_name || '').toLowerCase();
  const title = (proj.source_title || '').toLowerCase();
  const plat = (proj.platform || '').toLowerCase();
  if (ws.includes(currentVaultSearch) || title.includes(currentVaultSearch) || plat.includes(currentVaultSearch)) {
    return true;
  }
  if (proj.files && Array.isArray(proj.files)) {
    return proj.files.some(f =>
      (f.title || '').toLowerCase().includes(currentVaultSearch) ||
      (f.filename || '').toLowerCase().includes(currentVaultSearch)
    );
  }
  return false;
}

function getProjectMeter(proj) {
  const act = (proj.action || '').toLowerCase();
  const plat = (proj.platform || '').toLowerCase();
  if (act.includes('ai_clip')) {
    return { signal: 3, tone: '#ffffff', label: 'AI Clipper' };
  }
  if (act.includes('clip') || act.includes('trim')) {
    return { signal: 3, tone: '#a1a1aa', label: 'Video Trimmer' };
  }
  if (plat.includes('youtube') || act.includes('video')) {
    return { signal: 3, tone: '#ef4444', label: 'YouTube' };
  }
  if (plat.includes('instagram') || act.includes('reels')) {
    return { signal: 3, tone: '#ec4899', label: 'Instagram Reels' };
  }
  if (plat.includes('tiktok')) {
    return { signal: 3, tone: '#a1a1aa', label: 'TikTok Clean' };
  }
  if (act.includes('mp3') || plat.includes('audio')) {
    return { signal: 3, tone: '#f59e0b', label: 'Audio MP3' };
  }
  return { signal: 2, tone: '#a1a1aa', label: 'Media Vault' };
}

function renderVaultGallery() {
  const grid = document.getElementById('vaultGalleryGrid');
  const emptyState = document.getElementById('vaultEmptyState');
  const emptyTitle = document.getElementById('vaultEmptyTitle');
  const emptyDesc = document.getElementById('vaultEmptyDesc');
  if (!grid) return;

  grid.innerHTML = '';

  const filtered = vaultProjects.filter(p => matchesProjectFilter(p) && matchesProjectSearch(p));

  if (filtered.length === 0) {
    if (emptyState) {
      emptyState.classList.remove('hidden');
      if (currentVaultSearch) {
        if (emptyTitle) emptyTitle.innerText = 'Not found';
        if (emptyDesc) emptyDesc.innerText = `No projects match the search "${currentVaultSearch}".`;
      } else if (currentVaultFilter !== 'all') {
        if (emptyTitle) emptyTitle.innerText = 'Kategori Empty';
        if (emptyDesc) emptyDesc.innerText = 'No projects match this filter yet.';
      } else {
        if (emptyTitle) emptyTitle.innerText = 'No media in the vault yet';
        if (emptyDesc) emptyDesc.innerText = 'Downloaded media and generated AI clips will appear here, ready to play.';
      }
    }
    return;
  }

  if (emptyState) emptyState.classList.add('hidden');

  filtered.forEach(proj => {
    const card = document.createElement('div');
    card.id = `vault-proj-card-${proj.project_id}`;
    card.className = 't-rec-card cursor-pointer';
    const isVirtualProj = !!proj.virtual;
    if (isVirtualProj) card.title = 'Category archive — not deletable';
    card.onclick = (e) => {
      if (!e.target.closest('button') && !e.target.closest('a')) {
        openProjectPage(proj.project_id);
      }
    };

    const meter = getProjectMeter(proj);

    card.innerHTML = `
      <!-- primitive-card-pad -->
      <div class="primitive-card-pad">
        <span class="text-[14px] font-medium text-white tracking-tight block truncate">
          ${escapeHtml(proj.workspace_name)}
        </span>
        <p class="mt-1.5 min-h-[44px] text-[13px] leading-relaxed text-zinc-400 line-clamp-2">
          ${escapeHtml(proj.source_title || 'Media Project')}
        </p>
      </div>

      <!-- primitive-card-footer -->
      <div class="primitive-card-footer flex items-center justify-between gap-3 bg-surface">
        <span class="flex items-center gap-2">
          <span class="flex items-end gap-0.5">
            <span class="w-1 rounded-full transition-colors duration-300" style="height: 10px; background: ${meter.signal >= 1 ? meter.tone : 'rgba(255, 255, 255, 0.16)'};"></span>
            <span class="w-1 rounded-full transition-colors duration-300" style="height: 10px; background: ${meter.signal >= 2 ? meter.tone : 'rgba(255, 255, 255, 0.16)'};"></span>
            <span class="w-1 rounded-full transition-colors duration-300" style="height: 10px; background: ${meter.signal >= 3 ? meter.tone : 'rgba(255, 255, 255, 0.16)'};"></span>
          </span>
          <span class="text-[12.5px] font-medium text-zinc-400">${meter.label}</span>
        </span>

        <span class="-mr-0.5 flex items-center gap-1.5">
          <button 
            type="button" 
            onclick="confirmDeleteVaultProject('${proj.project_id}', '${escapeQuotes(proj.workspace_name)}', event)" 
            class="t-card-btn-delete group${isVirtualProj ? ' hidden' : ''}"
            title="${isVirtualProj ? 'Category archive — not deletable' : 'Delete Workspace'}"
            ${isVirtualProj ? 'disabled aria-disabled="true"' : ''}>
            <i data-lucide="trash-2" class="w-3.5 h-3.5 t-btn-icon"></i>
          </button>
          <button 
            type="button" 
            onclick="openProjectPage('${proj.project_id}')" 
            class="t-card-btn-open t-learn group"
            title="Open Workspace">
            <span>Open</span>
            <span class="t-learn-chevron">
              <svg class="w-3.5 h-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <path class="t-learn-arm t-learn-arm-top" d="M6 4L10 8"/>
                <path class="t-learn-arm t-learn-arm-bot" d="M10 8L6 12"/>
              </svg>
            </span>
          </button>
        </span>
      </div>
    `;

    grid.appendChild(card);
  });

  lucide.createIcons();
}

async function openProjectPage(projectId) {
  if (!projectId) return;
  let proj = vaultProjects.find(p => p.project_id === projectId);
  if (!proj) {
    try {
      const res = await fetch('/api/vault/projects');
      if (res.ok) {
        const data = await res.json();
        vaultProjects = data.projects || [];
        proj = vaultProjects.find(p => p.project_id === projectId);
      }
    } catch (e) {
      console.warn('Error fetching projects in openProjectPage:', e);
    }
  }
  if (!proj) return;
  currentActiveProjectId = projectId;
  document.body.classList.add('in-workspace');

  window.location.hash = `vault-project/${projectId}`;
  document.title = `${proj.workspace_name} (${projectId}) | Luna`;

  const listView = document.getElementById('vaultProjectsListView');
  const detailView = document.getElementById('vaultProjectDetailView');
  if (listView) listView.classList.add('hidden');
  if (detailView) detailView.classList.remove('hidden');

  const titleEl = document.getElementById('projectDetailPageTitle');
  const idEl = document.getElementById('projectDetailPageId');
  const srcEl = document.getElementById('projectDetailSourceTitle');
  const countEl = document.getElementById('projectDetailFileCount');
  const sizeEl = document.getElementById('projectDetailTotalSize');
  const dateEl = document.getElementById('projectDetailCreatedDate');
  const breadcrumbEl = document.getElementById('detailViewBreadcrumb');
  const btnRename = document.getElementById('btnRenameInDetail');
  const btnDelete = document.getElementById('btnDeleteInDetail');

  const files = proj.files || [];
  const totalSize = files.reduce((acc, f) => acc + (f.file_size || 0), 0);

  if (titleEl) titleEl.innerText = proj.workspace_name || 'Workspace';
  if (idEl) idEl.innerText = `ID: ${proj.project_id}`;
  if (srcEl) {
    srcEl.innerHTML = '';
    srcEl.classList.add('hidden');
  }
  if (countEl) countEl.innerText = `${files.length} Media Files`;
  if (sizeEl) sizeEl.innerText = `${formatBytes(totalSize)} Total`;
  if (dateEl) dateEl.innerText = formatSavedDate(proj.created_at);
  if (breadcrumbEl) breadcrumbEl.innerText = `${proj.project_id}`;

  if (btnRename) {
    btnRename.onclick = () => promptRenameWorkspace(proj.project_id, proj.workspace_name);
  }
  if (btnDelete) {
    btnDelete.onclick = (e) => confirmDeleteVaultProject(proj.project_id, proj.workspace_name, e);
  }

  const stdView = document.getElementById('vaultStandardDetailView');
  const clipContainer = document.getElementById('clipperWorkflowContainer');
  const clipperTitle = document.getElementById('clipperWorkspaceTitle');
  const clipperId = document.getElementById('clipperWorkspaceId');
  const btnClipperRename = document.getElementById('btnClipperRename');
  const btnClipperDelete = document.getElementById('btnClipperDelete');

  const isVirtualProj = !!proj.virtual;
  if (isVirtualProj && titleEl) titleEl.title = 'Category archive — not deletable';
  else if (titleEl) titleEl.removeAttribute('title');
  [btnRename, btnDelete, btnClipperRename, btnClipperDelete].forEach(btn => {
    if (!btn) return;
    if (btn.dataset.baseTitle === undefined) btn.dataset.baseTitle = btn.getAttribute('title') || '';
    btn.classList.toggle('hidden', isVirtualProj);
    btn.title = isVirtualProj ? 'Category archive — not deletable' : btn.dataset.baseTitle;
    if (isVirtualProj) {
      btn.setAttribute('disabled', 'disabled');
      btn.setAttribute('aria-disabled', 'true');
    } else {
      btn.removeAttribute('disabled');
      btn.removeAttribute('aria-disabled');
    }
  });

  if (clipperTitle) clipperTitle.innerText = proj.workspace_name || 'Workspace';
  if (clipperId) clipperId.innerText = `ID: ${proj.project_id}`;
  if (btnClipperRename) {
    btnClipperRename.onclick = () => promptRenameWorkspace(proj.project_id, proj.workspace_name);
  }
  if (btnClipperDelete) {
    btnClipperDelete.onclick = (e) => confirmDeleteVaultProject(proj.project_id, proj.workspace_name, e);
  }

  if (isAiClipperProject(proj)) {
    if (stdView) stdView.classList.add('hidden');
    if (clipContainer) clipContainer.classList.remove('hidden');
    renderClipperWorkflow(proj);
  } else {
    if (clipContainer) clipContainer.classList.add('hidden');
    if (stdView) stdView.classList.remove('hidden');
    renderProjectFiles(proj);
    requestAnimationFrame(() => {
      setVaultMediaFilter(window.currentVaultMediaFilter || 'all', true);
    });
  }

  window.scrollTo({ top: 0, behavior: 'instant' });
  lucide.createIcons();
}

function formatAudioSeconds(sec) {
  if (isNaN(sec) || sec === Infinity || sec < 0) return '0:00';
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s < 10 ? '0' : ''}${s}`;
}

window.toggleCustomAudioPlay = function (fileId) {
  const audioEl = document.getElementById(`audio-el-${fileId}`);
  const btn = document.getElementById(`audio-play-btn-${fileId}`);
  const vinyl = document.getElementById(`vinyl-disc-${fileId}`);
  const waveform = document.getElementById(`waveform-bars-${fileId}`);
  const statusEl = document.getElementById(`audio-status-${fileId}`);
  if (!audioEl) return;

  if (currentlyPlayingAudioId && currentlyPlayingAudioId !== fileId) {
    const prevEl = document.getElementById(`audio-el-${currentlyPlayingAudioId}`);
    const prevBtn = document.getElementById(`audio-play-btn-${currentlyPlayingAudioId}`);
    const prevVinyl = document.getElementById(`vinyl-disc-${currentlyPlayingAudioId}`);
    const prevWaveform = document.getElementById(`waveform-bars-${currentlyPlayingAudioId}`);
    const prevStatus = document.getElementById(`audio-status-${currentlyPlayingAudioId}`);
    if (prevEl) prevEl.pause();
    if (prevBtn) prevBtn.innerHTML = '<i data-lucide="play" class="w-3.5 h-3.5 ml-0.5"></i>';
    if (prevVinyl) prevVinyl.classList.remove('spinning');
    if (prevWaveform) prevWaveform.classList.remove('playing');
    if (prevStatus) prevStatus.innerText = 'Audio Track';
  }

  if (audioEl.paused) {
    audioEl.play().then(() => {
      currentlyPlayingAudioId = fileId;
      if (btn) btn.innerHTML = '<i data-lucide="pause" class="w-3.5 h-3.5"></i>';
      if (vinyl) vinyl.classList.add('spinning');
      if (waveform) waveform.classList.add('playing');
      if (statusEl) statusEl.innerText = 'Playing';
      lucide.createIcons();
    }).catch(err => {
      console.warn('Audio play error:', err);
    });
  } else {
    audioEl.pause();
    currentlyPlayingAudioId = null;
    if (btn) btn.innerHTML = '<i data-lucide="play" class="w-3.5 h-3.5 ml-0.5"></i>';
    if (vinyl) vinyl.classList.remove('spinning');
    if (waveform) waveform.classList.remove('playing');
    if (statusEl) statusEl.innerText = 'Paused';
    lucide.createIcons();
  }
};

window.seekCustomAudio = function (e, fileId) {
  const audioEl = document.getElementById(`audio-el-${fileId}`);
  if (!audioEl || !audioEl.duration) return;
  const rect = e.currentTarget.getBoundingClientRect();
  const pos = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
  audioEl.currentTime = pos * audioEl.duration;
  const progressEl = document.getElementById(`audio-progress-${fileId}`);
  if (progressEl) progressEl.style.width = (pos * 100) + '%';
};

window.toggleCustomAudioMute = function (fileId) {
  const audioEl = document.getElementById(`audio-el-${fileId}`);
  const btn = document.getElementById(`audio-mute-btn-${fileId}`);
  if (!audioEl) return;
  audioEl.muted = !audioEl.muted;
  if (btn) {
    btn.innerHTML = audioEl.muted
      ? '<i data-lucide="volume-x" class="w-3.5 h-3.5 text-red-400"></i>'
      : '<i data-lucide="volume-2" class="w-3.5 h-3.5"></i>';
    lucide.createIcons();
  }
};

window.initAudioEvents = function (fileId) {
  const audioEl = document.getElementById(`audio-el-${fileId}`);
  if (!audioEl) return;

  audioEl.ontimeupdate = () => {
    const timeEl = document.getElementById(`audio-time-${fileId}`);
    const progressEl = document.getElementById(`audio-progress-${fileId}`);
    if (timeEl) timeEl.innerText = formatAudioSeconds(audioEl.currentTime);
    if (progressEl && audioEl.duration) {
      progressEl.style.width = ((audioEl.currentTime / audioEl.duration) * 100) + '%';
    }
  };

  audioEl.onloadedmetadata = () => {
    const durEl = document.getElementById(`audio-dur-${fileId}`);
    if (durEl && audioEl.duration) {
      durEl.innerText = formatAudioSeconds(audioEl.duration);
    }
  };

  audioEl.onended = () => {
    const btn = document.getElementById(`audio-play-btn-${fileId}`);
    const vinyl = document.getElementById(`vinyl-disc-${fileId}`);
    const waveform = document.getElementById(`waveform-bars-${fileId}`);
    const statusEl = document.getElementById(`audio-status-${fileId}`);
    const progressEl = document.getElementById(`audio-progress-${fileId}`);
    if (btn) btn.innerHTML = '<i data-lucide="play" class="w-3.5 h-3.5 ml-0.5"></i>';
    if (vinyl) vinyl.classList.remove('spinning');
    if (waveform) waveform.classList.remove('playing');
    if (statusEl) statusEl.innerText = 'Completed';
    if (progressEl) progressEl.style.width = '0%';
    if (currentlyPlayingAudioId === fileId) currentlyPlayingAudioId = null;
    lucide.createIcons();
  };
};

// A workspace can hold 16:9, 9:16, 3:4, 4:3 and 1:1 files side by side, so the pill
// has to describe the real ratio instead of "portrait or not".
const VAULT_RATIOS = [
  { ratio: 16 / 9, label: '16:9 Landscape', kind: 'landscape', icon: 'tv' },
  { ratio: 4 / 3, label: '4:3 Landscape', kind: 'landscape', icon: 'tv' },
  { ratio: 9 / 16, label: '9:16 Portrait', kind: 'portrait', icon: 'smartphone' },
  { ratio: 3 / 4, label: '3:4 Portrait', kind: 'portrait', icon: 'smartphone' },
  { ratio: 1, label: '1:1 Square', kind: 'square', icon: 'square' },
];

function ratioMetaFromSize(width, height) {
  if (!width || !height) return null;
  const actual = width / height;
  let best = null;
  for (const item of VAULT_RATIOS) {
    const diff = Math.abs(actual - item.ratio) / item.ratio;
    if (diff <= 0.06 && (!best || diff < best.diff)) best = { ...item, diff };
  }
  if (best) return best;
  const kind = actual > 1.05 ? 'landscape' : (actual < 0.95 ? 'portrait' : 'square');
  return {
    label: `${width}:${height}`,
    kind,
    icon: kind === 'portrait' ? 'smartphone' : (kind === 'square' ? 'square' : 'tv'),
  };
}

function ratioMetaFromValue(value) {
  if (!value) return null;
  const match = String(value).match(/(\d{1,4})\s*[:x×]\s*(\d{1,4})/i);
  return match ? ratioMetaFromSize(Number(match[1]), Number(match[2])) : null;
}

function ratioMetaFromFilename(name) {
  const match = /_(\d{1,2})x(\d{1,2})(?:\.[a-z0-9]+)?$/i.exec(name || '');
  return match ? ratioMetaFromSize(Number(match[1]), Number(match[2])) : null;
}

function ratioAspectClass(meta) {
  if (!meta) return 'aspect-video';
  if (meta.kind === 'square') return 'aspect-square';
  if (meta.kind === 'portrait') return meta.label.indexOf('3:4') === 0 ? 'aspect-[3/4]' : 'aspect-[9/16]';
  return 'aspect-video';
}

// The class above is cosmetic; the inline style keeps the box correct even if the
// utility for that ratio has not been generated yet.
function ratioAspectStyle(meta) {
  if (!meta) return '16 / 9';
  if (meta.kind === 'square') return '1 / 1';
  if (meta.kind === 'portrait') return meta.label.indexOf('3:4') === 0 ? '3 / 4' : '9 / 16';
  return '16 / 9';
}

window.handleVaultVideoMetadata = function (videoEl, fileId) {
  if (!videoEl || !videoEl.videoWidth || !videoEl.videoHeight) return;
  const wrapper = videoEl.closest('.video-preview-wrapper');
  if (!wrapper) return;
  const card = wrapper.closest('.t-rec-card') || wrapper.closest('[data-media-type]') || wrapper.parentElement;
  const meta = ratioMetaFromSize(videoEl.videoWidth, videoEl.videoHeight);
  const ratioText = wrapper.querySelector('.ratio-text');
  const icon = wrapper.querySelector('.ratio-pill [data-lucide]');
  const isSingleCard = card && card.classList.contains('single-result-card');
  const isWide = !meta || meta.kind === 'landscape';

  wrapper.classList.remove('aspect-video', 'aspect-[4/5]', 'aspect-[9/16]', 'aspect-[3/4]', 'aspect-square');
  wrapper.classList.add(ratioAspectClass(meta));
  wrapper.style.aspectRatio = ratioAspectStyle(meta);

  if (isSingleCard) {
    wrapper.classList.remove('max-h-[460px]', 'max-h-[500px]', 'max-h-[520px]', 'max-h-[580px]');
    if (isWide) {
      wrapper.classList.add('max-h-[520px]');
      card.classList.remove('max-w-md');
      card.classList.add('max-w-3xl');
    } else {
      wrapper.classList.add('max-h-[580px]');
      card.classList.remove('max-w-3xl');
      card.classList.add('max-w-md');
    }
  } else {
    wrapper.classList.remove('max-h-[500px]', 'max-h-[520px]', 'max-h-[580px]');
    wrapper.classList.add(isWide ? 'max-h-[520px]' : 'max-h-[500px]');
  }

  if (card) card.setAttribute('data-media-type', meta ? meta.kind : 'landscape');
  if (ratioText) ratioText.innerText = meta ? meta.label : 'Video';
  if (icon && meta) {
    icon.setAttribute('data-lucide', meta.icon);
    icon.className = isWide ? 'w-3 h-3 text-zinc-400' : 'w-3 h-3 text-white';
  }
  lucide.createIcons();
  if (typeof updateVaultFilterCounters === 'function') {
    updateVaultFilterCounters();
  }
  if (window.currentVaultMediaFilter && window.currentVaultMediaFilter !== 'all') {
    window.setVaultMediaFilter(window.currentVaultMediaFilter);
  }
};

function closeProjectPage() {
  if (currentlyPlayingAudioId) {
    const otherEl = document.getElementById(`audio-el-${currentlyPlayingAudioId}`);
    if (otherEl) otherEl.pause();
    currentlyPlayingAudioId = null;
  }
  document.querySelectorAll('video').forEach(v => v.pause());
  currentActiveProjectId = null;
  document.body.classList.remove('in-workspace');
  if (window.location.hash) {
    history.replaceState(null, '', window.location.pathname);
  }
  document.title = 'Luna: AI Video Clipper & Downloader';

  const listView = document.getElementById('vaultProjectsListView');
  const detailView = document.getElementById('vaultProjectDetailView');
  const clipContainer = document.getElementById('clipperWorkflowContainer');
  const stdView = document.getElementById('vaultStandardDetailView');
  if (clipContainer) clipContainer.classList.add('hidden');
  if (stdView) stdView.classList.add('hidden');
  if (detailView) detailView.classList.add('hidden');
  if (listView) listView.classList.remove('hidden');

  window.scrollTo({ top: 0, behavior: 'instant' });
  lucide.createIcons();
}

// Global Sutro media player engine
window.compactSutroPlayers = function () {
  document.querySelectorAll('media-theme-sutro').forEach(player => {
    if (!player.shadowRoot) return;
    if (!player.shadowRoot.querySelector('#sutro-mini-style')) {
      const st = document.createElement('style');
      st.id = 'sutro-mini-style';
      st.textContent = `
        :host {
          --media-tooltip-display: none !important;
        }

        /* Completely disable tap/click on video area to play/pause - ONLY play button controls playback */
        media-gesture-receiver,
        slot[name="gestures-chrome"],
        [part~="gesture-layer"],
        media-controller::part(gesture-layer) {
          display: none !important;
          pointer-events: none !important;
        }

        /* Video ignores direct pointer events in cards so drag passes through and no accidental play occurs */
        video[slot="media"],
        ::slotted(video) {
          pointer-events: none !important;
        }

        /* Hide settings gear button & menu */
        media-settings-menu-button,
        media-settings-menu {
          display: none !important;
        }

        /* Completely disable & hide button tooltips (Pause, Play, Fullscreen, etc.) */
        media-tooltip,
        [part~="tooltip"],
        slot[name="tooltip"],
        media-play-button::part(tooltip),
        media-fullscreen-button::part(tooltip),
        media-mute-button::part(tooltip),
        media-chrome-button::part(tooltip) {
          display: none !important;
          opacity: 0 !important;
          visibility: hidden !important;
          pointer-events: none !important;
        }

        /* Universal Base Controls: Play, Time, Scrubber, Mute, Fullscreen ALWAYS visible */
        media-control-bar {
          display: flex !important;
          visibility: visible !important;
          opacity: 1 !important;
          align-items: center !important;
          z-index: 30 !important;
          pointer-events: auto !important;
        }
        media-play-button {
          display: inline-flex !important;
          visibility: visible !important;
          opacity: 1 !important;
          flex-shrink: 0 !important;
          cursor: pointer !important;
          pointer-events: auto !important;
        }
        media-mute-button {
          display: inline-flex !important;
          visibility: visible !important;
          opacity: 1 !important;
          flex-shrink: 0 !important;
          cursor: pointer !important;
          pointer-events: auto !important;
        }
        media-time-display {
          display: inline-flex !important;
          visibility: visible !important;
          opacity: 1 !important;
          flex-shrink: 0 !important;
        }
        media-time-range {
          display: block !important;
          flex: 1 1 auto !important;
          min-width: 44px !important;
          visibility: visible !important;
          opacity: 1 !important;
          cursor: pointer !important;
          pointer-events: auto !important;
          --media-range-track-background: rgba(255, 255, 255, 0.28) !important;
          --media-range-bar-color: #ffffff !important;
        }
        media-fullscreen-button {
          display: inline-flex !important;
          visibility: visible !important;
          opacity: 1 !important;
          flex-shrink: 0 !important;
          cursor: pointer !important;
          pointer-events: auto !important;
        }
        media-pip-button,
        [part~="pip-button"] {
          display: none !important;
          visibility: hidden !important;
          opacity: 0 !important;
          pointer-events: none !important;
        }

        /* 1. CARD MODE: MINI (AI Clipper Canvas, 9:16 narrow card) */
        :host([data-player-size="mini"]) media-controller:not([mediaisfullscreen]):not(:fullscreen) {
          --base: 11px !important;
          --media-control-height: 22px !important;
          --media-font-size: 10.5px !important;
          --media-icon-height: 15px !important;
          font-size: 10.5px !important;
        }
        :host([data-player-size="mini"]) media-controller:not([mediaisfullscreen]):not(:fullscreen) media-control-bar {
          height: 22px !important;
          line-height: 22px !important;
          bottom: 8px !important;
          left: 8px !important;
          right: 8px !important;
          gap: 3px !important;
        }
        :host([data-player-size="mini"]) media-controller:not([mediaisfullscreen]):not(:fullscreen) media-time-range {
          height: 16px !important;
          --media-range-thumb-width: 9px !important;
          --media-range-thumb-height: 9px !important;
          --media-range-track-height: 3.5px !important;
          --media-range-bar-height: 3.5px !important;
        }
        :host([data-player-size="mini"]) media-controller:not([mediaisfullscreen]):not(:fullscreen) .media-volume-range-wrapper {
          position: absolute !important;
          bottom: 100% !important;
          top: auto !important;
          left: 16px !important;
          width: 68px !important;
          height: 22px !important;
          padding: 0 0 13px 0 !important;
          margin: 0 !important;
          background: transparent !important;
          border: none !important;
          box-shadow: none !important;
          display: flex !important;
          align-items: flex-start !important;
          box-sizing: border-box !important;
        }
        :host([data-player-size="mini"]) media-controller:not([mediaisfullscreen]):not(:fullscreen) media-volume-range {
          width: 68px !important;
          height: 9px !important;
          padding: 0 !important;
          border-radius: 4.5px !important;
          overflow: hidden !important;
          background: rgba(255, 255, 255, 0.25) !important;
          backdrop-filter: blur(8px) !important;
          border: none !important;
          box-shadow: none !important;
          --media-range-bar-color: #ffffff !important;
          --media-range-track-width: 68px !important;
          --media-range-track-height: 9px !important;
          --media-range-track-border-radius: 4.5px !important;
          --media-range-thumb-width: 0px !important;
          --media-range-thumb-opacity: 0 !important;
        }

        /* 2. CARD MODE: MEDIUM (Multi-video grid cards ~350px-450px) */
        :host([data-player-size="medium"]) media-controller:not([mediaisfullscreen]):not(:fullscreen) {
          --base: 13px !important;
          --media-control-height: 28px !important;
          --media-font-size: 11.5px !important;
          --media-icon-height: 17px !important;
          font-size: 11.5px !important;
        }
        :host([data-player-size="medium"]) media-controller:not([mediaisfullscreen]):not(:fullscreen) media-control-bar {
          height: 28px !important;
          line-height: 28px !important;
          bottom: 10px !important;
          left: 10px !important;
          right: 10px !important;
          gap: 5px !important;
        }
        :host([data-player-size="medium"]) media-controller:not([mediaisfullscreen]):not(:fullscreen) media-time-range {
          height: 18px !important;
          --media-range-thumb-width: 11px !important;
          --media-range-thumb-height: 11px !important;
          --media-range-track-height: 4px !important;
          --media-range-bar-height: 4px !important;
        }
        :host([data-player-size="medium"]) media-controller:not([mediaisfullscreen]):not(:fullscreen) .media-volume-range-wrapper {
          position: absolute !important;
          bottom: 100% !important;
          top: auto !important;
          left: 24px !important;
          width: 80px !important;
          height: 24px !important;
          padding: 0 0 14px 0 !important;
          margin: 0 !important;
          background: transparent !important;
          border: none !important;
          box-shadow: none !important;
          display: flex !important;
          align-items: flex-start !important;
          box-sizing: border-box !important;
        }
        :host([data-player-size="medium"]) media-controller:not([mediaisfullscreen]):not(:fullscreen) media-volume-range {
          width: 80px !important;
          height: 10px !important;
          padding: 0 !important;
          border-radius: 5px !important;
          overflow: hidden !important;
          background: rgba(255, 255, 255, 0.25) !important;
          backdrop-filter: blur(8px) !important;
          border: none !important;
          box-shadow: none !important;
          --media-range-bar-color: #ffffff !important;
          --media-range-track-width: 80px !important;
          --media-range-track-height: 10px !important;
          --media-range-track-border-radius: 5px !important;
          --media-range-thumb-width: 0px !important;
          --media-range-thumb-opacity: 0 !important;
        }

        /* 3. CARD MODE: LARGE / DEFAULT (Single video card ~768px, like YouTube full download) */
        :host([data-player-size="large"]) media-controller:not([mediaisfullscreen]):not(:fullscreen),
        :host(:not([data-player-size="mini"]):not([data-player-size="medium"])) media-controller:not([mediaisfullscreen]):not(:fullscreen) {
          --base: 15px !important;
          --media-control-height: 38px !important;
          --media-font-size: 13px !important;
          --media-icon-height: 20px !important;
          font-size: 13px !important;
        }
        :host([data-player-size="large"]) media-controller:not([mediaisfullscreen]):not(:fullscreen) media-control-bar,
        :host(:not([data-player-size="mini"]):not([data-player-size="medium"])) media-controller:not([mediaisfullscreen]):not(:fullscreen) media-control-bar {
          height: 38px !important;
          line-height: 38px !important;
          bottom: 12px !important;
          left: 14px !important;
          right: 14px !important;
          gap: 8px !important;
        }
        :host([data-player-size="large"]) media-controller:not([mediaisfullscreen]):not(:fullscreen) media-time-range,
        :host(:not([data-player-size="mini"]):not([data-player-size="medium"])) media-controller:not([mediaisfullscreen]):not(:fullscreen) media-time-range {
          height: 22px !important;
          --media-range-thumb-width: 13px !important;
          --media-range-thumb-height: 13px !important;
          --media-range-track-height: 4.5px !important;
          --media-range-bar-height: 4.5px !important;
        }
        :host([data-player-size="large"]) media-controller:not([mediaisfullscreen]):not(:fullscreen) .media-volume-range-wrapper,
        :host(:not([data-player-size="mini"]):not([data-player-size="medium"])) media-controller:not([mediaisfullscreen]):not(:fullscreen) .media-volume-range-wrapper {
          position: absolute !important;
          bottom: 100% !important;
          top: auto !important;
          left: 32px !important;
          width: 100px !important;
          height: 26px !important;
          padding: 0 0 16px 0 !important;
          margin: 0 !important;
          background: transparent !important;
          border: none !important;
          box-shadow: none !important;
          display: flex !important;
          align-items: flex-start !important;
          box-sizing: border-box !important;
        }
        :host([data-player-size="large"]) media-controller:not([mediaisfullscreen]):not(:fullscreen) media-volume-range,
        :host(:not([data-player-size="mini"]):not([data-player-size="medium"])) media-controller:not([mediaisfullscreen]):not(:fullscreen) media-volume-range {
          width: 100px !important;
          height: 11px !important;
          padding: 0 !important;
          border-radius: 5.5px !important;
          overflow: hidden !important;
          background: rgba(255, 255, 255, 0.25) !important;
          backdrop-filter: blur(8px) !important;
          border: none !important;
          box-shadow: none !important;
          --media-range-bar-color: #ffffff !important;
          --media-range-track-width: 100px !important;
          --media-range-track-height: 11px !important;
          --media-range-track-border-radius: 5.5px !important;
          --media-range-thumb-width: 0px !important;
          --media-range-thumb-opacity: 0 !important;
        }

        /* 4. FULLSCREEN MODE (All player sizes revert to full specs) */
        media-controller[mediaisfullscreen],
        media-controller:fullscreen {
          --base: 24px !important;
          --media-control-height: 48px !important;
          --media-font-size: 16px !important;
          --media-icon-height: 24px !important;
          font-size: 16px !important;
          cursor: default !important;
        }
        media-controller[mediaisfullscreen] video[slot="media"],
        media-controller[mediaisfullscreen] ::slotted(video),
        media-controller:fullscreen video[slot="media"],
        media-controller:fullscreen ::slotted(video) {
          pointer-events: auto !important;
          cursor: default !important;
        }
        media-controller[mediaisfullscreen] media-play-button,
        media-controller[mediaisfullscreen] media-play-button *,
        media-controller[mediaisfullscreen] media-play-button::part(button),
        media-controller[mediaisfullscreen] media-mute-button,
        media-controller[mediaisfullscreen] media-mute-button *,
        media-controller[mediaisfullscreen] media-mute-button::part(button),
        media-controller[mediaisfullscreen] media-fullscreen-button,
        media-controller[mediaisfullscreen] media-fullscreen-button *,
        media-controller[mediaisfullscreen] media-fullscreen-button::part(button),
        media-controller[mediaisfullscreen] media-time-range,
        media-controller[mediaisfullscreen] media-time-range *,
        media-controller[mediaisfullscreen] media-volume-range,
        media-controller[mediaisfullscreen] media-volume-range *,
        media-controller[mediaisfullscreen] button,
        media-controller[mediaisfullscreen] button *,
        media-controller[mediaisfullscreen] [role="button"],
        media-controller[mediaisfullscreen] [role="button"] *,
        media-controller:fullscreen media-play-button,
        media-controller:fullscreen media-play-button *,
        media-controller:fullscreen media-play-button::part(button),
        media-controller:fullscreen media-mute-button,
        media-controller:fullscreen media-mute-button *,
        media-controller:fullscreen media-mute-button::part(button),
        media-controller:fullscreen media-fullscreen-button,
        media-controller:fullscreen media-fullscreen-button *,
        media-controller:fullscreen media-fullscreen-button::part(button),
        media-controller:fullscreen media-time-range,
        media-controller:fullscreen media-time-range *,
        media-controller:fullscreen media-volume-range,
        media-controller:fullscreen media-volume-range *,
        media-controller:fullscreen button,
        media-controller:fullscreen button *,
        media-controller:fullscreen [role="button"],
        media-controller:fullscreen [role="button"] * {
          cursor: pointer !important;
        }
        media-controller[mediaisfullscreen] media-control-bar,
        media-controller:fullscreen media-control-bar {
          height: 48px !important;
          line-height: 48px !important;
          bottom: 24px !important;
          left: 24px !important;
          right: 24px !important;
          gap: 10px !important;
        }
        media-controller[mediaisfullscreen] media-time-range,
        media-controller:fullscreen media-time-range {
          height: 48px !important;
          --media-range-thumb-width: 24px !important;
          --media-range-thumb-height: 24px !important;
          --media-range-track-height: 4px !important;
          --media-range-bar-height: 4px !important;
        }
        media-controller[mediaisfullscreen] .media-volume-range-wrapper,
        media-controller:fullscreen .media-volume-range-wrapper {
          position: absolute !important;
          top: -100% !important;
          bottom: auto !important;
          left: 48px !important;
          width: 240px !important;
          height: 60px !important;
          padding: 0 !important;
          margin: 0 !important;
          background: transparent !important;
          border: none !important;
          box-shadow: none !important;
          display: block !important;
          transform-origin: center left !important;
        }
        media-controller[mediaisfullscreen] media-volume-range,
        media-controller:fullscreen media-volume-range {
          width: 240px !important;
          height: 24px !important;
          padding: 0 !important;
          border-radius: 6px !important;
          overflow: hidden !important;
          background: rgba(0, 0, 0, 0.3) !important;
          backdrop-filter: blur(10px) brightness(80%) !important;
          border: none !important;
          box-shadow: none !important;
          --media-range-bar-color: #ffffff !important;
          --media-range-track-width: 240px !important;
          --media-range-track-height: 24px !important;
          --media-range-track-border-radius: 6px !important;
          --media-range-thumb-width: 24px !important;
          --media-range-thumb-opacity: 0 !important;
        }
        media-controller[mediaisfullscreen] media-time-display,
        media-controller:fullscreen media-time-display {
          padding: 12px !important;
          font-size: 16px !important;
          border-radius: 8px !important;
        }
      `;
      player.shadowRoot.appendChild(st);
    }
    player.querySelectorAll('video').forEach(v => {
      try {
        v.disablePictureInPicture = true;
      } catch (e) {}
      v.setAttribute('disablepictureinpicture', '');
      v.setAttribute('controlslist', 'nodownload nopictureinpicture');
    });
    player.shadowRoot.querySelectorAll('media-play-button, media-fullscreen-button, media-mute-button, media-chrome-button, .media-button, media-time-range, media-volume-range').forEach(btn => {
      btn.setAttribute('notooltip', '');
      btn.style.setProperty('cursor', 'pointer', 'important');
      if (btn.shadowRoot) {
        const tt = btn.shadowRoot.querySelectorAll('media-tooltip, slot[name="tooltip"], [part~="tooltip"]');
        tt.forEach(el => el.style.setProperty('display', 'none', 'important'));
        if (!btn.shadowRoot.querySelector('#pointer-cursor-override')) {
          const ptrStyle = document.createElement('style');
          ptrStyle.id = 'pointer-cursor-override';
          ptrStyle.textContent = ':host, button, [part~="button"], svg, path { cursor: pointer !important; }';
          btn.shadowRoot.appendChild(ptrStyle);
        }
      }
    });
    if (player.shadowRoot) {
      player.shadowRoot.querySelectorAll('media-controller').forEach(ctrl => {
        ctrl.setAttribute('gesturesdisabled', '');
      });
      player.shadowRoot.querySelectorAll('media-gesture-receiver').forEach(mgr => {
        mgr.style.setProperty('display', 'none', 'important');
        mgr.style.setProperty('pointer-events', 'none', 'important');
      });
    }
    player.shadowRoot.querySelectorAll('media-pip-button, [part~="pip-button"]').forEach(btn => {
      btn.style.setProperty('display', 'none', 'important');
    });
  });
};

// Global listener: Sync fullscreen state to media-theme-sutro and body
document.addEventListener('fullscreenchange', () => {
  const isAnyFs = !!document.fullscreenElement;
  document.body.classList.toggle('is-in-fullscreen', isAnyFs);
  document.querySelectorAll('media-theme-sutro').forEach(player => {
    const isFs = !!(document.fullscreenElement && (
      document.fullscreenElement === player ||
      player.contains(document.fullscreenElement) ||
      (player.shadowRoot && player.shadowRoot.contains(document.fullscreenElement))
    ));
    if (isFs) {
      player.setAttribute('mediaisfullscreen', '');
    } else {
      player.removeAttribute('mediaisfullscreen');
    }
  });
});

// Global listener: Pause other media when one video starts playing
document.addEventListener('play', (e) => {
  if (e.target && e.target.tagName === 'VIDEO') {
    document.querySelectorAll('video').forEach(v => {
      if (v !== e.target && !v.paused) {
        v.pause();
      }
    });
    if (currentlyPlayingAudioId) {
      const otherEl = document.getElementById(`audio-el-${currentlyPlayingAudioId}`);
      if (otherEl) otherEl.pause();
      currentlyPlayingAudioId = null;
      lucide.createIcons();
    }
  }
}, true);

// AI Clipper flowchart workspace engine
const clipperNodeOffsets = {};

function isAiClipperProject(proj) {
  if (!proj) return false;
  const act = (proj.action || '').toLowerCase();
  const cat = (proj.category || '').toLowerCase();
  const name = (proj.workspace_name || '').toLowerCase();
  const isActClip = act.includes('ai_clip') || act.includes('clipper') || act.includes('yt_clip') || act.includes('trim');
  const isCatClip = cat.includes('01-ai-clips') || cat.includes('ai-clip') || cat.includes('trim');
  const hasClipFiles = (proj.files || []).some(f =>
    (f.category || '').toLowerCase().includes('01-ai-clips') ||
    (f.action || '').toLowerCase().includes('ai_clip') ||
    (f.action || '').toLowerCase().includes('yt_clip') ||
    (f.filename || '').toLowerCase().includes('virality') ||
    (f.filename || '').toLowerCase().includes('clip')
  );
  return isActClip || isCatClip || hasClipFiles;
}

const FLOW_SKY = "#a1a1aa";
const FLOW_TEAL = "#a1a1aa";
const FLOW_AMBER = "#f59e0b";
const FLOW_ROSE = "#f43f5e";
const FLOW_EMERALD = "#ffffff";

function flowMix(hue, pct, base = "#171717") {
  return `color-mix(in srgb, ${hue} ${pct}%, ${base})`;
}

window.resetClipperCanvasLayout = function () {
  for (const k in clipperNodeOffsets) {
    delete clipperNodeOffsets[k];
  }
  document.querySelectorAll('.clipper-flow-node').forEach(el => {
    el.style.transform = '';
  });
  drawClipperConnectors();
};

function initClipperDraggable(nodeEl) {
  if (!nodeEl) return;
  let isDragging = false;
  let startX = 0, startY = 0;
  let initialDx = 0, initialDy = 0;
  let hasMoved = false;

  nodeEl.addEventListener('pointerdown', (e) => {
    // Do not drag if currently in fullscreen
    if (document.fullscreenElement || nodeEl.hasAttribute('mediaisfullscreen') || nodeEl.querySelector('[mediaisfullscreen]')) {
      return;
    }

    // Only ignore interactive elements (buttons, links, form inputs, video player, or media control bar)
    const path = e.composedPath ? e.composedPath() : [e.target];
    const isInteractive = path.some(el => {
      if (!el || !el.tagName) return false;
      const tag = el.tagName.toLowerCase();
      if (tag === 'button' || tag === 'a' || tag === 'input' || tag === 'select' || tag === 'textarea' || tag === 'video') return true;
      if (tag.startsWith('media-')) return true;
      if (el.hasAttribute && el.hasAttribute('data-no-drag')) return true;
      if (el.classList && (el.classList.contains('caption-popover') || el.classList.contains('video-preview-wrapper') || el.classList.contains('glass-caption-popover'))) return true;
      return false;
    });
    if (isInteractive) return;

    e.preventDefault();
    isDragging = true;
    hasMoved = false;
    startX = e.clientX;
    startY = e.clientY;

    const currentOffset = clipperNodeOffsets[nodeEl.id] || { dx: 0, dy: 0 };
    initialDx = currentOffset.dx;
    initialDy = currentOffset.dy;

    try { nodeEl.setPointerCapture(e.pointerId); } catch (_) {}
    nodeEl.classList.add('z-30', 'shadow-2xl', 'cursor-grabbing');
  });

  nodeEl.addEventListener('pointermove', (e) => {
    if (!isDragging) return;
    const dist = Math.hypot(e.clientX - startX, e.clientY - startY);
    if (dist > 3) hasMoved = true;
    const dx = initialDx + (e.clientX - startX) / clipperZoom;
    const dy = initialDy + (e.clientY - startY) / clipperZoom;
    clipperNodeOffsets[nodeEl.id] = { dx, dy };
    nodeEl.style.transform = `translate(${dx}px, ${dy}px)`;
    requestAnimationFrame(drawClipperConnectors);
  });

  const endDrag = (e) => {
    if (!isDragging) return;
    isDragging = false;
    try { nodeEl.releasePointerCapture(e.pointerId); } catch (_) {}
    nodeEl.classList.remove('z-30', 'cursor-grabbing');
    if (hasMoved) {
      const killClick = (ce) => {
        ce.stopPropagation();
        ce.preventDefault();
      };
      window.addEventListener('click', killClick, { capture: true, once: true });
      setTimeout(() => window.removeEventListener('click', killClick, { capture: true }), 120);
    }
    drawClipperConnectors();
  };

  nodeEl.addEventListener('pointerup', endDrag);
  nodeEl.addEventListener('pointercancel', endDrag);
}

function drawClipperConnectors() {
  const svg = document.getElementById('clipperFlowSvg');
  const scrollCanvas = document.getElementById('clipperScrollCanvas');
  if (!svg || !scrollCanvas) return;

  const totalW = Math.max(scrollCanvas.scrollWidth, scrollCanvas.offsetWidth, 4000);
  const totalH = Math.max(scrollCanvas.scrollHeight, scrollCanvas.offsetHeight, 4000);
  svg.setAttribute('width', totalW);
  svg.setAttribute('height', totalH);
  svg.style.overflow = 'visible';

  // Clean SVG canvas
  svg.innerHTML = '';

  function getNodeBox(el) {
    const canvasRect = scrollCanvas.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    return {
      x: (r.left - canvasRect.left) / clipperZoom,
      y: (r.top - canvasRect.top) / clipperZoom,
      w: r.width / clipperZoom,
      h: r.height / clipperZoom
    };
  }

  function drawN8nConnection(elA, elB) {
    if (!elA || !elB) return;
    const boxA = getNodeBox(elA);
    const boxB = getNodeBox(elB);

    // Validation guard: only draw when cards are actively rendered with valid dimensions
    if (!boxA.w || !boxB.w || boxA.w < 50 || boxB.w < 50) return;
    if (boxA.x < 15 && boxB.x < 15) return;

    // Header level anchor for all cards (clean 18px offset from card top)
    const anchorA = boxA.y + 18;
    const anchorB = boxB.y + 18;

    // FIXED PORTS: Output is ALWAYS on the right edge of A, Input is ALWAYS on the left edge of B
    // Ports never switch to other sides of cards.
    const p1 = { x: boxA.x + boxA.w, y: anchorA };
    const p2 = { x: boxB.x, y: anchorB };

    const dx = p2.x - p1.x;
    let d;

    if (dx >= -10) {
      // Normal horizontal forward flow
      const k = Math.min(Math.max(dx * 0.52, 40), 220);
      d = `M ${p1.x} ${p1.y} C ${p1.x + k} ${p1.y}, ${p2.x - k} ${p2.y}, ${p2.x} ${p2.y}`;
    } else {
      // Opposite direction (user dragged target to the left / backward):
      // Smoothly loops out of A's right port and enters B's left port from behind, exactly like n8n
      const loopDist = Math.max(Math.abs(dx) * 0.45, 60);
      d = `M ${p1.x} ${p1.y} C ${p1.x + loopDist} ${p1.y}, ${p2.x - loopDist} ${p2.y}, ${p2.x} ${p2.y}`;
    }

    // Connection path with a clean hairline stroke.
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', d);
    path.setAttribute('fill', 'none');
    path.setAttribute('stroke', 'rgba(255, 255, 255, 0.28)');
    path.setAttribute('stroke-width', '1');
    path.setAttribute('stroke-linecap', 'round');
    path.setAttribute('stroke-opacity', '0.75');
    path.classList.add('flow-connector-path');
    svg.appendChild(path);
  }

  const triggerEl = document.getElementById('node-trigger');
  const pipelineEl = document.getElementById('node-pipeline-engine');
  const clipNodes = document.querySelectorAll('.clipper-branch-clip');

  if (triggerEl && pipelineEl) {
    drawN8nConnection(triggerEl, pipelineEl);
    clipNodes.forEach(cn => {
      drawN8nConnection(pipelineEl, cn);
    });
  } else if (triggerEl && clipNodes.length > 0) {
    clipNodes.forEach(cn => {
      drawN8nConnection(triggerEl, cn);
    });
  }
}

window.toggleClipCaption = function (idx, event) {
  if (event) {
    event.stopPropagation();
    event.preventDefault();
  }
  const popover = document.getElementById(`clip-caption-popover-${idx}`);
  const node = document.getElementById(`clip-node-${idx}`);
  if (!popover) return;
  const isOpen = popover.classList.contains('is-open');

  closeAllClipCaptions();

  if (!isOpen) {
    const trigger = node ? node.querySelector('.caption-trigger-row') : null;
    if (trigger && node) {
      let top = 0;
      let curr = trigger;
      let found = false;
      while (curr && curr !== node) {
        top += curr.offsetTop;
        curr = curr.offsetParent;
        if (curr === node) {
          found = true;
          break;
        }
      }
      if (!found) {
        const nodeRect = node.getBoundingClientRect();
        const triggerRect = trigger.getBoundingClientRect();
        const zoom = (typeof clipperZoom === 'number' && clipperZoom > 0) ? clipperZoom : 1;
        top = (triggerRect.top - nodeRect.top) / zoom;
      }
      const triggerCenterY = top + (trigger.offsetHeight / 2);
      popover.style.top = `${Math.round(triggerCenterY)}px`;
    }
    popover.classList.add('is-open');
    if (node) {
      node.classList.add('caption-open');
      node.style.zIndex = '45';
      const trigger = node.querySelector('.caption-trigger-row');
      if (trigger) trigger.classList.add('is-open');
    }
    lucide.createIcons({ root: popover });
  }
};

window.closeClipCaption = function (idx) {
  const popover = document.getElementById(`clip-caption-popover-${idx}`);
  const node = document.getElementById(`clip-node-${idx}`);
  if (popover) popover.classList.remove('is-open');
  if (node) {
    node.classList.remove('caption-open');
    node.style.zIndex = '';
    const trigger = node.querySelector('.caption-trigger-row');
    if (trigger) trigger.classList.remove('is-open');
  }
};

window.closeAllClipCaptions = function () {
  document.querySelectorAll('.glass-caption-popover.is-open').forEach(p => {
    p.classList.remove('is-open');
  });
  document.querySelectorAll('.clipper-branch-clip.caption-open').forEach(n => {
    n.classList.remove('caption-open');
    n.style.zIndex = '';
    const trigger = n.querySelector('.caption-trigger-row');
    if (trigger) trigger.classList.remove('is-open');
  });
};

window.copyClipCaption = function (idx, btn, event) {
  if (event) {
    event.stopPropagation();
    event.preventDefault();
  }
  const file = clipperFilesCache && clipperFilesCache[idx];
  if (!file || !file.caption) return;
  navigator.clipboard.writeText(file.caption.trim()).then(() => {
    if (!btn) return;
    const originalHtml = btn.innerHTML;
    btn.innerHTML = '<i data-lucide="check" class="w-3.5 h-3.5 text-emerald-400"></i>';
    lucide.createIcons({ root: btn });
    setTimeout(() => {
      btn.innerHTML = originalHtml;
      lucide.createIcons({ root: btn });
    }, 1500);
  });
};

// Backward-compatibility aliases
window.openMorphingCaptionModal = function (idx) {
  toggleClipCaption(idx);
};
window.closeMorphingCaptionModal = function () {
  closeAllClipCaptions();
};

document.addEventListener('pointerdown', function (e) {
  if (!e.target.closest('.glass-caption-popover') && !e.target.closest('.caption-trigger-row')) {
    closeAllClipCaptions();
  }
});

document.addEventListener('keydown', function (e) {
  if (e.key === 'Escape') {
    closeAllClipCaptions();
  }
});

function renderClipperWorkflow(proj) {
  const nodesWrapper = document.getElementById('clipperCanvasNodesWrapper');
  if (!nodesWrapper) return;
  nodesWrapper.innerHTML = '';

  const files = proj.files || [];
  clipperFilesCache = files;

  const sourceTitle = proj.source_title ? escapeHtml(proj.source_title) : (files[0] && files[0].title ? escapeHtml(files[0].title) : 'Source Video');
  const titleLower = String(proj.source_title || proj.workspace_name || '').toLowerCase();

  // Source Channel / Creator extraction (pure factual extraction)
  let rawChannel = proj.channel || proj.source_channel || proj.uploader || '';
  if (!rawChannel) {
    rawChannel = 'YouTube';
  }
  const sourceChannel = escapeHtml(rawChannel);

  // Source URL extraction: NEVER accept local paths or /media-vault/ as valid YouTube link
  let rawUrl = '';
  if (proj.source_url && (proj.source_url.startsWith('http://') || proj.source_url.startsWith('https://'))) {
    rawUrl = proj.source_url;
  } else if (proj.url && (proj.url.startsWith('http://') || proj.url.startsWith('https://'))) {
    rawUrl = proj.url;
  }

  let displayUrl = rawUrl;
  try {
    const parsed = new URL(rawUrl);
    displayUrl = parsed.hostname.replace(/^www\./, '') + (parsed.pathname !== '/' ? parsed.pathname : '') + parsed.search;
  } catch (e) {
    displayUrl = rawUrl.replace(/^https?:\/\/(www\.)?/, '');
  }
  if (displayUrl.length > 26) {
    displayUrl = displayUrl.substring(0, 24) + '...';
  }

  const sourceLinkHtml = rawUrl
    ? `<a href="${encodeURI(rawUrl)}" target="_blank" rel="noopener noreferrer" class="block text-[11px] font-medium text-white hover:text-white leading-tight truncate mt-0.5 hover:underline" title="${escapeHtml(rawUrl)}" data-no-drag="true">
            ${escapeHtml(displayUrl)}
          </a>`
    : `<span class="block text-[11px] font-medium text-zinc-500 leading-tight truncate mt-0.5">Source unavailable</span>`;

  // NODE 1: Trigger Node / Source Input (Exact matching dimensions: w-[224px] h-[238px])
  const triggerNode = document.createElement('div');
  triggerNode.id = 'node-trigger';
  triggerNode.className = 'clipper-flow-node flex flex-col items-start w-[224px] shrink-0 cursor-grab active:cursor-grabbing select-none';
  triggerNode.setAttribute('data-node-id', 'node-trigger');

  triggerNode.innerHTML = `
    <div class="w-full h-[238px] rounded-[14px] bg-[#171717] border border-white/[0.08] shadow-[0_6px_18px_rgba(0,0,0,0.5)] overflow-hidden flex flex-col justify-between">
      <div class="flex items-center justify-between px-3.5 py-2.5 border-b border-white/[0.06] bg-white/[0.02] shrink-0">
        <span class="text-[10px] font-semibold text-zinc-300 font-mono">Source</span>
        <span class="text-[9.5px] font-mono text-zinc-400 font-medium">Ingested</span>
      </div>
      <div class="divide-y divide-white/[0.04] flex-1 flex flex-col justify-between">
        <div class="px-3.5 py-2 flex flex-col justify-center flex-1">
          <span class="block text-[9px] text-zinc-500 font-mono leading-tight">Input Video</span>
          <span class="block text-[11px] font-medium text-white leading-tight truncate mt-0.5" title="${sourceTitle}">${sourceTitle}</span>
        </div>
        <div class="px-3.5 py-2 flex flex-col justify-center flex-1">
          <span class="block text-[9px] text-zinc-500 font-mono leading-tight">Channel / Source</span>
          <span class="block text-[11px] font-medium text-white leading-tight truncate mt-0.5" title="${sourceChannel}">${sourceChannel}</span>
        </div>
        <div class="px-3.5 py-2 flex flex-col justify-center flex-1">
          <span class="block text-[9px] text-zinc-500 font-mono leading-tight">Link YouTube</span>
          ${sourceLinkHtml}
        </div>
        <div class="px-3.5 py-2.5 flex flex-col justify-center flex-1">
          <span class="block text-[9px] text-zinc-500 font-mono leading-tight">Total Clips</span>
          <span class="block text-[11px] font-medium text-white leading-tight mt-0.5">${files.length} Clips</span>
        </div>
      </div>
    </div>
  `;
  initClipperDraggable(triggerNode);
  nodesWrapper.appendChild(triggerNode);

  // NODE 2: Pipeline Engine Node (Exact matching dimensions: w-[224px] h-[238px])
  const pipelineNode = document.createElement('div');
  pipelineNode.id = 'node-pipeline-engine';
  pipelineNode.className = 'clipper-flow-node flex flex-col items-start w-[224px] shrink-0 cursor-grab active:cursor-grabbing select-none';
  pipelineNode.setAttribute('data-node-id', 'node-pipeline-engine');

  // Aspect ratio extraction (real data from project or files, never fake face tracking)
  let detectedRatio = proj.aspect_ratio || proj.crop_ratio || '';
  if (!detectedRatio && files && files.length > 0) {
    detectedRatio = files[0].aspect_ratio || files[0].ratio || '';
  }
  if (!detectedRatio) {
    detectedRatio = window.selectedRatio || '9:16';
  }
  detectedRatio = String(detectedRatio).trim();

  const isTrimProject = (proj.action === 'type_yt_clip' || proj.action === 'manual_clip' || (proj.category || '').includes('trim'));
  const transcribeProvider = proj.transcribe_provider || 'Groq Cloud Whisper';
  const microSteps = isTrimProject ? [
    { label: 'Download', sub: 'yt-dlp' },
    { label: 'Engine', sub: 'Video Trimmer' },
    { label: 'Crop Ratio', sub: detectedRatio || 'Original' },
    { label: 'Segments', sub: `${files.length} Clips` }
  ] : [
    { label: 'Download', sub: 'yt-dlp' },
    { label: 'Transcribe', sub: transcribeProvider },
    { label: 'Virality LLM', sub: 'AI Ranking' },
    { label: 'Crop Ratio', sub: detectedRatio }
  ];

  const checkmarkHtml = `
    <span class="text-emerald-400 shrink-0" title="Complete">
      <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/>
      </svg>
    </span>
  `;

  const stepsHtml = microSteps.map((s, i) => `
    <div class="flex items-center justify-between px-3.5 py-2.5 flex-1 ${i < microSteps.length - 1 ? 'border-b border-white/[0.04]' : ''}">
      <div class="min-w-0 flex-1">
        <span class="block text-[9px] text-zinc-500 font-mono leading-tight">${s.label}</span>
        <span class="block text-[11px] font-medium text-white leading-tight mt-0.5">${s.sub}</span>
      </div>
      ${checkmarkHtml}
    </div>
  `).join('');

  pipelineNode.innerHTML = `
    <div class="w-full h-[238px] rounded-[14px] bg-[#171717] border border-white/[0.08] shadow-[0_6px_18px_rgba(0,0,0,0.5)] overflow-hidden flex flex-col justify-between">
      <div class="flex items-center justify-between px-3.5 py-2.5 border-b border-white/[0.06] bg-white/[0.02] shrink-0">
        <span class="text-[10px] font-semibold text-zinc-300 font-mono">${isTrimProject ? "Trim Pipeline" : "AI Pipeline"}</span>
        <span class="text-[9.5px] font-mono text-zinc-400 font-medium">Task</span>
      </div>
      <div class="divide-y divide-white/[0.04] flex-1 flex flex-col justify-between">
        ${stepsHtml}
      </div>
    </div>
  `;
  initClipperDraggable(pipelineNode);
  nodesWrapper.appendChild(pipelineNode);

  // NODE 3+: Branching Output Clip Cards (Vertical Column)
  const clipsCol = document.createElement('div');
  clipsCol.id = 'clipperBranchingClipsWrapper';
  clipsCol.className = 'flex flex-col gap-6 shrink-0 ml-20 sm:ml-28';

  if (files.length === 0) {
    const emptyNode = document.createElement('div');
    emptyNode.className = 'clipper-flow-node flex flex-col items-start w-[245px] shrink-0';
    emptyNode.innerHTML = `
      <div class="w-full rounded-[14px] bg-[#171717] border border-white/[0.08] p-4 text-center text-[11px] text-zinc-400">
        No clips have finished rendering yet.
      </div>
    `;
    clipsCol.appendChild(emptyNode);
  } else {
    files.forEach((file, idx) => {
      const clipNode = document.createElement('div');
      clipNode.id = `clip-node-${idx}`;
      clipNode.className = 'clipper-flow-node clipper-branch-clip relative flex flex-col items-start w-[245px] shrink-0 cursor-grab active:cursor-grabbing select-none';
      clipNode.setAttribute('data-node-id', `clip-node-${idx}`);

      const score = file.score || 90;
      const rawMediaUrl = file.url || (file.relative_path ? `/media-vault/${file.relative_path.replace(/\\/g, '/')}` : '#');
      const mediaUrl = rawMediaUrl !== '#' ? encodeURI(rawMediaUrl) : '#';
      const downloadUrl = file.download_url ? encodeURI(file.download_url) : mediaUrl;

      const hasCaption = !isTrimProject && Boolean(file.caption && file.caption.trim());
      const captionSnippet = hasCaption ? escapeHtml(file.caption.trim()) : '';

      const captionTrigger = hasCaption ? `
        <div class="caption-trigger-row group/caption flex items-center justify-between gap-2 px-2.5 py-1.5 rounded-lg mx-1 border border-transparent hover:border-white/[0.06] hover:bg-white/[0.04] transition cursor-pointer" onclick="toggleClipCaption(${idx}, event)" data-no-drag="true">
          <p class="text-[10px] text-zinc-400 group-hover/caption:text-zinc-200 leading-normal truncate flex-1 min-w-0 transition-colors select-none">${captionSnippet}</p>
          <button type="button" onclick="copyClipCaption(${idx}, this, event)" class="caption-copy-btn p-1 rounded-md text-zinc-400 hover:text-white hover:bg-white/[0.08] transition flex items-center justify-center cursor-pointer shrink-0" aria-label="Copy caption">
            <i data-lucide="copy" class="w-3.5 h-3.5"></i>
          </button>
        </div>
      ` : '';

      const captionPopover = hasCaption ? `
        <div id="clip-caption-popover-${idx}" class="glass-caption-popover absolute left-[calc(100%+12px)] z-50 w-[280px] rounded-[14px] bg-[#171717] border border-white/[0.08] shadow-[0_16px_36px_rgba(0,0,0,0.75)] text-left overflow-hidden" data-no-drag="true" onclick="event.stopPropagation()">
          <div class="max-h-[260px] overflow-y-auto pr-0.5 text-[11.5px] leading-[1.6] text-zinc-200 font-sans select-all text-left whitespace-pre-line break-words">${escapeHtml(file.caption.trim())}</div>
        </div>
      ` : '';

      clipNode.innerHTML = `
        ${captionPopover}
        <div class="w-full rounded-[14px] bg-[#171717] border border-white/[0.08] shadow-[0_8px_24px_rgba(0,0,0,0.6)] overflow-hidden flex flex-col">
          <!-- Video Preview Area (Starts directly at top of card, no header bar above) -->
          <div class="relative bg-black w-full overflow-hidden border-b border-white/[0.06]" style="aspect-ratio: 9/16; max-height: 230px;">
            <media-theme-sutro style="width:100%; height:100%;" data-player-size="mini" disabled>
              <video
                slot="media"
                preload="metadata"
                playsinline
                disablepictureinpicture
                controlslist="nodownload nopictureinpicture"
                src="${mediaUrl}"
                style="width:100%; height:100%; object-fit:contain; pointer-events:none;">
              </video>
            </media-theme-sutro>
          </div>

                        <div class="px-3 pt-2.5 pb-1">
            <h4 class="text-[11px] font-semibold text-white line-clamp-1 leading-snug">${escapeHtml(file.title || `Clip #${idx + 1}`)}</h4>
          </div>

          ${captionTrigger}

          <!-- Bottom Bar: Info on Left, Balanced Download Button on Right -->
          <div class="flex items-center justify-between gap-3 px-3 pb-3 pt-2 border-t border-white/[0.04]">
            <div class="min-w-0 flex flex-col justify-center">
              ${isTrimProject ? `
                <span class="text-[11px] font-semibold text-white tracking-tight leading-tight">Clip #${idx + 1}</span>
                <span class="text-[10px] font-mono text-zinc-400 leading-tight mt-0.5">${escapeHtml(file.start_time || '00:00')} - ${escapeHtml(file.end_time || '00:30')}</span>
              ` : `
                <span class="text-[11px] font-semibold text-white tracking-tight leading-tight">Score ${score}%</span>
                <span class="text-[10px] font-mono text-zinc-400 leading-tight mt-0.5">Clip #${idx + 1}</span>
              `}
            </div>
            <a href="${downloadUrl}" download="${escapeHtml(file.filename || `clip_${idx + 1}.mp4`)}" class="t-btn t-btn-secondary !h-7 px-2.5 text-[10.5px] font-medium flex items-center justify-center gap-1.5 shrink-0 cursor-pointer" data-no-drag="true" aria-label="Download Clip">
              <span>Download</span>
              <i data-lucide="download" class="w-3.5 h-3.5"></i>
            </a>
          </div>
        </div>
      `;
      const clipVid = clipNode.querySelector('video');
      if (clipVid) {
        try { clipVid.disablePictureInPicture = true; } catch (e) {}
        // Auto-recovery if browser momentarily drops source
        clipVid.addEventListener('error', function () {
          const el = this;
          if (el.dataset.hasRecovered) return;
          el.dataset.hasRecovered = 'true';
          setTimeout(() => {
            const prev = el.src;
            el.src = '';
            el.src = prev;
            el.load();
          }, 400);
        });
      }
      initClipperDraggable(clipNode);
      clipsCol.appendChild(clipNode);
    });
  }
  nodesWrapper.appendChild(clipsCol);

  lucide.createIcons();

  setTimeout(compactSutroPlayers, 30);
  setTimeout(compactSutroPlayers, 150);
  setTimeout(compactSutroPlayers, 500);

  setTimeout(drawClipperConnectors, 40);
  setTimeout(drawClipperConnectors, 200);
}

// Canvas pan + zoom via CSS transform (translate + scale)
let clipperPanX = 0, clipperPanY = 0, clipperZoom = 1;

(function initClipperCanvasControls() {
  let viewport = null;
  let scrollCanvas = null;
  let isPanning = false;
  let panStartX = 0, panStartY = 0;
  let panOriginX = 0, panOriginY = 0;

  function getRefs() {
    if (!viewport) viewport = document.getElementById('clipperCanvasViewport');
    if (!scrollCanvas) scrollCanvas = document.getElementById('clipperScrollCanvas');
    return viewport;
  }

  function isVisible() {
    const vp = getRefs();
    return vp && vp.style.display !== 'none' && vp.offsetWidth > 0;
  }

  function applyTransform() {
    if (!scrollCanvas) return;
    scrollCanvas.style.transform = `translate(${clipperPanX}px, ${clipperPanY}px) scale(${clipperZoom})`;
    scrollCanvas.style.transformOrigin = '0 0';
    const label = document.getElementById('clipperZoomLabel');
    if (label) label.innerText = Math.round(clipperZoom * 100) + '%';
  }

  // Pan: click empty canvas → cursor becomes hand → drag to move
  document.addEventListener('pointerdown', function (e) {
    if (!isVisible()) return;
    if (!viewport.contains(e.target)) return;
    if (e.target.closest('.clipper-flow-node, button, a, video, media-theme-sutro, input, select, textarea, [data-no-drag]')) return;
    isPanning = true;
    panStartX = e.clientX;
    panStartY = e.clientY;
    panOriginX = clipperPanX;
    panOriginY = clipperPanY;
    viewport.classList.add('is-panning');
    e.preventDefault();
  });

  // Spotlight Tracking
  let spotlightRaf = null;

  document.addEventListener('pointermove', function (e) {
    if (!isVisible()) return;
    const vp = getRefs();

    // Spotlight cursor position tracking
    if (vp) {
      const rect = vp.getBoundingClientRect();
      if (
        e.clientX >= rect.left &&
        e.clientX <= rect.right &&
        e.clientY >= rect.top &&
        e.clientY <= rect.bottom
      ) {
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;
        if (spotlightRaf) cancelAnimationFrame(spotlightRaf);
        spotlightRaf = requestAnimationFrame(function () {
          vp.style.setProperty('--mouse-x', mx + 'px');
          vp.style.setProperty('--mouse-y', my + 'px');
          vp.style.setProperty('--hero-spotlight-opacity', '1');
        });
      } else {
        vp.style.setProperty('--hero-spotlight-opacity', '0');
      }
    }

    if (!isPanning) return;
    clipperPanX = panOriginX + (e.clientX - panStartX);
    clipperPanY = panOriginY + (e.clientY - panStartY);
    applyTransform();
  });

  document.addEventListener('pointerleave', function () {
    const vp = getRefs();
    if (vp) vp.style.setProperty('--hero-spotlight-opacity', '0');
  });

  document.addEventListener('pointerup', function () {
    if (!isPanning) return;
    isPanning = false;
    if (viewport) viewport.classList.remove('is-panning');
  });

  // Zoom: Ctrl+scroll or pinch: zooms toward cursor position
  document.addEventListener('wheel', function (e) {
    if (!isVisible()) return;
    if (!viewport.contains(e.target)) return;
    if (!e.ctrlKey && !e.metaKey) return;
    e.preventDefault();

    const rect = viewport.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;

    const oldZoom = clipperZoom;
    const delta = e.deltaY > 0 ? -0.08 : 0.08;
    clipperZoom = Math.min(Math.max(clipperZoom + delta, 0.3), 2.5);

    // Adjust pan so zoom centers on cursor
    const ratio = clipperZoom / oldZoom;
    clipperPanX = mx - ratio * (mx - clipperPanX);
    clipperPanY = my - ratio * (my - clipperPanY);

    applyTransform();
    setTimeout(drawClipperConnectors, 20);
  }, { passive: false });

  window.clipperZoomIn = function () {
    getRefs();
    const rect = viewport.getBoundingClientRect();
    const cx = rect.width / 2, cy = rect.height / 2;
    const oldZoom = clipperZoom;
    clipperZoom = Math.min(clipperZoom + 0.15, 2.5);
    const ratio = clipperZoom / oldZoom;
    clipperPanX = cx - ratio * (cx - clipperPanX);
    clipperPanY = cy - ratio * (cy - clipperPanY);
    applyTransform();
    setTimeout(drawClipperConnectors, 20);
  };
  window.clipperZoomOut = function () {
    getRefs();
    const rect = viewport.getBoundingClientRect();
    const cx = rect.width / 2, cy = rect.height / 2;
    const oldZoom = clipperZoom;
    clipperZoom = Math.max(clipperZoom - 0.15, 0.3);
    const ratio = clipperZoom / oldZoom;
    clipperPanX = cx - ratio * (cx - clipperPanX);
    clipperPanY = cy - ratio * (cy - clipperPanY);
    applyTransform();
    setTimeout(drawClipperConnectors, 20);
  };
  window.clipperZoomReset = function () {
    getRefs();
    clipperZoom = 1;
    clipperPanX = 0;
    clipperPanY = 0;
    applyTransform();
    setTimeout(drawClipperConnectors, 20);
  };
})();

window.currentVaultMediaFilter = 'all';

window.updateVaultFilterCounters = function () {
  const grid = document.getElementById('projectFilesGrid');
  if (!grid) return;
  const allCards = grid.querySelectorAll('[data-media-type]');
  let landscapeCount = 0;
  let portraitCount = 0;
  let squareCount = 0;
  allCards.forEach(c => {
    const type = c.getAttribute('data-media-type');
    if (type === 'portrait') portraitCount++;
    else if (type === 'square') squareCount++;
    else landscapeCount++;
  });
  const cAll = document.getElementById('filterCountAll');
  const cLand = document.getElementById('filterCountLandscape');
  const cPort = document.getElementById('filterCountPortrait');
  const cSquare = document.getElementById('filterCountSquare');
  if (cAll) cAll.innerText = allCards.length;
  if (cLand) cLand.innerText = landscapeCount;
  if (cPort) cPort.innerText = portraitCount;
  if (cSquare) cSquare.innerText = squareCount;

  requestAnimationFrame(() => {
    setVaultMediaFilter(window.currentVaultMediaFilter || 'all', false);
  });
};

window.setVaultMediaFilter = function (filterType, immediate = false) {
  window.currentVaultMediaFilter = filterType;
  const filterGroup = document.getElementById('vaultMediaFilterGroup');
  const pill = document.getElementById('vaultMediaFilterPill');

  if (filterGroup) {
    const tabs = filterGroup.querySelectorAll('.t-tab');
    let activeTab = null;
    tabs.forEach(btn => {
      const isSelected = btn.id === `btn-vault-filter-${filterType}`;
      btn.setAttribute('aria-selected', isSelected ? 'true' : 'false');
      btn.classList.toggle('active', isSelected);
      if (isSelected) activeTab = btn;
    });

    if (activeTab && pill) {
      if (immediate) {
        pill.style.transition = 'none';
        pill.style.transform = `translateX(${activeTab.offsetLeft}px)`;
        pill.style.width = `${activeTab.offsetWidth}px`;
        void pill.offsetHeight;
        pill.style.transition = '';
      } else {
        pill.style.transform = `translateX(${activeTab.offsetLeft}px)`;
        pill.style.width = `${activeTab.offsetWidth}px`;
      }
    }
  }

  const grid = document.getElementById('projectFilesGrid');
  if (!grid) return;
  const cards = grid.querySelectorAll('[data-media-type]');
  let visible = 0;
  cards.forEach(card => {
    const type = card.getAttribute('data-media-type') || 'landscape';
    if (filterType === 'all' || type === filterType) {
      card.classList.remove('hidden');
      visible++;
    } else {
      card.classList.add('hidden');
    }
  });
  const visibleCountEl = document.getElementById('vaultVisibleFileCount');
  if (visibleCountEl) {
    visibleCountEl.innerText = `${visible} files shown`;
  }
};

window.addEventListener('resize', () => {
  if (typeof setVaultMediaFilter === 'function') {
    const group = document.getElementById('vaultMediaFilterGroup');
    if (group && !group.closest('.hidden')) {
      setVaultMediaFilter(window.currentVaultMediaFilter || 'all', true);
    }
  }
});

function renderProjectFiles(proj) {
  const grid = document.getElementById('projectFilesGrid');
  const emptyState = document.getElementById('projectFilesEmptyState');
  if (!grid) return;
  grid.innerHTML = '';

  const files = proj.files || [];
  if (files.length === 0) {
    if (emptyState) emptyState.classList.remove('hidden');
    updateVaultFilterCounters();
    return;
  }
  if (emptyState) emptyState.classList.add('hidden');

  const isPortraitWorkspace = proj.platform === 'tiktok' || proj.platform === 'instagram' ||
    (proj.workspace_name || '').toLowerCase().includes('tiktok') ||
    (proj.workspace_name || '').toLowerCase().includes('reels') ||
    (proj.workspace_name || '').toLowerCase().includes('short');

  const waveformHeights = [20, 45, 75, 30, 85, 55, 95, 70, 40, 90, 100, 65, 45, 80, 60, 35, 75, 50, 25, 15];

  files.forEach(file => {
    const isAud = file.type === 'audio' || (file.filename || '').endsWith('.mp3');
    const storedRatio = ratioMetaFromValue(file.aspect_ratio) || ratioMetaFromFilename(file.filename);
    const guessPortrait = isPortraitWorkspace || (file.quality && file.quality.includes('vertical')) ||
      (file.filename && (file.filename.includes('Reels') || file.filename.includes('Shorts')));
    const mediaMeta = storedRatio || {
      label: guessPortrait ? '9:16 Portrait' : '16:9 Landscape',
      kind: guessPortrait ? 'portrait' : 'landscape',
      icon: guessPortrait ? 'smartphone' : 'tv',
    };
    const fSize = formatBytes(file.file_size);
    const rawMediaUrl = file.url || (file.relative_path ? `/media-vault/${file.relative_path.replace(/\\/g, '/')}` : '#');
    const mediaUrl = rawMediaUrl !== '#' ? encodeURI(rawMediaUrl) : '#';
    const durStr = formatClipDuration(file);
    const dateStr = formatSavedDate(file.created_at || proj.created_at);

    const card = document.createElement('div');
    card.id = `vault-card-${file.id}`;
    card.className = 'rounded-2xl bg-[#171717] border border-white/[0.08] shadow-[0_4px_20px_-2px_rgba(0,0,0,0.5)] overflow-hidden flex flex-col justify-between group';
    card.setAttribute('data-media-type', mediaMeta.kind);

    let mediaPreviewHtml = '';
    if (isAud) {
      const waveformBarsHtml = waveformHeights.map(h => `<span class="waveform-bar w-[3px] rounded-full bg-zinc-600/70" style="height: ${h}%;"></span>`).join('');
      mediaPreviewHtml = `
        <div class="audio-card-showcase relative bg-[#121212] border-b border-white/[0.06] p-5 flex flex-col items-center justify-center overflow-hidden select-none">
          <div class="absolute inset-0 bg-radial from-white/[0.07] via-transparent to-transparent pointer-events-none"></div>

          <div class="absolute top-2.5 right-2.5 flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-white/[0.04] border border-white/10 text-[10px] font-mono text-zinc-400">
            <span class="w-1.5 h-1.5 rounded-full bg-white"></span>
            <span>320 KBPS MP3</span>
          </div>

          <!-- Vinyl Disc Graphic -->
          <div class="relative my-2 flex items-center justify-center">
            <div id="vinyl-disc-${file.id}" class="vinyl-disc w-20 h-20 rounded-full bg-[#0a0a0a] border border-zinc-700/60 shadow-[0_8px_25px_rgba(0,0,0,0.8)] relative flex items-center justify-center transition-transform">
              <div class="absolute inset-1.5 rounded-full border border-white/[0.06]"></div>
              <div class="absolute inset-3 rounded-full border border-white/[0.04]"></div>
              <div class="absolute inset-4.5 rounded-full border border-white/[0.05]"></div>
              <div class="w-7 h-7 rounded-full bg-zinc-800 border border-white/20 flex items-center justify-center shadow-inner">
                <div class="w-2 h-2 rounded-full bg-[#0a0a0a] border border-white/40"></div>
              </div>
            </div>
          </div>

          <!-- Waveform Visualizer -->
          <div id="waveform-bars-${file.id}" class="waveform-bars flex items-end justify-center gap-[3px] h-6 w-full max-w-[200px] mt-1 mb-1 px-2">
            ${waveformBarsHtml}
          </div>

          <!-- Custom Player Controls -->
          <div class="w-full mt-3 pt-3 border-t border-white/[0.06] space-y-2">
            <audio id="audio-el-${file.id}" src="${mediaUrl}" preload="metadata" class="hidden"></audio>

            <!-- Scrubber Timeline -->
            <div class="flex items-center gap-2 text-[11px] font-mono text-zinc-400">
              <span id="audio-time-${file.id}">0:00</span>
              <div 
                class="relative flex-1 h-1.5 rounded-full bg-white/10 hover:bg-white/20 transition cursor-pointer overflow-hidden group/scrubber" 
                onclick="seekCustomAudio(event, '${file.id}')"
                title="Seek">
                <div id="audio-progress-${file.id}" class="h-full bg-white rounded-full w-0 transition-[width] duration-75"></div>
              </div>
              <span id="audio-dur-${file.id}">--:--</span>
            </div>

            <!-- Play/Pause & Status Row -->
            <div class="flex items-center justify-between pt-0.5">
              <div class="flex items-center gap-2">
                <button 
                  type="button" 
                  id="audio-play-btn-${file.id}" 
                  onclick="toggleCustomAudioPlay('${file.id}')" 
                  class="w-7 h-7 rounded-full bg-white text-black hover:bg-zinc-200 active:scale-95 transition-all flex items-center justify-center shadow cursor-pointer"
                  title="Play / Pause">
                  <i data-lucide="play" class="w-3.5 h-3.5 ml-0.5"></i>
                </button>
                <span class="text-[11px] font-mono text-zinc-400" id="audio-status-${file.id}">Audio Track</span>
              </div>

              <button 
                type="button" 
                onclick="toggleCustomAudioMute('${file.id}')" 
                id="audio-mute-btn-${file.id}"
                class="p-1 rounded-md text-zinc-400 hover:text-white hover:bg-white/[0.06] transition cursor-pointer" 
                title="Mute / Unmute">
                <i data-lucide="volume-2" class="w-3.5 h-3.5"></i>
              </button>
            </div>
          </div>
        </div>
      `;
    } else {
      mediaPreviewHtml = `
        <div class="video-preview-wrapper relative bg-[#09090b] w-full overflow-hidden border-b border-white/[0.06] flex items-center justify-center ${ratioAspectClass(mediaMeta)} ${mediaMeta.kind === 'landscape' ? 'max-h-[520px]' : 'max-h-[500px]'}" style="aspect-ratio: ${ratioAspectStyle(mediaMeta)}" data-file-id="${file.id}">
          <div class="ambient-glow absolute inset-0 opacity-15 pointer-events-none filter blur-2xl scale-125 bg-gradient-to-t from-white/10 via-white/5 to-transparent"></div>

          <div class="ratio-pill absolute top-2.5 left-2.5 z-20 flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-black/60 backdrop-blur-md border border-white/10 text-[10px] font-mono text-zinc-300 pointer-events-none">
            <i data-lucide="${mediaMeta.icon}" class="w-3 h-3 ${mediaMeta.kind === 'landscape' ? 'text-zinc-400' : 'text-white'}"></i>
            <span class="ratio-text">${mediaMeta.label}</span>
          </div>

          <media-theme-sutro style="width:100%; height:100%;" data-player-size="medium">
            <video 
              slot="media"
              preload="metadata" 
              playsinline 
              disablepictureinpicture
              controlslist="nodownload nopictureinpicture"
              class="w-full h-full object-contain" 
              src="${mediaUrl}" 
              onloadedmetadata="handleVaultVideoMetadata(this, '${file.id}')">
            </video>
          </media-theme-sutro>
        </div>
      `;
    }

    card.innerHTML = `
      ${mediaPreviewHtml}
      <div class="p-4 flex-1 flex flex-col justify-between space-y-3">
        <div>
          <h4 class="text-xs sm:text-sm font-semibold font-sans text-white line-clamp-2 leading-snug mb-1" title="${escapeHtml(file.title || file.filename)}">
            ${escapeHtml(file.title || file.filename)}
          </h4>
          <div class="flex items-center gap-2 text-[11px] text-zinc-400 font-mono">
            <span>${fSize}</span>
            ${file.quality ? `<span>• ${file.quality}p</span>` : ''}
            ${durStr ? `<span>• ${durStr}</span>` : ''}
          </div>
        </div>

        <!-- Balanced action footer with proportional button sizing -->
        <div class="flex items-center justify-between pt-2.5 border-t border-white/[0.06]">
          <span class="text-[10.5px] font-mono text-zinc-500">${dateStr}</span>
          <div class="flex items-center gap-2">
            <a href="${mediaUrl}" download="${escapeHtml(file.filename)}" class="h-8 px-4 rounded-xl bg-white hover:bg-zinc-200 text-black text-xs font-semibold font-sans flex items-center gap-1.5 transition cursor-pointer shadow-sm" title="Download File">
              <i data-lucide="download" class="w-3.5 h-3.5"></i>
              <span>Download</span>
            </a>
            <button type="button" onclick="confirmDeleteVaultItem('${file.id}', '${escapeQuotes(file.title || file.filename)}', '${escapeQuotes(file.file_path)}')" class="w-8 h-8 rounded-xl bg-white/[0.04] hover:bg-red-500/15 border border-white/[0.08] text-zinc-400 hover:text-red-400 flex items-center justify-center transition cursor-pointer" title="Delete File">
              <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
            </button>
          </div>
        </div>
      </div>
    `;

    grid.appendChild(card);
    if (isAud) {
      setTimeout(() => initAudioEvents(file.id), 20);
    }
  });

  updateVaultFilterCounters();
  setVaultMediaFilter(window.currentVaultMediaFilter || 'all');

  lucide.createIcons();
  setTimeout(compactSutroPlayers, 30);
  setTimeout(compactSutroPlayers, 150);
  setTimeout(compactSutroPlayers, 500);
}

function toggleProjectDrawer(projectId) {
  openProjectPage(projectId);
}

function promptRenameWorkspace(projectId, currentName) {
  const modal = document.getElementById('renameWorkspaceModal');
  const input = document.getElementById('renameWsInput');
  const targetId = document.getElementById('renameWsTargetId');
  if (!modal || !input || !targetId) return;

  targetId.value = projectId;
  input.value = currentName;
  modal.classList.remove('hidden');
  setTimeout(() => {
    input.focus();
    const len = input.value.length;
    input.setSelectionRange(len, len);
  }, 50);
  lucide.createIcons();
}

function closeRenameModal() {
  const modal = document.getElementById('renameWorkspaceModal');
  if (modal) modal.classList.add('hidden');
}

async function submitRenameWorkspace() {
  const input = document.getElementById('renameWsInput');
  const targetId = document.getElementById('renameWsTargetId');
  if (!input || !targetId) return;

  const newName = input.value.trim();
  const projectId = targetId.value;
  if (!newName || !projectId) return;

  try {
    const res = await fetch(`/api/vault/project/${projectId}/rename`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_name: newName }),
    });
    if (res.ok) {
      closeRenameModal();
      const proj = vaultProjects.find(p => p.project_id === projectId);
      if (proj) {
        proj.workspace_name = newName;
      }
      if (currentActiveProjectId === projectId) {
        const titleEl = document.getElementById('projectDetailPageTitle');
        if (titleEl) titleEl.innerText = newName;
        const clipperTitleEl = document.getElementById('clipperWorkspaceTitle');
        if (clipperTitleEl) clipperTitleEl.innerText = newName;
        const breadcrumbEl = document.getElementById('detailViewBreadcrumb');
        if (breadcrumbEl) breadcrumbEl.innerText = `${projectId}`;
        document.title = `${newName} (${projectId}) | Luna`;
        const btnRename = document.getElementById('btnRenameInDetail');
        if (btnRename) {
          btnRename.onclick = () => promptRenameWorkspace(projectId, newName);
        }
      }
      await loadVaultItems();
    } else {
      showNoticeModal('Could not rename', 'An error occurred while saving the workspace name.');
    }
  } catch (e) {
    showNoticeModal('Connection Error', 'Could not connect to the server while updating the workspace.');
  }
}

function openDeleteModalBox() {
  const modal = document.getElementById('deleteModal');
  const box = document.getElementById('deleteModalBox');
  if (!modal || !box) return;
  modal.classList.remove('hidden');
  requestAnimationFrame(() => {
    box.classList.remove('scale-95', 'opacity-0');
    box.classList.add('scale-100', 'opacity-100');
  });
}

function closeDeleteModal() {
  deletingItemId = null;
  deletingProjectId = null;
  const modal = document.getElementById('deleteModal');
  const box = document.getElementById('deleteModalBox');
  if (box) {
    box.classList.remove('scale-100', 'opacity-100');
    box.classList.add('scale-95', 'opacity-0');
  }
  setTimeout(() => {
    if (modal) modal.classList.add('hidden');
  }, 150);
}

function confirmDeleteVaultProject(projectId, wsName, event) {
  if (event && event.stopPropagation) {
    event.stopPropagation();
  }
  deletingProjectId = projectId;
  deletingItemId = null;
  const heading = document.getElementById('deleteModalHeading');
  const desc = document.getElementById('deleteModalDesc');
  const btnText = document.getElementById('deleteModalBtnText');
  const confirmBtn = document.getElementById('deleteModalConfirmBtn');

  if (heading) heading.innerText = 'Delete this workspace?';
  if (desc) desc.innerText = `Are you sure you want to delete workspace "${wsName || 'Workspace'}"? All files in it will be deleted and cannot be recovered.`;
  if (btnText) btnText.innerText = 'Delete';
  if (confirmBtn) {
    confirmBtn.disabled = false;
    confirmBtn.onclick = executeDeleteVaultProject;
  }

  openDeleteModalBox();
}

function releaseMediaLocks() {
  try {
    document.querySelectorAll('video, audio').forEach(el => {
      try {
        if (!el.paused) el.pause();
        el.removeAttribute('src');
        el.load();
      } catch (e) {}
    });
  } catch (e) {}
}

async function executeDeleteVaultProject() {
  if (!deletingProjectId) return;
  const confirmBtn = document.getElementById('deleteModalConfirmBtn');
  const btnText = document.getElementById('deleteModalBtnText');
  const btnSpinner = document.getElementById('deleteModalBtnSpinner');

  if (confirmBtn) confirmBtn.disabled = true;
  if (btnSpinner) btnSpinner.classList.remove('hidden');
  if (btnText) btnText.innerText = 'Deleting...';

  releaseMediaLocks();

  try {
    const res = await fetch(`/api/vault/project/${deletingProjectId}`, { method: 'DELETE' });
    if (res.ok) {
      if (currentActiveProjectId === deletingProjectId) {
        closeProjectPage();
      }
      closeDeleteModal();
      deletingProjectId = null;
      await loadVaultItems();
    } else {
      showNoticeModal('Could not delete workspace', 'Could not delete this workspace. Please try again.');
    }
  } catch (e) {
    showNoticeModal('Server error', 'An error occurred while deleting the workspace.');
  } finally {
    if (confirmBtn) confirmBtn.disabled = false;
    if (btnSpinner) btnSpinner.classList.add('hidden');
    if (btnText) btnText.innerText = 'Delete';
  }
}

function getPlatformBadgeHtml(plat) {
  const p = (plat || '').toLowerCase();
  if (p === 'youtube') {
    return `<span class="px-2 py-0.5 rounded-md bg-red-500/20 backdrop-blur-md border border-red-500/30 text-red-300 text-[10px] font-semibold flex items-center gap-1 shadow-sm"><img src="/assets/youtube-logo.svg?v=3" class="w-3 h-3 object-contain" /> YouTube</span>`;
  } else if (p === 'instagram') {
    return `<span class="px-2 py-0.5 rounded-md bg-pink-500/20 backdrop-blur-md border border-pink-500/30 text-pink-300 text-[10px] font-semibold flex items-center gap-1 shadow-sm"><img src="/assets/instagram-logo.svg?v=3" class="w-3 h-3 object-contain" /> Reels</span>`;
  } else if (p === 'tiktok') {
    return `<span class="px-2 py-0.5 rounded-md bg-zinc-800/80 backdrop-blur-md border border-white/10 text-zinc-200 text-[10px] font-semibold flex items-center gap-1 shadow-sm"><img src="/assets/tiktok-logo.svg?v=3" class="w-3 h-3 object-contain" /> TikTok</span>`;
  }
  return `<span class="px-2 py-0.5 rounded-md bg-white/10 backdrop-blur-md border border-white/20 text-zinc-300 text-[10px] font-semibold flex items-center gap-1 shadow-sm"><i data-lucide="film" class="w-3 h-3"></i> Media</span>`;
}

function formatBytes(bytes) {
  if (!bytes || isNaN(bytes)) return '0 MB';
  const mb = bytes / (1024 * 1024);
  if (mb >= 1024) return (mb / 1024).toFixed(2) + ' GB';
  return mb.toFixed(1) + ' MB';
}

function formatSavedDate(ts) {
  if (!ts) return '';
  try {
    const d = new Date(ts * 1000);
    return d.toLocaleDateString('en-US', { day: 'numeric', month: 'short', year: 'numeric' });
  } catch (e) {
    return '';
  }
}

function formatClipDuration(item) {
  if (item.start_time !== undefined && item.end_time !== undefined && item.end_time > item.start_time) {
    const dur = Math.round(item.end_time - item.start_time);
    return `${dur}s`;
  }
  return '';
}

function copyVaultStoragePath() {
  const storageEl = document.getElementById('vaultStoragePath');
  if (!storageEl) return;
  const path = storageEl.innerText.trim();
  if (!path) return;
  navigator.clipboard.writeText(path).catch(err => {
    console.warn('Clipboard write error:', err);
  });
}

async function openVaultFolder() {
  try {
    const res = await fetch('/api/vault/open-folder', { method: 'POST' });
    if (!res.ok) {
      showNoticeModal('Could not open folder', 'Folder not found or the file manager could not be opened.');
    }
  } catch (err) {
    console.error('Error opening vault folder:', err);
    showNoticeModal('Could not open folder', 'An error occurred while opening the folder.');
  }
}

async function openVaultFile(filePath) {
  if (!filePath) return;
  try {
    const res = await fetch('/api/vault/open-file', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_path: filePath })
    });
    if (!res.ok) {
      showNoticeModal('Could not open file', 'File not found or the file manager could not open it.');
    }
  } catch (err) {
    console.error('Error opening file in Explorer:', err);
    showNoticeModal('Could not open file', 'An error occurred while opening the file.');
  }
}

function confirmDeleteVaultItem(id, title, filePath) {
  deletingItemId = id;
  deletingProjectId = null;
  const heading = document.getElementById('deleteModalHeading');
  const desc = document.getElementById('deleteModalDesc');
  const btnText = document.getElementById('deleteModalBtnText');
  const confirmBtn = document.getElementById('deleteModalConfirmBtn');

  if (heading) heading.innerText = 'Delete this file?';
  if (desc) desc.innerText = `Are you sure you want to delete "${title || 'this file'}"? This action cannot be undone.`;
  if (btnText) btnText.innerText = 'Delete';
  if (confirmBtn) {
    confirmBtn.disabled = false;
    confirmBtn.onclick = executeDeleteVaultItem;
  }

  openDeleteModalBox();
}

async function executeDeleteVaultItem() {
  if (!deletingItemId) return;
  const confirmBtn = document.getElementById('deleteModalConfirmBtn');
  const btnText = document.getElementById('deleteModalBtnText');
  const btnSpinner = document.getElementById('deleteModalBtnSpinner');

  if (confirmBtn) confirmBtn.disabled = true;
  if (btnSpinner) btnSpinner.classList.remove('hidden');
  if (btnText) btnText.innerText = 'Deleting...';

  const idToDelete = deletingItemId;

  releaseMediaLocks();

  try {
    const res = await fetch(`/api/vault/${encodeURIComponent(idToDelete)}`, {
      method: 'DELETE'
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Could not delete file');
    }

    // Card smooth exit animation
    const card = document.getElementById(`vault-card-${idToDelete}`);
    if (card) {
      card.classList.add('opacity-0', 'scale-95', 'pointer-events-none');
      setTimeout(() => {
        if (card && card.parentNode) card.remove();
      }, 300);
    }

    // Update in-memory data
    vaultItems = vaultItems.filter(it => it.id !== idToDelete);
    if (vaultStats.total_files > 0) vaultStats.total_files -= 1;

    if (currentActiveProjectId) {
      const activeProj = vaultProjects.find(p => p.project_id === currentActiveProjectId);
      if (activeProj && activeProj.files) {
        activeProj.files = activeProj.files.filter(f => f.id !== idToDelete);
        const countEl = document.getElementById('projectDetailFileCount');
        const sizeEl = document.getElementById('projectDetailTotalSize');
        const totalSize = activeProj.files.reduce((acc, f) => acc + (f.file_size || 0), 0);
        if (countEl) countEl.innerText = `${activeProj.files.length} file`;
        if (sizeEl) sizeEl.innerText = formatBytes(totalSize);
        if (activeProj.files.length === 0) {
          const emptyState = document.getElementById('projectFilesEmptyState');
          if (emptyState) emptyState.classList.remove('hidden');
        }
      }
    }

    updateVaultStatsUI();
    closeDeleteModal();

    setTimeout(() => {
      renderVaultGallery();
    }, 320);

  } catch (err) {
    showNoticeModal('Could not delete file', err.message || 'An error occurred while deleting the file.');
  } finally {
    if (confirmBtn) confirmBtn.disabled = false;
    if (btnSpinner) btnSpinner.classList.add('hidden');
    if (btnText) btnText.innerText = 'Delete';
  }
}

// Auto-load vault badge count immediately on load
updateVaultBadge();

// Handle hash navigation (e.g. #vault-project/{id})
// Handle hash navigation (e.g. #vault-project/{id}) and trackpad back swipes
window.addEventListener('hashchange', () => {
  const hash = window.location.hash;
  if (hash.startsWith('#vault-project/')) {
    const pId = hash.replace('#vault-project/', '');
    if (currentMainTab !== 'vault') switchMainTab('vault');
    openProjectPage(pId);
  } else {
    if (currentActiveProjectId) {
      closeProjectPage();
    } else {
      document.body.classList.remove('in-workspace');
    }

    if (hash === '#vault') {
      if (currentMainTab !== 'vault') switchMainTab('vault');
    } else if (hash === '#settings') {
      if (currentMainTab !== 'settings') switchMainTab('settings');
    } else if (hash === '#studio') {
      if (currentMainTab !== 'studio') switchMainTab('studio');
    } else if (hash === '#guide') {
      if (currentMainTab !== 'guide') switchMainTab('guide');
    }
  }
});

window.addEventListener('popstate', () => {
  const hash = window.location.hash;
  if (!hash.startsWith('#vault-project/') && currentActiveProjectId) {
    closeProjectPage();
  }
});

// Remove error states when user types in settings inputs
document.addEventListener('input', (e) => {
  if (e.target && e.target.closest && e.target.closest('.t-input')) {
    const wrap = e.target.closest('.t-input-wrap');
    const box = e.target.closest('.t-input');
    if (wrap) wrap.classList.remove('is-error');
    if (box) box.classList.remove('is-error');
  }
});

// Wire up Transitions.dev sliding tabs pill & redraw flowchart on resize
window.addEventListener('resize', () => {
  updateTabsPill(true);
  if (currentActiveProjectId) {
    const proj = vaultProjects.find(p => p.project_id === currentActiveProjectId);
    if (proj && typeof isAiClipperProject === 'function' && isAiClipperProject(proj)) {
      drawClipperConnectors();
    }
  }
});
// A failed job runs again in its own folder, so a finished or partial download is reused.
async function offerRetry(jobId, errMsg) {
  if (!await showConfirmModal('Processing failed', errMsg, 'Retry')) return;
  try {
    const res = await fetch(`/api/retry/${jobId}`, { method: 'POST' });
    if (!res.ok) throw new Error((await res.json()).detail || 'Could not retry the job');
    try { localStorage.setItem('luna_active_job_id', jobId); } catch (e) {}
    await checkAndResumeSavedJob(jobId);
  } catch (err) {
    showNoticeModal('Could not retry', err.message);
  }
}

async function checkAndResumeSavedJob(savedJobId) {
  try {
    const res = await fetch(`/api/status/${savedJobId}`);
    if (!res.ok) {
      localStorage.removeItem('luna_active_job_id');
      localStorage.removeItem('luna_active_ws');
      localStorage.removeItem('luna_active_action');
      return;
    }
    const data = await res.json();
    if (!['completed', 'failed', 'cancelled'].includes(data.status)) {
      activeJobId = savedJobId;
      if (jobIdPill) jobIdPill.innerText = `JOB-${activeJobId}`;
      if (mainActionBtn) {
        mainActionBtn.disabled = true;
        mainActionBtn.classList.add('opacity-50', 'cursor-not-allowed');
      }
      if (progressStateCard) {
        progressStateCard.classList.remove('hidden');
      }
      setCancelButtonVisible(true, 'Cancel');
      const savedAction = data.action || localStorage.getItem('luna_active_action') || 'type_yt_ai_clip';
      currentJobWorkspaceName = data.workspace_name || localStorage.getItem('luna_active_ws') || null;
      initTaskRows(savedAction);
      updateProgressUI(data.stage || 'queued', data);
      startPolling(savedJobId);
    } else {
      localStorage.removeItem('luna_active_job_id');
      localStorage.removeItem('luna_active_ws');
      localStorage.removeItem('luna_active_action');
      // The server restarted while this job ran; it now reports failed and can be retried.
      if (data.status === 'failed' && data.retryable) offerRetry(savedJobId, data.error);
    }
  } catch (e) {
    console.warn('Failed to resume saved job:', e);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  updateTabsPill(true);
  if (typeof initAllGlidingIndicators === 'function') {
    initAllGlidingIndicators();
renderTrimSegments();
  }

  // Check and resume running background job if page was refreshed
  try {
    const savedJobId = localStorage.getItem('luna_active_job_id');
    if (savedJobId) {
      checkAndResumeSavedJob(savedJobId);
    }
  } catch (e) {}

  const hash = window.location.hash;
  if (hash.startsWith('#vault-project/')) {
    document.body.classList.add('in-workspace');
    const pId = hash.replace('#vault-project/', '');
    switchMainTab('vault');
    setTimeout(() => openProjectPage(pId), 300);
  } else if (hash === '#settings') {
    switchMainTab('settings');
  } else if (hash === '#vault') {
    switchMainTab('vault');
  } else if (hash === '#guide') {
    switchMainTab('guide');
  }
});
if (document.fonts && document.fonts.ready) {
  document.fonts.ready.then(() => updateTabsPill(true));
}
setTimeout(() => {
  updateTabsPill(true);
  if (typeof initAllGlidingIndicators === 'function') {
    initAllGlidingIndicators();
  }
}, 0);
