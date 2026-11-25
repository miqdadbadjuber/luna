/* Copyright (C) 2026 Miqdad
 * SPDX-License-Identifier: AGPL-3.0-or-later
 *
 * Isolated frontend controller for Luna AI Clipper Studio (/studio/{project_id}).
 */

const PROJECT_ID = document.body?.dataset?.projectId || '';

const SUBTITLE_PRESETS = [
  { id: 'none', name: 'Off' },
  { id: 'selene', name: 'Selene', baseCqh: 3.4, maxChars: 34, twoLineWeight: true, defaultY: 78 },
];

const PRESET_CARD_PREVIEWS = {
  selene: '<span style="display:flex;flex-direction:column;align-items:center;line-height:1.08;font-family:\'Montserrat\',sans-serif;"><span style="font-weight:400;font-size:9px;color:rgba(255,255,255,0.82);">Se</span><span style="font-weight:700;font-size:10px;color:#fff;">lene</span></span>',
};

const filmstripCanvas = document.createElement('canvas');
filmstripCanvas.className = 'filmstrip-canvas';
filmstripCanvas.width = 14 * 48;
filmstripCanvas.height = 44;

let WORKSPACE_CLIPS = [];

const state = {
  activeIdx: 0,
  currentTime: 0,
  playing: false,
  muted: false,
  rightTab: 'subtitle',
  subStyle: 'none',
  subSize: 'medium',
  customScale: 100,
  subPos: 'bottom',
  posX: 50,
  posY: 78,
  draftMusic: null,
  modalPlaying: false,
  modalZoom: 1,
  exporting: false,
};

const videoEl = document.getElementById('videoEl');
const thumbVideoEl = document.getElementById('thumbVideoEl');
const customAudioEl = document.getElementById('customAudioEl');

function activeClip() {
  return WORKSPACE_CLIPS[state.activeIdx] || null;
}

function activeMusic() {
  return activeClip()?.music || null;
}

function getSubPreset(id) {
  return SUBTITLE_PRESETS.find((p) => p.id === id) || SUBTITLE_PRESETS[0];
}

function fmtMMSS(sec) {
  const s = Math.max(0, Math.round(Number(sec) || 0));
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}

function escHtml(s) {
  return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function encodeMediaUrl(url) {
  if (!url || url === '#') return '#';
  try {
    return encodeURI(decodeURI(url));
  } catch (_) {
    return url;
  }
}

function renderStyleCards() {
  const grid = document.getElementById('subStyleGrid');
  if (!grid) return;
  grid.innerHTML = '';
  SUBTITLE_PRESETS.forEach((p) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = `sub-style-card ${state.subStyle === p.id ? 'is-active' : ''}`;
    btn.dataset.style = p.id;
    btn.title = p.name;
    btn.onclick = () => setSubStyle(p.id);
    const inner = p.id === 'none'
      ? '<span class="text-[11px] text-neutral-400">Off</span>'
      : (PRESET_CARD_PREVIEWS[p.id] || `<span class="text-[11px] text-neutral-200">${escHtml(p.name)}</span>`);
    btn.innerHTML = `
      <span class="check-dot"><i data-lucide="check" class="w-2.5 h-2.5"></i></span>
      ${inner}
    `;
    grid.appendChild(btn);
  });
  if (window.lucide) lucide.createIcons();
}

function buildPersistPayload() {
  return {
    subStyle: state.subStyle,
    subSize: state.subSize,
    customScale: state.customScale,
    subPos: state.subPos,
    posX: state.posX,
    posY: state.posY,
    clips: WORKSPACE_CLIPS.map((c) => ({
      id: c.id,
      dur: c.dur || 0,
      start: c.start || 0,
      end: c.end || c.dur || 0,
      title: c.title || '',
      tags: c.tags || '',
      caption: c.caption || '',
      cues: c.cues || [],
      music: c.music && c.music.assetName ? {
        name: c.music.name,
        assetName: c.music.assetName,
        totalDur: c.music.totalDur,
        sliceStart: c.music.sliceStart,
        volume: c.music.volume,
        peaks: c.music.peaks || [],
      } : null,
    })),
  };
}

let autoSaveTimer = null;
function scheduleDraftSave() {
  clearTimeout(autoSaveTimer);
  autoSaveTimer = setTimeout(() => {
    persistDraftToServer(false);
  }, 600);
}

async function persistDraftToServer(showNotification = false) {
  if (!PROJECT_ID || !WORKSPACE_CLIPS.length) return false;
  try {
    const res = await fetch(`/api/studio/${encodeURIComponent(PROJECT_ID)}/save`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(buildPersistPayload()),
    });
    if (!res.ok) throw new Error('Failed to save');
    if (showNotification) {
      const clip = activeClip();
      const subText = state.subStyle === 'none' ? 'No subtitle' : `Subtitle: ${state.subStyle}`;
      const m = activeMusic();
      const musicText = m ? ` · Music: ${m.name}` : '';
      showToast(`Saved ${clip.name} (${fmtMMSS(clip.start)}–${fmtMMSS(clip.end)}, ${subText}${musicText})`);
    }
    return true;
  } catch (err) {
    if (showNotification) showToast('Could not save draft changes');
    return false;
  }
}

function syncClipAudioElement() {
  const m = activeMusic();
  document.getElementById('customAudioLabel').textContent = m ? m.name : 'Add Music';
  if (m && m.url) {
    const resolved = encodeMediaUrl(m.url);
    if (customAudioEl.getAttribute('src') !== resolved) {
      customAudioEl.src = resolved;
      customAudioEl.load();
    }
    customAudioEl.volume = state.muted ? 0 : m.volume / 100;
  } else {
    customAudioEl.pause();
    customAudioEl.removeAttribute('src');
  }
}

function selectWorkspaceClip(idx) {
  if (!WORKSPACE_CLIPS[idx]) return;
  state.activeIdx = idx;
  state.playing = false;
  closeMusicPopover();
  videoEl.pause();
  customAudioEl.pause();
  const clip = activeClip();
  document.getElementById('captionBox').value = clip.caption || '';
  document.getElementById('clipTitleInput').value = clip.title || '';
  document.getElementById('clipTagsInput').value = clip.tags || '';
  updateCaptionCharCount();
  syncClipAudioElement();
  const srcUrl = encodeMediaUrl(clip.src);
  videoEl.src = srcUrl;
  videoEl.load();
  thumbVideoEl.src = srcUrl;
  thumbVideoEl.load();
  state.currentTime = clip.start || 0;
  renderWorkspaceClips();
  renderRuler();
  renderTracks();
  updateSubtitleOverlay();
  updatePlayhead();
  updatePlayIcon();
}

videoEl.addEventListener('loadedmetadata', () => {
  const clip = activeClip();
  if (!clip) return;
  const realDur = Math.max(1, videoEl.duration || clip.dur || 1);
  if (!clip.end || clip.end >= clip.dur - 0.2 || clip.end > realDur) clip.end = realDur;
  clip.dur = realDur;
  if (videoEl.videoWidth > 0 && videoEl.videoHeight > 0) {
    const frameBox = document.getElementById('mediaFrameBox');
    frameBox.style.aspectRatio = `${videoEl.videoWidth} / ${videoEl.videoHeight}`;
    const isLandscape = videoEl.videoWidth > videoEl.videoHeight;
    frameBox.classList.toggle('w-full', isLandscape);
    frameBox.classList.toggle('h-full', !isLandscape);
  }
  videoEl.currentTime = clip.start || 0;
  renderRuler();
  renderTracks();
  updatePlayhead();
  updateSubtitleOverlay();
});

let thumbGenToken = 0;
thumbVideoEl.addEventListener('loadedmetadata', async () => {
  const token = ++thumbGenToken;
  const dur = thumbVideoEl.duration;
  if (!dur || Number.isNaN(dur)) return;

  const vArea = document.getElementById('videoTrackArea');
  const trackW = Math.max(560, Math.round((vArea?.clientWidth || 1000) - 3));
  const trackH = Math.max(36, Math.round((vArea?.clientHeight || 42) - 6));
  const dpr = Math.max(2, Math.min(3, window.devicePixelRatio || 2));

  filmstripCanvas.width = Math.round(trackW * dpr);
  filmstripCanvas.height = Math.round(trackH * dpr);

  const count = Math.max(14, Math.min(30, Math.round(trackW / (trackH * 1.05))));
  const tilePxW = filmstripCanvas.width / count;
  const tilePxH = filmstripCanvas.height;
  const dstAspect = tilePxW / tilePxH;

  const cctx = filmstripCanvas.getContext('2d');
  cctx.imageSmoothingEnabled = true;
  cctx.imageSmoothingQuality = 'high';
  cctx.fillStyle = '#141414';
  cctx.fillRect(0, 0, filmstripCanvas.width, filmstripCanvas.height);

  for (let i = 0; i < count; i++) {
    if (token !== thumbGenToken) return;
    const target = ((i + 0.5) / count) * dur;
    await new Promise((res) => {
      const timer = setTimeout(res, 600);
      const onSeeked = () => {
        clearTimeout(timer);
        thumbVideoEl.removeEventListener('seeked', onSeeked);
        try {
          const vw = thumbVideoEl.videoWidth || 1080;
          const vh = thumbVideoEl.videoHeight || 1920;
          const srcAspect = vw / vh;
          let sx = 0, sy = 0, sw = vw, sh = vh;
          if (srcAspect > dstAspect) {
            sw = vh * dstAspect;
            sx = (vw - sw) / 2;
          } else {
            sh = vw / dstAspect;
            sy = Math.max(0, (vh - sh) * 0.22);
          }
          const dx = Math.floor(i * tilePxW);
          const dw = Math.ceil((i + 1) * tilePxW) - dx;
          cctx.drawImage(thumbVideoEl, sx, sy, sw, sh, dx, 0, dw, tilePxH);
        } catch (_) {}
        res();
      };
      thumbVideoEl.addEventListener('seeked', onSeeked, { once: true });
      thumbVideoEl.currentTime = target;
    });
  }
});

function renderWorkspaceClips() {
  const list = document.getElementById('aiClipsList');
  list.innerHTML = '';
  WORKSPACE_CLIPS.forEach((c, idx) => {
    const row = document.createElement('div');
    row.className = `list-pill ${idx === state.activeIdx ? 'is-active' : ''}`;
    row.onclick = () => selectWorkspaceClip(idx);
    row.innerHTML = `
      <span class="truncate">${escHtml(c.name)}</span>
      <span class="check-dot"><i data-lucide="check" class="w-2.5 h-2.5"></i></span>
    `;
    list.appendChild(row);
  });
  if (window.lucide) lucide.createIcons();
}

function switchRightTab(tab) {
  state.rightTab = tab;
  document.querySelectorAll('.right-tab').forEach((b) => b.classList.toggle('is-active', b.dataset.tab === tab));
  document.getElementById('panelSubtitle').classList.toggle('hidden', tab !== 'subtitle');
  document.getElementById('panelCaption').classList.toggle('hidden', tab !== 'caption');
}

function getSizeScale() {
  if (state.subSize === 'small') return 0.8;
  if (state.subSize === 'large') return 1.24;
  if (state.subSize === 'custom') return Math.max(0.45, state.customScale / 100);
  return 1.0;
}

function setSubStyle(style) {
  const valid = SUBTITLE_PRESETS.some((p) => p.id === style) ? style : 'none';
  state.subStyle = valid;
  document.querySelectorAll('.sub-style-card').forEach((c) => c.classList.toggle('is-active', c.dataset.style === valid));
  const isOff = valid === 'none';
  const opts = document.getElementById('subtitleOptionsGroup');
  if (opts) {
    opts.classList.toggle('opacity-35', isOff);
    opts.classList.toggle('pointer-events-none', isOff);
    opts.classList.toggle('select-none', isOff);
    opts.setAttribute('aria-disabled', isOff ? 'true' : 'false');
    opts.querySelectorAll('button, input, textarea').forEach((el) => {
      el.disabled = isOff;
    });
  }
  updateSubtitleOverlay();
  if (!isOff && (!activeClip()?.cues || !activeClip().cues.length)) {
    showToast('No transcript found for this clip — type in Current Line to add subtitle');
  }
  scheduleDraftSave();
}

function setSubSize(sz) {
  state.subSize = sz;
  document.querySelectorAll('.size-chip').forEach((c) => c.classList.toggle('is-active', c.dataset.size === sz));
  document.getElementById('customScaleWrap').classList.toggle('hidden', sz !== 'custom');
  document.getElementById('customScaleSlider').value = state.customScale;
  document.getElementById('customScaleLabel').textContent = String(state.customScale);
  updateSubtitleOverlay();
  scheduleDraftSave();
}

function resetSubSize() {
  state.customScale = 100;
  setSubSize('medium');
  showToast('Subtitle size reset to Medium (100)');
}

function setCustomScale(val) {
  state.customScale = Math.max(45, Math.min(200, Number(val)));
  document.getElementById('customScaleLabel').textContent = String(state.customScale);
  updateSubtitleOverlay();
  scheduleDraftSave();
}

function setSubPos(pos) {
  state.subPos = pos;
  document.querySelectorAll('.pos-chip').forEach((c) => c.classList.toggle('is-active', c.dataset.pos === pos));
  document.getElementById('customXYWrap').classList.toggle('hidden', pos !== 'custom');
  document.getElementById('posXSlider').value = Math.round(state.posX);
  document.getElementById('posYSlider').value = Math.round(state.posY);
  document.getElementById('posXLabel').textContent = `${Math.round(state.posX)}%`;
  document.getElementById('posYLabel').textContent = `${Math.round(state.posY)}%`;
  updateSubtitleOverlay();
  scheduleDraftSave();
}

function resetSubPos() {
  state.posX = 50;
  state.posY = 78;
  setSubPos('bottom');
  showToast('Subtitle position reset to Bottom');
}

function setCustomXY(axis, val) {
  if (axis === 'x') {
    state.posX = Math.max(15, Math.min(85, Number(val)));
    document.getElementById('posXLabel').textContent = `${Math.round(state.posX)}%`;
  } else {
    state.posY = Math.max(10, Math.min(92, Number(val)));
    document.getElementById('posYLabel').textContent = `${Math.round(state.posY)}%`;
  }
  updateSubtitleOverlay();
  scheduleDraftSave();
}

function splitIntoTwoBalancedLines(text) {
  const words = text.trim().split(/\s+/).filter(Boolean);
  if (words.length <= 2) return [words.join(' ')];
  const total = text.length;
  let acc = 0;
  let bestIdx = Math.ceil(words.length / 2);
  let bestDiff = Infinity;
  for (let i = 1; i < words.length; i++) {
    acc += words[i - 1].length + 1;
    const diff = Math.abs(acc - total / 2);
    if (diff < bestDiff) { bestDiff = diff; bestIdx = i; }
  }
  return [words.slice(0, bestIdx).join(' '), words.slice(bestIdx).join(' ')];
}

function currentDisplayCue(atTime = state.currentTime) {
  const clip = activeClip();
  const cues = clip?.cues || [];
  if (!cues.length) return null;
  const firstValidIdx = (cues.length > 1 && (cues[0].end - cues[0].start) < 0.25) ? 1 : 0;
  if (atTime < cues[firstValidIdx].start) {
    return { ...cues[firstValidIdx], start: 0, baseIdx: firstValidIdx };
  }
  const idx = cues.findIndex((q, i) => i >= firstValidIdx && atTime >= q.start && atTime < q.end);
  const pick = idx !== -1 ? idx : (atTime >= cues[cues.length - 1].end ? cues.length - 1 : firstValidIdx);
  return { ...cues[pick], baseIdx: pick };
}

function updateActiveCueText(val) {
  const clip = activeClip();
  if (!clip) return;
  if (!Array.isArray(clip.cues)) clip.cues = [];
  const disp = currentDisplayCue();
  if (disp && clip.cues[disp.baseIdx]) {
    clip.cues[disp.baseIdx].text = val;
  } else if (val.trim()) {
    clip.cues.push({ start: clip.start || 0, end: clip.end || clip.dur || 10, text: val });
  }
  updateSubtitleOverlay(true);
  scheduleDraftSave();
}

function updateSubtitleOverlay(skipInputSync = false) {
  const box = document.getElementById('subtitleOverlay');
  const clip = activeClip();
  const disp = currentDisplayCue(state.currentTime);

  if (!skipInputSync) {
    if (disp) {
      document.getElementById('activeCueTime').textContent = `${fmtMMSS(disp.start)} – ${fmtMMSS(disp.end)}`;
      const input = document.getElementById('cueTextInput');
      if (document.activeElement !== input) input.value = disp.text;
      const stageInput = document.getElementById('stageCueInput');
      if (stageInput && document.activeElement !== stageInput) stageInput.value = disp.text;
    } else if (clip) {
      document.getElementById('activeCueTime').textContent = `${fmtMMSS(clip.start)} – ${fmtMMSS(clip.end)}`;
      const input = document.getElementById('cueTextInput');
      if (document.activeElement !== input) input.value = '';
    }
  }

  const preset = getSubPreset(state.subStyle);
  if (preset.id === 'none' || !disp || !disp.text.trim()) {
    box.classList.add('hidden');
    return;
  }

  box.classList.remove('hidden');
  box.className = `subtitle-overlay-box sub-style-${preset.id}`;

  let posX = 50;
  let posY = preset.defaultY || 78;
  if (state.subPos === 'top') posY = 18;
  else if (state.subPos === 'middle') posY = 50;
  else if (state.subPos === 'custom') { posX = state.posX; posY = state.posY; }

  const sizeScale = getSizeScale();
  box.style.left = `${posX}%`;
  box.style.top = `${posY}%`;
  box.style.fontSize = `calc(${preset.baseCqh}cqh * ${sizeScale.toFixed(3)})`;

  const lines = splitIntoTwoBalancedLines(disp.text);
  const span = Math.max(0.2, disp.end - disp.start);
  const progress = state.playing ? Math.max(0, Math.min(1, (state.currentTime - disp.start) / span)) : 0.7;
  const activeLineIdx = lines.length > 1 && progress >= 0.5 ? 1 : 0;
  box.innerHTML = lines
    .map((ln, idx) => `<span class="sub-line ${idx === activeLineIdx ? '' : 'is-muted'}">${escHtml(ln)}</span>`)
    .join('');
}

let stageExpanded = false;

function toggleStageExpand(forceState = null) {
  const next = typeof forceState === 'boolean' ? forceState : !stageExpanded;
  stageExpanded = next;
  const stage = document.getElementById('stageSection');
  stage?.classList.toggle('is-expanded', stageExpanded);
  if (!stageExpanded) closeStageInlineEdit();
  const icon = document.getElementById('stageExpandIcon');
  if (icon) icon.setAttribute('data-lucide', stageExpanded ? 'minimize' : 'maximize');
  const btn = document.getElementById('btnStageExpand');
  if (btn) btn.title = stageExpanded ? 'Exit full size (Esc)' : 'Full size preview (F)';
  if (window.lucide) lucide.createIcons();
  updateSubtitleOverlay(true);
}

function openStageInlineEdit() {
  const box = document.getElementById('stageInlineEdit');
  const inp = document.getElementById('stageCueInput');
  if (!box || !inp) return;
  const disp = currentDisplayCue();
  inp.value = disp ? disp.text : '';
  box.classList.add('is-open');
  inp.focus();
  inp.select();
}

function closeStageInlineEdit() {
  document.getElementById('stageInlineEdit')?.classList.remove('is-open');
}

// Drag subtitle with magnetic center snap guides (zoom-safe ratio calculation)
document.getElementById('subtitleOverlay').addEventListener('pointerdown', (ev) => {
  ev.stopPropagation();
  ev.preventDefault();
  const stageRect = document.getElementById('mediaFrameBox').getBoundingClientRect();
  const guideV = document.getElementById('snapGuideV');
  const guideH = document.getElementById('snapGuideH');
  const SNAP_THRESHOLD = 2.4;
  const startX = ev.clientX;
  const startY = ev.clientY;
  let dragged = false;

  const onMove = (e) => {
    if (!dragged && Math.hypot(e.clientX - startX, e.clientY - startY) < 4) return;
    dragged = true;
    if (state.subPos !== 'custom') setSubPos('custom');
    const rawX = Math.max(15, Math.min(85, ((e.clientX - stageRect.left) / stageRect.width) * 100));
    const rawY = Math.max(10, Math.min(92, ((e.clientY - stageRect.top) / stageRect.height) * 100));
    const snapX = Math.abs(rawX - 50) <= SNAP_THRESHOLD;
    const snapY = Math.abs(rawY - 50) <= SNAP_THRESHOLD;
    state.posX = snapX ? 50 : rawX;
    state.posY = snapY ? 50 : rawY;
    guideV?.classList.toggle('is-visible', snapX);
    guideH?.classList.toggle('is-visible', snapY);
    document.getElementById('posXSlider').value = Math.round(state.posX);
    document.getElementById('posYSlider').value = Math.round(state.posY);
    document.getElementById('posXLabel').textContent = `${Math.round(state.posX)}%`;
    document.getElementById('posYLabel').textContent = `${Math.round(state.posY)}%`;
    updateSubtitleOverlay(true);
  };
  const onUp = () => {
    window.removeEventListener('pointermove', onMove);
    window.removeEventListener('pointerup', onUp);
    guideV?.classList.remove('is-visible');
    guideH?.classList.remove('is-visible');
    if (dragged) {
      scheduleDraftSave();
    } else if (stageExpanded) {
      openStageInlineEdit();
    } else {
      switchRightTab('subtitle');
      const inp = document.getElementById('cueTextInput');
      inp.focus();
      inp.select();
    }
  };
  window.addEventListener('pointermove', onMove);
  window.addEventListener('pointerup', onUp);
});

function renderRuler() {
  const clip = activeClip();
  if (!clip) return;
  const ruler = document.getElementById('timelineRuler');
  const dur = clip.dur || 1;
  const steps = 8;
  let html = '';
  for (let i = 0; i <= steps; i++) {
    const sec = Math.round((i / steps) * dur);
    html += `<span>${sec}s</span>`;
    if (i < steps) html += '<span class="text-neutral-700 tracking-widest select-none">· · ·</span>';
  }
  ruler.innerHTML = html;
}

function sampleMusicSlicePeaks(peaks, totalDur, sliceStart, clipSpan, outPoints = 64) {
  if (!peaks || !peaks.length) return [];
  const dur = Math.max(0.1, totalDur || clipSpan || 1);
  const startRatio = Math.max(0, Math.min(1, sliceStart / dur));
  const endRatio = Math.max(startRatio + 0.01, Math.min(1, (sliceStart + clipSpan) / dur));
  const maxIdx = peaks.length - 1;
  const out = [];
  for (let i = 0; i < outPoints; i++) {
    const r = startRatio + (i / Math.max(1, outPoints - 1)) * (endRatio - startRatio);
    const fIdx = r * maxIdx;
    const i0 = Math.floor(fIdx);
    const i1 = Math.min(maxIdx, i0 + 1);
    const frac = fIdx - i0;
    out.push(peaks[i0] * (1 - frac) + peaks[i1] * frac);
  }
  return out;
}

function buildModernWaveArea(peaks, totalW, h) {
  const count = peaks.length;
  if (!count) return '';
  const minV = Math.min(...peaks);
  const maxV = Math.max(...peaks);
  const range = Math.max(0.08, maxV - minV);
  const norm = peaks.map((v) => 0.14 + ((v - minV) / range) * 0.86);
  const smooth = norm.map((v, i) => {
    const a = norm[Math.max(0, i - 1)] ?? v;
    const b = norm[Math.min(count - 1, i + 1)] ?? v;
    return (a + v * 2 + b) / 4;
  });
  const base = h;
  const maxH = h * 0.74;
  const pts = smooth.map((v, i) => [(i / Math.max(1, count - 1)) * totalW, base - v * maxH]);

  let topPath = `M ${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
  for (let i = 1; i < pts.length; i++) {
    const [px, py] = pts[i - 1];
    const [cx, cy] = pts[i];
    const mx = ((px + cx) / 2).toFixed(1);
    const my = ((py + cy) / 2).toFixed(1);
    topPath += ` Q ${px.toFixed(1)} ${py.toFixed(1)}, ${mx} ${my}`;
  }
  const last = pts[pts.length - 1];
  topPath += ` L ${last[0].toFixed(1)} ${last[1].toFixed(1)}`;
  const areaPath = `${topPath} L ${totalW} ${base} L 0 ${base} Z`;

  return `
    <defs>
      <linearGradient id="lunaWaveFill" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="rgba(255,255,255,0.09)" />
        <stop offset="100%" stop-color="rgba(255,255,255,0.01)" />
      </linearGradient>
    </defs>
    <path d="${areaPath}" fill="url(#lunaWaveFill)" />
    <path d="${topPath}" fill="none" stroke="rgba(255,255,255,0.14)" stroke-width="0.9" stroke-linecap="round" />
  `;
}

function renderTracks() {
  const clip = activeClip();
  if (!clip) return;
  const dur = Math.max(1, clip.dur || 1);
  const leftPct = (clip.start / dur) * 100;
  const widthPct = Math.max(3, ((clip.end - clip.start) / dur) * 100);

  const filmWidthPct = (100 / widthPct) * 100;
  const filmOffsetPct = -(leftPct / widthPct) * 100;
  filmstripCanvas.style.width = `${filmWidthPct}%`;
  filmstripCanvas.style.maxWidth = 'none';
  filmstripCanvas.style.left = `${filmOffsetPct}%`;

  const vArea = document.getElementById('videoTrackArea');
  vArea.innerHTML = `
    <div id="videoSeg" class="video-track-seg" style="left: ${leftPct}%; width: ${widthPct}%;">
      <div class="absolute inset-0 bg-gradient-to-t from-black/55 via-transparent to-black/35 pointer-events-none z-[1]"></div>
      <div class="seg-grab-bar seg-grab-left" data-edge="start" title="Drag to trim Start"></div>
      <div class="relative z-[2] w-full h-full px-5 flex items-center justify-between text-[11px] text-white pointer-events-none drop-shadow">
        <span class="font-medium truncate">${escHtml(clip.name)}</span>
        <span class="text-neutral-200 tabular-nums">${Math.round(clip.end - clip.start)}s</span>
      </div>
      <div class="seg-grab-bar seg-grab-right" data-edge="end" title="Drag to trim End"></div>
    </div>
  `;
  const segEl = document.getElementById('videoSeg');
  segEl.insertBefore(filmstripCanvas, segEl.firstChild);

  const m = activeMusic();
  const hasMusic = Boolean(m);
  document.getElementById('musicTrackRow').classList.toggle('hidden', !hasMusic);
  const tlPanel = document.getElementById('timelinePanel');
  tlPanel.classList.toggle('h-[164px]', !hasMusic);
  tlPanel.classList.toggle('h-[204px]', hasMusic);

  if (hasMusic) {
    const aArea = document.getElementById('audioTrackArea');
    const clipSpan = Math.max(1, clip.end - clip.start);
    const peaks = (m.peaks && m.peaks.length) ? m.peaks : defaultPeaks(96);
    const slicePeaks = sampleMusicSlicePeaks(peaks, m.totalDur, m.sliceStart, clipSpan, 64);
    aArea.innerHTML = `
      <div id="musicBarSeg" class="audio-track-seg" style="left: ${leftPct}%; width: ${widthPct}%;" title="Click to adjust music volume">
        <div class="relative h-full overflow-hidden w-full">
          <svg class="h-full w-full absolute inset-0" viewBox="0 0 400 28" preserveAspectRatio="none">
            ${buildModernWaveArea(slicePeaks, 400, 28)}
          </svg>
          <span class="relative z-10 px-3 h-full flex items-center justify-between text-[11px] text-neutral-200 pointer-events-none">
            <span class="truncate pr-2 font-medium">${escHtml(m.name)}</span>
            <span class="text-neutral-400 tabular-nums shrink-0">${m.volume}%</span>
          </span>
        </div>
      </div>
    `;
    document.getElementById('musicBarSeg').addEventListener('pointerdown', (ev) => {
      ev.stopPropagation();
      toggleMusicPopover();
    });
  }

  document.getElementById('trimRangeBadge').textContent = `${fmtMMSS(clip.start)} – ${fmtMMSS(clip.end)}`;

  segEl.addEventListener('pointerdown', (ev) => {
    const edge = ev.target.dataset.edge;
    if (edge === 'start' || edge === 'end') {
      ev.stopPropagation();
      ev.preventDefault();
      startTrimDrag(ev, edge);
    }
  });
}

function toggleMusicPopover() {
  const m = activeMusic();
  if (!m) return;
  const pop = document.getElementById('musicInlinePopover');
  const willShow = pop.classList.contains('hidden');
  if (willShow) {
    document.getElementById('inlineMusicVolSlider').value = m.volume;
    document.getElementById('inlineMusicVolText').textContent = `${m.volume}%`;
    pop.classList.remove('hidden');
  } else {
    pop.classList.add('hidden');
  }
}

function closeMusicPopover() {
  document.getElementById('musicInlinePopover')?.classList.add('hidden');
}

document.addEventListener('pointerdown', (ev) => {
  if (!ev.target.closest('#musicTrackRow')) closeMusicPopover();
});

function setMusicVolume(val) {
  const m = activeMusic();
  if (!m) return;
  m.volume = Number(val);
  document.getElementById('inlineMusicVolText').textContent = `${val}%`;
  if (!state.muted) customAudioEl.volume = m.volume / 100;
  const label = document.querySelector('#musicBarSeg span span:last-child');
  if (label) label.textContent = `${val}%`;
  scheduleDraftSave();
}

function startTrimDrag(ev, edge) {
  const clip = activeClip();
  if (!clip) return;
  const rect = document.getElementById('videoTrackArea').getBoundingClientRect();
  const onMove = (e) => {
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const t = ratio * clip.dur;
    if (edge === 'start') {
      clip.start = Math.max(0, Math.min(clip.end - 1, t));
      seekTo(clip.start);
    } else {
      clip.end = Math.min(clip.dur, Math.max(clip.start + 1, t));
      seekTo(clip.end);
    }
    renderTracks();
  };
  const onUp = () => {
    window.removeEventListener('pointermove', onMove);
    window.removeEventListener('pointerup', onUp);
    scheduleDraftSave();
  };
  window.addEventListener('pointermove', onMove);
  window.addEventListener('pointerup', onUp);
}

function resetTrim() {
  const clip = activeClip();
  if (!clip) return;
  clip.start = 0;
  clip.end = clip.dur;
  seekTo(0);
  renderTracks();
  scheduleDraftSave();
  showToast('Reset clip boundaries');
}

function syncMusicTimeToVideo(playIfReady = false) {
  const clip = activeClip();
  const m = activeMusic();
  if (!clip || !m || !customAudioEl.src || state.modalPlaying) return;
  const offset = Math.max(0, state.currentTime - clip.start);
  const targetAudioTime = m.sliceStart + offset;
  if (Math.abs(customAudioEl.currentTime - targetAudioTime) > 0.08) {
    customAudioEl.currentTime = targetAudioTime;
  }
  if (playIfReady && state.playing && !videoEl.paused && !videoEl.seeking && !videoEl.ended && videoEl.readyState >= 3) {
    customAudioEl.volume = state.muted ? 0 : m.volume / 100;
    if (customAudioEl.paused) customAudioEl.play().catch(() => {});
  }
}

function seekTo(sec) {
  const clip = activeClip();
  if (!clip) return;
  const m = activeMusic();
  state.currentTime = Math.max(0, Math.min(clip.dur, sec));
  if (m && customAudioEl.src && !state.modalPlaying) {
    customAudioEl.pause();
  }
  if (Math.abs(videoEl.currentTime - state.currentTime) > 0.03) {
    videoEl.currentTime = state.currentTime;
  } else {
    syncMusicTimeToVideo(true);
  }
  if (m && customAudioEl.src && !state.modalPlaying) {
    const offset = Math.max(0, state.currentTime - clip.start);
    customAudioEl.currentTime = m.sliceStart + offset;
  }
  updateSubtitleOverlay();
  updatePlayhead();
}

function stepTime(delta) {
  seekTo(state.currentTime + delta);
}

function updatePlayhead() {
  const clip = activeClip();
  if (!clip) return;
  const pct = clip.dur > 0 ? (state.currentTime / clip.dur) * 100 : 0;
  document.getElementById('playhead').style.left = `${pct}%`;
}

function stopPlaybackAtEnd() {
  const clip = activeClip();
  if (!clip) return;
  state.playing = false;
  videoEl.pause();
  customAudioEl.pause();
  state.currentTime = Math.min(clip.end, videoEl.duration || clip.dur);
  updatePlayhead();
  updateSubtitleOverlay();
  updatePlayIcon();
}

videoEl.addEventListener('ended', () => {
  if (state.playing) stopPlaybackAtEnd();
  else if (!state.modalPlaying) customAudioEl.pause();
});
videoEl.addEventListener('pause', () => {
  if (!state.modalPlaying) customAudioEl.pause();
});
videoEl.addEventListener('seeking', () => {
  if (!state.modalPlaying) customAudioEl.pause();
});
videoEl.addEventListener('waiting', () => {
  if (!state.modalPlaying) customAudioEl.pause();
});
videoEl.addEventListener('seeked', () => {
  state.currentTime = videoEl.currentTime;
  syncMusicTimeToVideo(true);
});
videoEl.addEventListener('playing', () => {
  state.currentTime = videoEl.currentTime;
  syncMusicTimeToVideo(true);
});

function togglePlay() {
  const clip = activeClip();
  if (!clip) return;
  const m = activeMusic();
  state.playing = !state.playing;
  if (state.playing) {
    if (videoEl.ended || state.currentTime >= clip.end - 0.08 || state.currentTime < clip.start) {
      seekTo(clip.start);
    } else if (m && customAudioEl.src) {
      const offset = Math.max(0, state.currentTime - clip.start);
      customAudioEl.currentTime = m.sliceStart + offset;
    }
    videoEl.play().catch(() => {});
    if (m && customAudioEl.src) {
      customAudioEl.volume = state.muted ? 0 : m.volume / 100;
      customAudioEl.play().catch(() => {});
    }
  } else {
    videoEl.pause();
    customAudioEl.pause();
  }
  updateSubtitleOverlay(true);
  updatePlayIcon();
}

function updatePlayIcon() {
  const iconName = state.playing ? 'pause' : 'play';
  document.getElementById('playIcon').setAttribute('data-lucide', iconName);
  document.getElementById('expandedPlayIcon')?.setAttribute('data-lucide', iconName);
  if (window.lucide) lucide.createIcons();
}

function toggleMute() {
  const m = activeMusic();
  state.muted = !state.muted;
  videoEl.muted = state.muted;
  if (m) customAudioEl.volume = state.muted ? 0 : m.volume / 100;
  const volIcon = state.muted ? 'volume-x' : 'volume-2';
  document.getElementById('bottomMuteIcon').setAttribute('data-lucide', volIcon);
  document.getElementById('expandedMuteIcon')?.setAttribute('data-lucide', volIcon);
  document.getElementById('origAudioIcon').setAttribute('data-lucide', state.muted ? 'volume-x' : 'check');
  if (window.lucide) lucide.createIcons();
}

// --- Background Music Upload & Slice Modal ---
function defaultPeaks(n) {
  return Array.from({ length: n }, (_, i) => 0.25 + 0.7 * Math.abs(Math.sin(i * 0.45) * Math.cos(i * 0.17)));
}

async function extractPeaksFromFile(file) {
  try {
    const buf = await file.arrayBuffer();
    const ac = new (window.AudioContext || window.webkitAudioContext)();
    const audioBuf = await ac.decodeAudioData(buf);
    const ch = audioBuf.getChannelData(0);
    const n = 160;
    const block = Math.max(1, Math.floor(ch.length / n));
    const raw = [];
    for (let i = 0; i < n; i++) {
      let sqSum = 0;
      let samples = 0;
      const base = i * block;
      const step = Math.max(1, Math.floor(block / 256));
      for (let j = 0; j < block; j += step) {
        const v = ch[base + j] || 0;
        sqSum += v * v;
        samples++;
      }
      raw.push(Math.sqrt(sqSum / Math.max(1, samples)));
    }
    const maxRms = Math.max(0.01, ...raw);
    const peaks = raw.map((v) => Math.min(1, v / maxRms));
    ac.close();
    return { peaks, duration: audioBuf.duration };
  } catch (_) {
    return { peaks: defaultPeaks(160), duration: 180 };
  }
}

async function onSelectMusicFile(ev) {
  const file = ev.target.files?.[0];
  if (!file) return;
  ev.target.value = '';
  const clip = activeClip();
  if (!clip) return;

  showToast(`Uploading ${file.name}...`);
  try {
    const uploadUrl = `/api/studio/${encodeURIComponent(PROJECT_ID)}/music?clip_id=${encodeURIComponent(clip.id)}&filename=${encodeURIComponent(file.name)}`;
    const [uploadRes, extracted] = await Promise.all([
      fetch(uploadUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/octet-stream' },
        body: file,
      }),
      extractPeaksFromFile(file),
    ]);
    if (!uploadRes.ok) {
      const errData = await uploadRes.json().catch(() => ({}));
      throw new Error(errData.detail || 'Upload failed');
    }
    const uploaded = await uploadRes.json();
    state.draftMusic = {
      name: uploaded.name || file.name,
      assetName: uploaded.assetName,
      url: uploaded.url,
      totalDur: Math.max(clip.dur || 1, extracted.duration),
      sliceStart: 0,
      volume: 35,
      peaks: extracted.peaks,
    };
    openMusicModal(true);
  } catch (err) {
    showToast(err.message || 'Could not upload audio');
  }
}

function openMusicModal(isNew = false) {
  const curMusic = activeMusic();
  if (!isNew && !curMusic) return;
  if (!isNew) {
    state.draftMusic = { ...curMusic };
  }
  const m = state.draftMusic;
  if (!m.peaks || !m.peaks.length) m.peaks = defaultPeaks(96);
  state.modalZoom = 1;
  document.getElementById('modalMusicName').textContent = m.name;
  document.getElementById('modalVolumeSlider').value = m.volume;
  document.getElementById('modalVolumeText').textContent = `${m.volume}%`;
  document.getElementById('btnRemoveMusic').classList.toggle('hidden', isNew && !curMusic);

  const buildModalBars = (fill) => {
    let bars = '';
    const count = m.peaks.length;
    const innerX = 5;
    const usableW = 400 - innerX * 2;
    const step = usableW / count;
    for (let i = 0; i < count; i++) {
      const bh = Math.max(3, m.peaks[i] * (52 - 12));
      const y = (52 - bh) / 2;
      const x = (innerX + i * step).toFixed(1);
      bars += `<rect x="${x}" y="${y.toFixed(1)}" width="${Math.max(1.2, step * 0.56).toFixed(1)}" height="${bh.toFixed(1)}" rx="1" fill="${fill}" />`;
    }
    return bars;
  };

  const bgWave = document.getElementById('modalWaveSvg');
  bgWave.setAttribute('viewBox', '0 0 400 52');
  bgWave.innerHTML = buildModalBars('rgba(255,255,255,0.12)');

  const selWave = document.getElementById('modalWaveSelSvg');
  selWave.setAttribute('viewBox', '0 0 400 52');
  selWave.innerHTML = buildModalBars('rgba(255,255,255,0.34)');

  const litWave = document.getElementById('modalWaveLitSvg');
  litWave.setAttribute('viewBox', '0 0 400 52');
  litWave.innerHTML = buildModalBars('#ffffff');

  const resolved = encodeMediaUrl(m.url);
  if (customAudioEl.getAttribute('src') !== resolved) {
    customAudioEl.src = resolved;
    customAudioEl.load();
  }
  state.modalPlaying = false;
  customAudioEl.pause();
  updateModalPlayIcon();
  applyModalZoom(false);
  renderModalWindow();

  document.getElementById('musicPickerModal').classList.remove('hidden');
  if (window.lucide) lucide.createIcons();
}

const MODAL_ZOOM_STEPS = [1, 1.5, 2, 3, 4];

function stepModalZoom(dir) {
  const idx = MODAL_ZOOM_STEPS.indexOf(state.modalZoom || 1);
  const nextIdx = Math.max(0, Math.min(MODAL_ZOOM_STEPS.length - 1, (idx === -1 ? 0 : idx) + dir));
  state.modalZoom = MODAL_ZOOM_STEPS[nextIdx];
  applyModalZoom(true);
}

function applyModalZoom(centerSelection = true) {
  const m = state.draftMusic;
  const clip = activeClip();
  const z = state.modalZoom || 1;
  document.getElementById('modalWaveZoomContent').style.width = `${z * 100}%`;

  if (m && clip) {
    const ticks = Math.max(4, Math.round(4 * z));
    const rulerEl = document.getElementById('modalWaveRuler');
    rulerEl.innerHTML = Array.from({ length: ticks + 1 }, (_, i) => `<span>${fmtMMSS((i / ticks) * m.totalDur)}</span>`).join('');

    if (centerSelection) {
      const scrollEl = document.getElementById('modalWaveScroll');
      const clipSpan = Math.min(m.totalDur, Math.max(1, clip.end - clip.start));
      const midRatio = (m.sliceStart + clipSpan / 2) / m.totalDur;
      const targetScroll = midRatio * scrollEl.scrollWidth - scrollEl.clientWidth / 2;
      scrollEl.scrollLeft = Math.max(0, targetScroll);
    }
  }
}

function updateModalPlayhead(sec) {
  const m = state.draftMusic;
  const clip = activeClip();
  if (!m || !clip) return;
  const clipSpan = Math.min(m.totalDur, Math.max(1, clip.end - clip.start));
  const cur = typeof sec === 'number' ? sec : m.sliceStart;
  const progressPct = state.modalPlaying
    ? Math.max(0, Math.min(100, ((cur - m.sliceStart) / clipSpan) * 100))
    : 0;
  document.getElementById('modalWaveFillWrap').style.clipPath = `inset(0 ${Math.max(0, 100 - progressPct)}% 0 0)`;
}

function renderModalWindow() {
  const m = state.draftMusic;
  const clip = activeClip();
  if (!m || !clip) return;
  const clipSpan = Math.min(m.totalDur, Math.max(1, clip.end - clip.start));
  m.sliceStart = Math.max(0, Math.min(m.totalDur - clipSpan, m.sliceStart));
  const leftPct = (m.sliceStart / m.totalDur) * 100;
  const widthPct = Math.max(1, (clipSpan / m.totalDur) * 100);

  const win = document.getElementById('modalWindowBox');
  win.style.left = `${leftPct}%`;
  win.style.width = `${widthPct}%`;

  const innerW = `${(100 / widthPct) * 100}%`;
  const innerL = `${-(leftPct / widthPct) * 100}%`;
  const selWave = document.getElementById('modalWaveSelSvg');
  const litWave = document.getElementById('modalWaveLitSvg');
  selWave.style.width = innerW;
  selWave.style.left = innerL;
  litWave.style.width = innerW;
  litWave.style.left = innerL;

  document.getElementById('modalMusicMeta').textContent = `${fmtMMSS(m.sliceStart)} – ${fmtMMSS(m.sliceStart + clipSpan)}`;
  updateModalPlayhead(state.modalPlaying ? customAudioEl.currentTime : m.sliceStart);
}

function updateModalVolume(val) {
  if (!state.draftMusic) return;
  state.draftMusic.volume = Number(val);
  document.getElementById('modalVolumeText').textContent = `${val}%`;
  customAudioEl.volume = state.draftMusic.volume / 100;
}

function toggleModalMusicPreview() {
  if (!state.draftMusic) return;
  state.modalPlaying = !state.modalPlaying;
  if (state.modalPlaying) {
    customAudioEl.currentTime = state.draftMusic.sliceStart;
    customAudioEl.volume = state.draftMusic.volume / 100;
    customAudioEl.play().catch(() => {});
    updateModalPlayhead(state.draftMusic.sliceStart);
  } else {
    customAudioEl.pause();
    updateModalPlayhead(state.draftMusic.sliceStart);
  }
  updateModalPlayIcon();
}

function updateModalPlayIcon() {
  document.getElementById('modalPlayIcon').setAttribute('data-lucide', state.modalPlaying ? 'pause' : 'play');
  if (window.lucide) lucide.createIcons();
}

function closeMusicModal(apply) {
  state.modalPlaying = false;
  customAudioEl.pause();
  document.getElementById('musicPickerModal').classList.add('hidden');
  const clip = activeClip();
  if (apply && state.draftMusic && clip) {
    clip.music = {
      name: state.draftMusic.name,
      assetName: state.draftMusic.assetName,
      url: state.draftMusic.url,
      totalDur: state.draftMusic.totalDur,
      sliceStart: state.draftMusic.sliceStart,
      volume: state.draftMusic.volume,
      peaks: state.draftMusic.peaks,
    };
    syncClipAudioElement();
    renderTracks();
    scheduleDraftSave();
    showToast(`Music ready for ${clip.name}: ${clip.music.name}`);
  } else {
    syncClipAudioElement();
  }
  state.draftMusic = null;
}

function removeCustomMusic() {
  const clip = activeClip();
  if (!clip) return;
  clip.music = null;
  state.draftMusic = null;
  state.modalPlaying = false;
  customAudioEl.pause();
  customAudioEl.removeAttribute('src');
  closeMusicPopover();
  document.getElementById('customAudioLabel').textContent = 'Add Music';
  document.getElementById('musicPickerModal').classList.add('hidden');
  renderTracks();
  scheduleDraftSave();
  showToast(`Music removed from ${clip.name}`);
}

document.getElementById('modalWaveBox').addEventListener('pointerdown', (ev) => {
  if (ev.target.closest('#modalWindowBox') || !state.draftMusic || !activeClip()) return;
  const m = state.draftMusic;
  const rect = document.getElementById('modalWaveTrack').getBoundingClientRect();
  const clipSpan = Math.min(m.totalDur, Math.max(1, activeClip().end - activeClip().start));
  const clickSec = ((ev.clientX - rect.left) / rect.width) * m.totalDur;
  m.sliceStart = Math.max(0, Math.min(m.totalDur - clipSpan, clickSec - clipSpan / 2));
  if (state.modalPlaying) customAudioEl.currentTime = m.sliceStart;
  renderModalWindow();
});

document.getElementById('modalWindowBox').addEventListener('pointerdown', (ev) => {
  ev.stopPropagation();
  ev.preventDefault();
  if (!state.draftMusic || !activeClip()) return;
  const m = state.draftMusic;
  const boxRect = document.getElementById('modalWaveTrack').getBoundingClientRect();
  const startX = ev.clientX;
  const origStart = m.sliceStart;
  const clipSpan = Math.min(m.totalDur, Math.max(1, activeClip().end - activeClip().start));

  const onMove = (e) => {
    const dx = e.clientX - startX;
    const deltaSec = (dx / boxRect.width) * m.totalDur;
    m.sliceStart = Math.max(0, Math.min(m.totalDur - clipSpan, origStart + deltaSec));
    renderModalWindow();
  };
  const onUp = () => {
    if (state.modalPlaying) customAudioEl.currentTime = m.sliceStart;
    renderModalWindow();
    window.removeEventListener('pointermove', onMove);
    window.removeEventListener('pointerup', onUp);
  };
  window.addEventListener('pointermove', onMove);
  window.addEventListener('pointerup', onUp);
});

// --- Caption Tab ---
function updateCaptionCharCount() {
  const len = (document.getElementById('captionBox')?.value || '').length;
  const el = document.getElementById('captionCharCount');
  if (el) el.textContent = `${len} chars`;
}

function saveCaptionDraft() {
  const clip = activeClip();
  if (!clip) return;
  clip.caption = document.getElementById('captionBox').value;
  updateCaptionCharCount();
  scheduleDraftSave();
}

function saveClipMetaDraft() {
  const clip = activeClip();
  if (!clip) return;
  clip.title = document.getElementById('clipTitleInput').value;
  clip.tags = document.getElementById('clipTagsInput').value;
  scheduleDraftSave();
}

function focusCaptionEdit() {
  switchRightTab('caption');
  const box = document.getElementById('captionBox');
  box.focus();
  box.setSelectionRange(box.value.length, box.value.length);
}

function copyCaption() {
  const text = document.getElementById('captionBox').value;
  navigator.clipboard?.writeText(text).catch(() => {});
  showToast('Caption copied');
}

function copyFullPost() {
  const caption = document.getElementById('captionBox').value.trim();
  const tags = document.getElementById('clipTagsInput').value.trim();
  const full = tags ? `${caption}\n\n${tags}` : caption;
  navigator.clipboard?.writeText(full).catch(() => {});
  showToast('Caption & hashtags copied');
}

// --- Save Draft & Export Download ---
async function saveClip() {
  const clip = activeClip();
  if (!clip) return;
  clip.caption = document.getElementById('captionBox').value;
  clip.title = document.getElementById('clipTitleInput').value;
  clip.tags = document.getElementById('clipTagsInput').value;
  await persistDraftToServer(true);
}

async function downloadClip() {
  const clip = activeClip();
  if (!clip || state.exporting) return;
  state.exporting = true;
  const dlBtn = document.getElementById('btnDownloadClip');
  if (dlBtn) dlBtn.disabled = true;
  showToast(`Rendering ${clip.name}...`);

  try {
    await persistDraftToServer(false);
    const res = await fetch(
      `/api/studio/${encodeURIComponent(PROJECT_ID)}/export/${encodeURIComponent(clip.id)}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          start: clip.start,
          end: clip.end,
          muted: state.muted,
          subStyle: state.subStyle,
          subSize: state.subSize,
          customScale: state.customScale,
          subPos: state.subPos,
          posX: state.posX,
          posY: state.posY,
          cues: clip.cues || [],
          music: clip.music || null,
        }),
      }
    );
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || 'Export failed');
    }
    const blob = await res.blob();
    const dlUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = dlUrl;
    const stem = (clip.filename || clip.id).replace(/\.[^.]+$/, '');
    a.download = `${stem}_studio.mp4`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(dlUrl), 10000);
    showToast(`Downloaded ${stem}_studio.mp4`);
  } catch (err) {
    showToast(err.message || 'Export failed');
  } finally {
    state.exporting = false;
    if (dlBtn) dlBtn.disabled = false;
  }
}

let toastTimer = null;
function showToast(msg) {
  const el = document.getElementById('editorToast');
  document.getElementById('editorToastText').textContent = msg;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 2600);
}

function startScrub(ev) {
  ev.preventDefault();
  const clip = activeClip();
  if (!clip) return;
  const update = (e) => {
    const rect = document.getElementById('videoTrackArea').getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    seekTo(ratio * clip.dur);
  };
  update(ev);
  const onUp = () => {
    window.removeEventListener('pointermove', update);
    window.removeEventListener('pointerup', onUp);
  };
  window.addEventListener('pointermove', update);
  window.addEventListener('pointerup', onUp);
}

document.getElementById('timelineRuler').addEventListener('pointerdown', startScrub);
document.getElementById('videoTrackArea').addEventListener('pointerdown', startScrub);
document.getElementById('playheadDot').addEventListener('pointerdown', (ev) => {
  ev.stopPropagation();
  startScrub(ev);
});

function tick() {
  if (state.playing && activeClip()) {
    const clip = activeClip();
    state.currentTime = videoEl.currentTime;
    if (videoEl.ended || state.currentTime >= clip.end - 0.04) {
      stopPlaybackAtEnd();
    } else {
      if (videoEl.seeking || videoEl.readyState < 3) {
        if (!state.modalPlaying && !customAudioEl.paused) customAudioEl.pause();
      } else {
        syncMusicTimeToVideo(true);
      }
      updateSubtitleOverlay();
      updatePlayhead();
    }
  }
  if (state.modalPlaying && state.draftMusic && activeClip()) {
    const m = state.draftMusic;
    const clipSpan = Math.min(m.totalDur, Math.max(1, activeClip().end - activeClip().start));
    const sliceEnd = m.sliceStart + clipSpan;
    if (customAudioEl.currentTime >= sliceEnd) {
      customAudioEl.currentTime = m.sliceStart;
    }
    updateModalPlayhead(customAudioEl.currentTime);
  }
  requestAnimationFrame(tick);
}

window.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && stageExpanded) { e.preventDefault(); toggleStageExpand(false); return; }
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
  if (e.code === 'Space') { e.preventDefault(); togglePlay(); }
  else if (e.key === 'ArrowLeft') { e.preventDefault(); stepTime(-0.5); }
  else if (e.key === 'ArrowRight') { e.preventDefault(); stepTime(0.5); }
  else if (e.key === 'f' || e.key === 'F') { e.preventDefault(); toggleStageExpand(); }
});

async function init() {
  renderStyleCards();
  try {
    const res = await fetch(`/api/studio/${encodeURIComponent(PROJECT_ID)}`);
    if (!res.ok) throw new Error('Workspace not found');
    const data = await res.json();
    document.getElementById('projectTitle').textContent = data.workspace_name || 'AI Clipper Studio';
    document.title = `${data.workspace_name || 'Studio'} | Luna`;
    WORKSPACE_CLIPS = data.clips || [];

    const ui = data.ui || {};
    state.subStyle = SUBTITLE_PRESETS.some((p) => p.id === ui.subStyle) ? ui.subStyle : 'none';
    state.subSize = ui.subSize || 'medium';
    state.customScale = typeof ui.customScale === 'number' ? ui.customScale : 100;
    state.subPos = ui.subPos || 'bottom';
    state.posX = typeof ui.posX === 'number' ? ui.posX : 50;
    state.posY = typeof ui.posY === 'number' ? ui.posY : 78;

    const params = new URLSearchParams(window.location.search);
    const wantedClip = params.get('clip');
    const wantedIdx = wantedClip ? WORKSPACE_CLIPS.findIndex((c) => c.id === wantedClip) : 0;
    state.activeIdx = wantedIdx >= 0 ? wantedIdx : 0;

    setSubStyle(state.subStyle);
    setSubSize(state.subSize);
    setSubPos(state.subPos);
    if (WORKSPACE_CLIPS.length) {
      selectWorkspaceClip(state.activeIdx);
    } else {
      showToast('No video clips found in this project');
    }
  } catch (err) {
    showToast(err.message || 'Could not load project');
  }
  if (window.lucide) lucide.createIcons();
  requestAnimationFrame(tick);
}

init();
