/* Copyright (C) 2026 Miqdad
 * SPDX-License-Identifier: AGPL-3.0-or-later
 *
 * Isolated frontend controller for Luna Studio (/studio/{project_id}).
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
  mode: document.body?.dataset?.studioMode === 'full_video' ? 'full_video' : 'ai_clip',
  activeIdx: 0,
  currentTime: 0,
  playing: false,
  muted: false,
  rightTab: 'subtitle',
  fvRightTab: 'basic',
  selectedTrack: 'video',
  selectedSegIdx: 0,
  selectedAudioId: null,
  playingSegIdx: 0,
  cropLocked: false,
  tlZoom: 1,
  tlFitContent: false,
  snapEnabled: true,
  lastPrevClickAt: 0,
  fvHistory: [],
  fvFuture: [],
  subStyle: 'none',
  subSize: 'medium',
  customScale: 100,
  subPos: 'bottom',
  posX: 50,
  posY: 78,
  draftMusic: null,
  editingAudioClipId: null,
  modalPlaying: false,
  modalZoom: 1,
  exporting: false,
  extractingAudio: false,
};

function isFullVideoMode() {
  return state.mode === 'full_video';
}

function makeDefaultSegment(start, end) {
  const ss = Math.max(0, Number(start) || 0);
  const se = Math.max(ss + 0.25, Number(end) || ss + 1);
  return {
    id: `seg_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 5)}`,
    sourceStart: Number(ss.toFixed(3)),
    sourceEnd: Number(se.toFixed(3)),
    volume: 100,
    speedMode: 'normal',
    speed: 1.0,
    curvePreset: 'none',
    curvePoints: [1.0, 1.0, 1.0, 1.0, 1.0],
    curvePositions: [0.0, 0.25, 0.5, 0.75, 1.0],
    cropX: 50,
    cropY: 50,
  };
}

function sanitizeCurvePoints(pts) {
  if (!Array.isArray(pts) || pts.length !== 5) return [1.0, 1.0, 1.0, 1.0, 1.0];
  return pts.map((v) => Number(Math.max(0.25, Math.min(4.0, Number(v) || 1.0)).toFixed(2)));
}

function sanitizeCurvePositions(pos) {
  const def = [0.0, 0.25, 0.5, 0.75, 1.0];
  if (!Array.isArray(pos) || pos.length !== 5) return def;
  const out = pos.map((v, i) => {
    const n = Number(v);
    return Number.isFinite(n) ? Math.max(0, Math.min(1, n)) : def[i];
  });
  out[0] = 0.0;
  out[4] = 1.0;
  for (let i = 1; i <= 3; i++) {
    const lo = out[i - 1] + 0.04;
    const hi = 1.0 - (4 - i) * 0.04;
    out[i] = Number(Math.max(lo, Math.min(hi, out[i])).toFixed(4));
  }
  return out;
}

function sanitizeAudioKeyframes(kfs, maxSpan) {
  if (!Array.isArray(kfs) || !kfs.length) return [];
  const span = Math.max(0.15, Number(maxSpan) || 0.15);
  const pts = [];
  kfs.slice(0, 32).forEach((k) => {
    if (!k || typeof k !== 'object') return;
    const t = Math.max(0, Math.min(span, Number(k.t) || 0));
    const vol = Math.max(0, Math.min(100, Math.round((Number(k.vol) ?? 35) * 10) / 10));
    pts.push({ t: Number(t.toFixed(3)), vol: Number(vol.toFixed(1)) });
  });
  pts.sort((a, b) => a.t - b.t);
  const dedup = [];
  for (const p of pts) {
    if (dedup.length && Math.abs(p.t - dedup[dedup.length - 1].t) < 0.02) {
      dedup[dedup.length - 1] = p;
    } else {
      dedup.push(p);
    }
  }
  return dedup;
}

function getAudioClipSpan(ac) {
  if (!ac) return 0;
  return Math.max(0.15, (Number(ac.trimEnd) || 0) - (Number(ac.trimStart) || 0));
}

function makeAudioClip(opts) {
  const sourceDur = Math.max(0.2, Number(opts.sourceDur) || Number(opts.totalDur) || 1);
  const trimStart = Math.max(0, Math.min(sourceDur - 0.15, Number(opts.trimStart) || 0));
  const rawEnd = opts.trimEnd !== undefined && opts.trimEnd !== null ? Number(opts.trimEnd) : sourceDur;
  const trimEnd = Math.min(sourceDur, Math.max(trimStart + 0.15, rawEnd));
  const span = trimEnd - trimStart;
  const maxFade = Number((span / 2).toFixed(2));
  return {
    id: String(opts.id || `aud_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 5)}`),
    name: String(opts.name || opts.assetName || 'Music'),
    assetName: String(opts.assetName || ''),
    url: String(opts.url || ''),
    track: Math.max(0, Math.min(7, Math.round(Number(opts.track) || 0))),
    sourceDur: Number(sourceDur.toFixed(3)),
    timelineStart: Number(Math.max(0, Number(opts.timelineStart) || 0).toFixed(3)),
    trimStart: Number(trimStart.toFixed(3)),
    trimEnd: Number(trimEnd.toFixed(3)),
    volume: Math.max(0, Math.min(100, Math.round(typeof opts.volume === 'number' ? opts.volume : 35))),
    fadeIn: Number(Math.max(0, Math.min(maxFade, Number(opts.fadeIn) || 0)).toFixed(2)),
    fadeOut: Number(Math.max(0, Math.min(maxFade, Number(opts.fadeOut) || 0)).toFixed(2)),
    keyframes: sanitizeAudioKeyframes(opts.keyframes, span),
    peaks: Array.isArray(opts.peaks) ? opts.peaks : [],
  };
}

function ensureFullVideoDefaults(c) {
  if (!c) return c;
  if (!c.cropRatio) c.cropRatio = 'original';
  if (typeof c.fade !== 'number') c.fade = 0;
  if (!c.color || typeof c.color !== 'object') {
    c.color = { preset: 'natural', brightness: 0, contrast: 0, saturation: 0, exposure: 0, warmth: 0, sharpness: 0, vignette: 0 };
  } else {
    c.color.preset = c.color.preset || 'natural';
    c.color.brightness = Number(c.color.brightness) || 0;
    c.color.contrast = Number(c.color.contrast) || 0;
    c.color.saturation = Number(c.color.saturation) || 0;
    c.color.exposure = Number(c.color.exposure) || 0;
    c.color.warmth = Number(c.color.warmth) || 0;
    c.color.sharpness = Math.max(0, Number(c.color.sharpness) || 0);
    c.color.vignette = Math.max(0, Number(c.color.vignette) || 0);
  }
  if (!c.audioEnhance || typeof c.audioEnhance !== 'object') {
    c.audioEnhance = { normalize: false, denoise: false, autoDuck: false };
  } else {
    c.audioEnhance = {
      normalize: !!c.audioEnhance.normalize,
      denoise: !!c.audioEnhance.denoise,
      autoDuck: !!c.audioEnhance.autoDuck,
    };
  }
  const maxDur = Math.max(0.5, Number(c.dur) || Number(c.end) || 1);
  if (!Array.isArray(c.segments) || !c.segments.length) {
    c.segments = [makeDefaultSegment(c.start || 0, c.end || maxDur)];
  } else {
    for (let i = c.segments.length - 1; i >= 0; i--) {
      const s = c.segments[i];
      if (!s || typeof s !== 'object') {
        c.segments.splice(i, 1);
        continue;
      }
      const ss = Math.max(0, Math.min(maxDur - 0.2, Number(s.sourceStart) || 0));
      const se = Math.min(maxDur, Math.max(ss + 0.2, Number(s.sourceEnd) || maxDur));
      s.id = String(s.id || `seg_${i + 1}`);
      s.sourceStart = Number(ss.toFixed(3));
      s.sourceEnd = Number(se.toFixed(3));
      s.volume = Math.max(0, Math.min(100, Math.round(typeof s.volume === 'number' ? s.volume : 100)));
      s.speedMode = s.speedMode === 'curve' ? 'curve' : 'normal';
      s.speed = Number(Math.max(0.25, Math.min(4.0, Number(s.speed) || 1.0)).toFixed(2));
      s.curvePreset = ['none', 'dip', 'pulse', 'fast_in', 'custom'].includes(s.curvePreset) ? s.curvePreset : 'none';
      s.curvePoints = sanitizeCurvePoints(s.curvePoints);
      s.curvePositions = sanitizeCurvePositions(s.curvePositions);
      s.cropX = Number(Math.max(0, Math.min(100, typeof s.cropX === 'number' ? s.cropX : 50)).toFixed(1));
      s.cropY = Number(Math.max(0, Math.min(100, typeof s.cropY === 'number' ? s.cropY : 50)).toFixed(1));
    }
    if (!c.segments.length) c.segments = [makeDefaultSegment(0, maxDur)];
  }

  if (!Array.isArray(c.audioClips)) {
    c.audioClips = [];
    if (isFullVideoMode() && c.music && c.music.assetName && (Number(c.music.totalDur) || 0) > 0.15) {
      const sd = Number(c.music.totalDur);
      const sl = Math.max(0, Math.min(sd - 0.15, Number(c.music.sliceStart) || 0));
      c.audioClips.push(makeAudioClip({
        id: 'aud_1',
        name: c.music.name,
        assetName: c.music.assetName,
        url: c.music.url,
        track: 0,
        sourceDur: sd,
        timelineStart: 0,
        trimStart: sl,
        trimEnd: Math.min(sd, sl + maxDur),
        volume: c.music.volume,
        fadeIn: 0,
        fadeOut: 0,
        keyframes: [],
        peaks: c.music.peaks || [],
      }));
    }
  } else {
    for (let i = c.audioClips.length - 1; i >= 0; i--) {
      const ac = c.audioClips[i];
      if (!ac || typeof ac !== 'object' || !ac.assetName) {
        c.audioClips.splice(i, 1);
        continue;
      }
      const norm = makeAudioClip(ac);
      Object.assign(ac, norm);
    }
    c.audioClips.sort((a, b) => (a.track - b.track) || (a.timelineStart - b.timelineStart));
  }
  if (typeof c.origMuted !== 'boolean') c.origMuted = Boolean(c.muted);
  return c;
}

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
    clips: WORKSPACE_CLIPS.map((c) => {
      ensureFullVideoDefaults(c);
      return {
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
        audioClips: isFullVideoMode() ? (c.audioClips || []).map((ac) => ({
          id: ac.id,
          name: ac.name,
          assetName: ac.assetName,
          track: ac.track || 0,
          sourceDur: ac.sourceDur,
          timelineStart: ac.timelineStart,
          trimStart: ac.trimStart,
          trimEnd: ac.trimEnd,
          volume: ac.volume,
          fadeIn: ac.fadeIn,
          fadeOut: ac.fadeOut,
          keyframes: ac.keyframes || [],
          peaks: ac.peaks || [],
        })) : undefined,
        cropRatio: c.cropRatio,
        fade: c.fade,
        color: c.color,
        origMuted: Boolean(c.origMuted),
        audioEnhance: c.audioEnhance || { normalize: false, denoise: false, autoDuck: false },
        segments: c.segments,
      };
    }),
  };
}

let autoSaveTimer = null;
let preRenderTimer = null;
let activePreRenderClipId = null;

function cancelBackgroundPreRender(useBeacon = false) {
  clearTimeout(preRenderTimer);
  preRenderTimer = null;
  if (!PROJECT_ID || !activePreRenderClipId) return;
  const url = `/api/studio/${encodeURIComponent(PROJECT_ID)}/prerender/${encodeURIComponent(activePreRenderClipId)}/cancel`;
  activePreRenderClipId = null;
  if (useBeacon && navigator.sendBeacon) {
    try { navigator.sendBeacon(url, ''); } catch (_) {}
    return;
  }
  fetch(url, { method: 'POST' }).catch(() => {});
}

function clipNeedsBackgroundPreRender(clip) {
  if (!clip || !isFullVideoMode()) return false;
  if (clip.cropRatio && clip.cropRatio !== 'original') return true;
  if ((Number(clip.fade) || 0) > 0) return true;
  const col = clip.color || {};
  if ((col.preset && col.preset !== 'natural')
    || (Number(col.brightness) || 0) !== 0
    || (Number(col.contrast) || 0) !== 0
    || (Number(col.saturation) || 0) !== 0
    || (Number(col.exposure) || 0) !== 0
    || (Number(col.warmth) || 0) !== 0
    || (Number(col.sharpness) || 0) !== 0
    || (Number(col.vignette) || 0) !== 0) {
    return true;
  }
  const segs = Array.isArray(clip.segments) ? clip.segments : [];
  return segs.some((s) => isSegmentSpeedActive(s));
}

function scheduleBackgroundPreRender() {
  clearTimeout(preRenderTimer);
  preRenderTimer = null;
  if (!PROJECT_ID || !isFullVideoMode() || state.exporting) return;
  const clip = activeClip();
  if (!clip || !clipNeedsBackgroundPreRender(clip)) return;
  preRenderTimer = setTimeout(() => {
    if (state.exporting || !isFullVideoMode()) return;
    if (videoEl && !videoEl.paused) {
      // Defer quietly until playback pauses so scrubbing/preview stays silky smooth
      scheduleBackgroundPreRender();
      return;
    }
    const cur = ensureFullVideoDefaults(activeClip());
    if (!cur || !clipNeedsBackgroundPreRender(cur)) return;
    activePreRenderClipId = cur.id;
    fetch(
      `/api/studio/${encodeURIComponent(PROJECT_ID)}/prerender/${encodeURIComponent(cur.id)}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ payload: buildClipExportBody(cur) }),
      }
    ).catch(() => {});
  }, 4000);
}

window.addEventListener('beforeunload', () => {
  if ((autoSaveTimer !== null || draftSaveDirty) && PROJECT_ID && WORKSPACE_CLIPS.length) {
    clearTimeout(autoSaveTimer);
    autoSaveTimer = null;
    draftSaveDirty = false;
    try {
      fetch(`/api/studio/${encodeURIComponent(PROJECT_ID)}/save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildPersistPayload()),
        keepalive: true,
      }).catch(() => {});
    } catch (_) {}
  }
  cancelBackgroundPreRender(true);
});

let draftSaveInFlight = false;
let draftSaveDirty = false;
let draftSaveWantToast = false;
let draftSaveWaiters = [];

function scheduleDraftSave() {
  clearTimeout(autoSaveTimer);
  draftSaveDirty = true;
  cancelBackgroundPreRender(false);
  autoSaveTimer = setTimeout(() => {
    autoSaveTimer = null;
    persistDraftToServer(false);
    scheduleBackgroundPreRender();
  }, 600);
}

async function persistDraftToServer(showNotification = false) {
  if (!PROJECT_ID || !WORKSPACE_CLIPS.length) return false;
  clearTimeout(autoSaveTimer);
  autoSaveTimer = null;
  if (showNotification) draftSaveWantToast = true;
  if (draftSaveInFlight) {
    draftSaveDirty = true;
    return new Promise((resolve) => draftSaveWaiters.push(resolve));
  }
  draftSaveInFlight = true;
  let lastOk = true;
  try {
    do {
      draftSaveDirty = false;
      const notifyThisRound = draftSaveWantToast;
      draftSaveWantToast = false;
      try {
        const res = await fetch(`/api/studio/${encodeURIComponent(PROJECT_ID)}/save`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(buildPersistPayload()),
        });
        if (!res.ok) throw new Error('Failed to save');
        lastOk = true;
        if (notifyThisRound && !draftSaveDirty) {
          const clip = activeClip();
          const m = activeMusic();
          const musicText = m ? ` · Music: ${m.name}` : '';
          if (isFullVideoMode()) {
            const layout = computeTimelineLayout(clip);
            const segCount = (clip.segments || []).length;
            const segText = segCount > 1 ? ` · ${segCount} clips` : '';
            const acCount = (clip.audioClips || []).length;
            const fvMusicText = acCount > 0 ? ` · ${acCount} audio` : '';
            showToast(`Saved ${clip.name} (${fmtMMSS(layout.totalDur)}${segText}${fvMusicText})`);
          } else {
            const subText = state.subStyle === 'none' ? 'No subtitle' : `Subtitle: ${state.subStyle}`;
            showToast(`Saved ${clip.name} (${fmtMMSS(clip.start)}–${fmtMMSS(clip.end)}, ${subText}${musicText})`);
          }
        }
      } catch (err) {
        lastOk = false;
        if (notifyThisRound) showToast('Could not save draft changes');
      }
    } while (draftSaveDirty);
    return lastOk;
  } finally {
    draftSaveInFlight = false;
    const waiters = draftSaveWaiters.splice(0, draftSaveWaiters.length);
    waiters.forEach((fn) => fn(lastOk));
  }
}

function canSliceMusic(clip, m) {
  if (!clip || !m) return false;
  const musicDur = Number(m.totalDur) || 0;
  if (musicDur <= 0.1) return false;
  return musicDur > getActiveClipSpan(clip) + 0.5;
}

function getMusicTargetTime(clip, m, offsetSec) {
  const off = Math.max(0, Number(offsetSec) || 0);
  const totalDur = Number(m?.totalDur) || Number(customAudioEl.duration) || 0;
  const clipSpan = getActiveClipSpan(clip);
  if (totalDur > 0.1 && clipSpan > totalDur + 0.05) {
    return off % totalDur;
  }
  const start = Math.max(0, Number(m?.sliceStart) || 0);
  if (totalDur > 0.1) return Math.min(totalDur, start + off);
  return start + off;
}

function activeAudioClip() {
  const clip = activeClip();
  if (!clip || !isFullVideoMode()) return null;
  const list = clip.audioClips || [];
  if (!list.length) return null;
  return list.find((a) => a.id === state.selectedAudioId) || null;
}

const fvAudioPool = new Map();

function getFvLaneAudioEl(trackIdx) {
  if (!fvAudioPool.has(trackIdx)) {
    const el = document.createElement('audio');
    el.preload = 'auto';
    el.addEventListener('loadedmetadata', () => {
      const realDur = Number(el.duration) || 0;
      const clip = activeClip();
      const asset = el.dataset.assetName;
      if (isFullVideoMode() && clip && asset && realDur > 0.05 && Number.isFinite(realDur)) {
        let changed = false;
        (clip.audioClips || []).forEach((ac) => {
          if (ac.assetName === asset && (!(Number(ac.sourceDur) > 0.15) || Math.abs(ac.sourceDur - realDur) > 1.0)) {
            ac.sourceDur = Number(realDur.toFixed(3));
            if (ac.trimEnd > ac.sourceDur) ac.trimEnd = ac.sourceDur;
            changed = true;
          }
        });
        if (changed) renderFvAudioTrack(clip, getTimelineScaleDur(clip));
      }
      if (el.dataset.pendingSeek !== undefined) {
        const target = Number(el.dataset.pendingSeek);
        delete el.dataset.pendingSeek;
        if (Number.isFinite(target) && target >= 0) {
          try { el.currentTime = Math.min(realDur > 0.05 ? realDur - 0.01 : target, target); } catch (_) {}
        }
        if (state.playing && !isUserScrubbing && !videoEl.paused && !videoEl.seeking && !videoEl.ended && videoEl.readyState >= 3) {
          syncMusicTimeToVideo(true);
        }
      }
    });
    fvAudioPool.set(trackIdx, el);
  }
  return fvAudioPool.get(trackIdx);
}

function pauseAllFvAudioPlayers() {
  fvAudioPool.forEach((el) => {
    if (!el.paused) el.pause();
  });
}

function findAudioClipsAt(clip, tlSec) {
  if (!clip || !isFullVideoMode()) return [];
  const t = Math.max(0, Number(tlSec) || 0);
  const byTrack = new Map();
  (clip.audioClips || []).forEach((ac) => {
    const span = getAudioClipSpan(ac);
    if (t >= ac.timelineStart - 0.005 && t < ac.timelineStart + span - 0.015) {
      const lane = ac.track || 0;
      if (!byTrack.has(lane)) byTrack.set(lane, ac);
    }
  });
  return Array.from(byTrack.values());
}

function findAudioClipAt(clip, tlSec) {
  const hits = findAudioClipsAt(clip, tlSec);
  return hits.length ? hits[0] : null;
}

function evalAudioVolumeAt(ac, localT) {
  if (!ac) return 0;
  const kfs = ac.keyframes || [];
  if (!kfs.length) return Math.max(0, Math.min(100, Number(ac.volume) ?? 35));
  if (kfs.length === 1) return Math.max(0, Math.min(100, Number(kfs[0].vol) ?? 35));
  const t = Math.max(0, Number(localT) || 0);
  if (t <= kfs[0].t) return kfs[0].vol;
  const last = kfs[kfs.length - 1];
  if (t >= last.t) return last.vol;
  for (let i = 0; i < kfs.length - 1; i++) {
    const a = kfs[i];
    const b = kfs[i + 1];
    if (t >= a.t && t <= b.t) {
      const dt = Math.max(0.0005, b.t - a.t);
      const frac = (t - a.t) / dt;
      return a.vol + (b.vol - a.vol) * frac;
    }
  }
  return last.vol;
}

function evalAudioGainAt(ac, localT) {
  if (!ac) return 0;
  const span = getAudioClipSpan(ac);
  const t = Math.max(0, Math.min(span, Number(localT) || 0));
  let gain = evalAudioVolumeAt(ac, t) / 100;
  const fi = Math.max(0, Number(ac.fadeIn) || 0);
  const fo = Math.max(0, Number(ac.fadeOut) || 0);
  if (fi > 0.01 && t < fi) gain *= Math.max(0, t / fi);
  if (fo > 0.01 && (span - t) < fo) gain *= Math.max(0, (span - t) / fo);
  return Math.max(0, Math.min(1, gain));
}

function syncClipAudioElement() {
  const clip = activeClip();
  if (isFullVideoMode()) {
    const list = clip?.audioClips || [];
    const lbl = document.getElementById('customAudioLabel');
    if (lbl) {
      lbl.textContent = list.length === 0 ? 'Add Music' : (list.length === 1 ? list[0].name : `Music (${list.length})`);
    }
    const usedLanes = new Set(list.map((a) => a.track || 0));
    fvAudioPool.forEach((el, lane) => {
      if (!usedLanes.has(lane)) {
        el.pause();
        el.removeAttribute('src');
        delete el.dataset.assetName;
      }
    });
    usedLanes.forEach((lane) => {
      const laneClips = list.filter((a) => (a.track || 0) === lane);
      const activeAtNow = laneClips.find((ac) => {
        const sp = getAudioClipSpan(ac);
        return state.currentTime >= ac.timelineStart - 0.005 && state.currentTime < ac.timelineStart + sp - 0.015;
      }) || laneClips[0];
      if (!activeAtNow || !activeAtNow.url) return;
      const el = getFvLaneAudioEl(lane);
      const resolved = encodeMediaUrl(activeAtNow.url);
      if (el.getAttribute('src') !== resolved) {
        el.src = resolved;
        el.dataset.assetName = activeAtNow.assetName || '';
        el.load();
      }
      el.loop = false;
      const sp = getAudioClipSpan(activeAtNow);
      if (state.currentTime >= activeAtNow.timelineStart - 0.005 && state.currentTime < activeAtNow.timelineStart + sp - 0.015) {
        const localT = Math.max(0, state.currentTime - activeAtNow.timelineStart);
        el.volume = state.muted ? 0 : evalAudioGainAt(activeAtNow, localT);
      } else {
        el.pause();
      }
    });
    return;
  }

  const m = activeMusic();
  document.getElementById('customAudioLabel').textContent = m ? m.name : 'Add Music';
  if (m && m.url) {
    const resolved = encodeMediaUrl(m.url);
    if (customAudioEl.getAttribute('src') !== resolved) {
      customAudioEl.src = resolved;
      customAudioEl.load();
    }
    const totalDur = Number(m.totalDur) || 0;
    customAudioEl.loop = Boolean(clip && totalDur > 0.1 && getActiveClipSpan(clip) > totalDur + 0.05);
    customAudioEl.volume = state.muted ? 0 : m.volume / 100;
  } else {
    customAudioEl.loop = false;
    customAudioEl.pause();
    customAudioEl.removeAttribute('src');
  }
}

customAudioEl.addEventListener('loadedmetadata', () => {
  if (isFullVideoMode()) return;
  const realDur = Number(customAudioEl.duration) || 0;
  if (!(realDur > 0.05) || !Number.isFinite(realDur)) return;
  const clip = activeClip();
  const m = activeMusic();
  if (m && (!(Number(m.totalDur) > 0.1) || Math.abs(m.totalDur - realDur) > 1.0)) {
    m.totalDur = Number(realDur.toFixed(3));
    if (clip && !canSliceMusic(clip, m)) m.sliceStart = 0;
    customAudioEl.loop = Boolean(clip && getActiveClipSpan(clip) > m.totalDur + 0.05);
    renderTracks();
  }
});

function selectWorkspaceClip(idx) {
  if (!WORKSPACE_CLIPS[idx]) return;
  cancelBackgroundPreRender(false);
  state.activeIdx = idx;
  state.playing = false;
  state.selectedTrack = 'video';
  state.selectedSegIdx = 0;
  state.selectedAudioId = null;
  state.playingSegIdx = 0;
  state.cropLocked = false;
  state.tlZoom = 1;
  state.tlFitContent = false;
  syncFvFitButton();
  const zSlider = document.getElementById('tlZoomSlider');
  const zFit = document.getElementById('btnTlZoomFit');
  if (zSlider) zSlider.value = '1';
  if (zFit) {
    zFit.textContent = '1x';
    zFit.classList.remove('text-white', 'font-medium');
    zFit.classList.add('text-neutral-400');
  }
  state.fvHistory = [];
  state.fvFuture = [];
  fvFrameCache.clear();
  clearTimeout(fvThumbDecodeScheduled);
  fvThumbDecodeScheduled = null;
  videoSeekBusy = false;
  pendingVideoSeekTime = null;
  pendingPlayAfterSeek = false;
  isUserScrubbing = false;
  closeMusicPopover();
  videoEl.pause();
  customAudioEl.pause();
  pauseAllFvAudioPlayers();
  const clip = ensureFullVideoDefaults(activeClip());
  const capBox = document.getElementById('captionBox');
  const titleInp = document.getElementById('clipTitleInput');
  const tagsInp = document.getElementById('clipTagsInput');
  if (capBox) capBox.value = clip.caption || '';
  if (titleInp) titleInp.value = clip.title || '';
  if (tagsInp) tagsInp.value = clip.tags || '';
  updateCaptionCharCount();
  syncClipAudioElement();
  const initSeg = clip.segments[0];
  syncAudioMuteState();
  const srcUrl = encodeMediaUrl(clip.src);
  videoEl.src = srcUrl;
  videoEl.load();
  thumbVideoEl.src = srcUrl;
  thumbVideoEl.load();
  state.currentTime = isFullVideoMode() ? 0 : (clip.start || 0);
  renderWorkspaceClips();
  if (isFullVideoMode()) {
    syncFullVideoPanels();
    applyStageAspectAndFilters();
    applyLivePlaybackSpeed();
    updateFvToolbarState();
  }
  renderRuler();
  renderTracks();
  updateSubtitleOverlay();
  updatePlayhead();
  updatePlayIcon();
}

videoEl.addEventListener('loadedmetadata', () => {
  const clip = activeClip();
  if (!clip) return;
  const oldDur = clip.dur || 0;
  const realDur = Math.max(1, videoEl.duration || clip.dur || 1);
  if (!clip.end || clip.end >= oldDur - 0.2 || clip.end > realDur) clip.end = realDur;
  clip.dur = realDur;
  if (isFullVideoMode()) {
    ensureFullVideoDefaults(clip);
    if (
      clip.segments.length === 1 &&
      clip.segments[0].sourceStart <= 0.05 &&
      Math.abs(clip.segments[0].sourceEnd - oldDur) <= 0.25
    ) {
      clip.segments[0].sourceEnd = Number(realDur.toFixed(3));
    } else {
      clip.segments.forEach((s) => {
        s.sourceStart = Math.max(0, Math.min(realDur - 0.2, s.sourceStart));
        s.sourceEnd = Math.min(realDur, Math.max(s.sourceStart + 0.2, s.sourceEnd));
      });
    }
    const mapped = timelineToSource(clip, state.currentTime);
    state.playingSegIdx = mapped.segIdx;
    videoEl.currentTime = mapped.srcTime;
    applyStageAspectAndFilters();
    applyLivePlaybackSpeed();
    syncFullVideoPanels();
  } else {
    if (videoEl.videoWidth > 0 && videoEl.videoHeight > 0) {
      const frameBox = document.getElementById('mediaFrameBox');
      frameBox.style.aspectRatio = `${videoEl.videoWidth} / ${videoEl.videoHeight}`;
      const isLandscape = videoEl.videoWidth > videoEl.videoHeight;
      frameBox.classList.toggle('w-full', isLandscape);
      frameBox.classList.toggle('h-full', !isLandscape);
    }
    videoEl.currentTime = clip.start || 0;
  }
  renderRuler();
  renderTracks();
  updatePlayhead();
  updateSubtitleOverlay();
});

let thumbGenToken = 0;
const fvFrameCache = new Map();
const FV_FRAME_CACHE_MAX = 180;
let fvThumbDecodeScheduled = null;
let fvScrollPaintRaf = 0;

function quantizeThumbTime(sec, dur) {
  const safeDur = Math.max(0.1, Number(dur) || 1);
  const clamped = Math.max(0, Math.min(safeDur - 0.04, Number(sec) || 0));
  return Number((Math.round(clamped * 2) / 2).toFixed(1));
}

function captureThumbFrameCanvas(vid) {
  const vw = vid.videoWidth || 160;
  const vh = vid.videoHeight || 90;
  const maxW = 144;
  const maxH = 84;
  const scale = Math.min(maxW / vw, maxH / vh, 1);
  const cw = Math.max(24, Math.round(vw * scale));
  const ch = Math.max(24, Math.round(vh * scale));
  const c = document.createElement('canvas');
  c.width = cw;
  c.height = ch;
  const ctx = c.getContext('2d');
  if (ctx) {
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(vid, 0, 0, cw, ch);
  }
  return c;
}

function putFvFrameCache(qKey, frameCanvas) {
  if (fvFrameCache.has(qKey)) fvFrameCache.delete(qKey);
  fvFrameCache.set(qKey, frameCanvas);
  while (fvFrameCache.size > FV_FRAME_CACHE_MAX) {
    const oldestKey = fvFrameCache.keys().next().value;
    fvFrameCache.delete(oldestKey);
  }
}

function getNearestFvCachedFrame(targetSec) {
  if (!fvFrameCache.size) return null;
  let best = null;
  let bestDist = Infinity;
  fvFrameCache.forEach((canvas, tKey) => {
    const d = Math.abs(tKey - targetSec);
    if (d < bestDist) {
      bestDist = d;
      best = canvas;
    }
  });
  return best;
}

function drawCoverFrameToTile(ctx, srcCanvas, dx, dy, dw, dh) {
  const sw0 = srcCanvas.width || 1;
  const sh0 = srcCanvas.height || 1;
  const srcAspect = sw0 / sh0;
  const dstAspect = dw / Math.max(1, dh);
  let sx = 0, sy = 0, sw = sw0, sh = sh0;
  if (srcAspect > dstAspect) {
    sw = sh0 * dstAspect;
    sx = (sw0 - sw) / 2;
  } else {
    sh = sw0 / dstAspect;
    sy = Math.max(0, (sh0 - sh) * 0.22);
  }
  ctx.drawImage(srcCanvas, sx, sy, sw, sh, dx, dy, dw, dh);
}

async function decodeFvThumbTimes(timesList, token) {
  const dur = thumbVideoEl.duration;
  if (!dur || Number.isNaN(dur) || thumbVideoEl.readyState < 1) return;
  let decoded = 0;
  for (let i = 0; i < timesList.length; i++) {
    if (token !== thumbGenToken) return;
    const qKey = timesList[i];
    if (fvFrameCache.has(qKey)) continue;
    const target = Math.max(0, Math.min(dur - 0.04, qKey));
    await new Promise((res) => {
      const timer = setTimeout(res, 750);
      const onSeeked = () => {
        clearTimeout(timer);
        thumbVideoEl.removeEventListener('seeked', onSeeked);
        try {
          if (token === thumbGenToken && thumbVideoEl.readyState >= 2) {
            putFvFrameCache(qKey, captureThumbFrameCanvas(thumbVideoEl));
            decoded += 1;
            if (decoded % 2 === 0 || i === timesList.length - 1) {
              paintFvBlockFilmstrips(false);
            }
          }
        } catch (_) {}
        res();
      };
      thumbVideoEl.addEventListener('seeked', onSeeked, { once: true });
      try {
        thumbVideoEl.currentTime = target;
      } catch (_) {
        clearTimeout(timer);
        thumbVideoEl.removeEventListener('seeked', onSeeked);
        res();
      }
    });
  }
  if (token === thumbGenToken && decoded > 0) {
    paintFvBlockFilmstrips(false);
  }
}

function scheduleFvVisibleThumbDecode(neededTimes) {
  if (!neededTimes || !neededTimes.length || !isFullVideoMode()) return;
  clearTimeout(fvThumbDecodeScheduled);
  const unique = Array.from(new Set(neededTimes)).sort((a, b) => a - b).slice(0, 32);
  fvThumbDecodeScheduled = setTimeout(() => {
    const token = ++thumbGenToken;
    decodeFvThumbTimes(unique, token);
  }, 60);
}

async function preloadFvBackendFilmstrip(clip, token) {
  if (!PROJECT_ID || !clip?.id || !isFullVideoMode()) return false;
  try {
    const res = await fetch(
      `/api/studio/${encodeURIComponent(PROJECT_ID)}/filmstrip/${encodeURIComponent(clip.id)}`
    );
    if (!res.ok || token !== thumbGenToken) return false;
    const meta = await res.json();
    if (!meta?.ok || !meta.url || !Array.isArray(meta.times) || !meta.times.length) return false;
    const img = await new Promise((resolve) => {
      const el = new Image();
      el.crossOrigin = 'anonymous';
      el.onload = () => resolve(el);
      el.onerror = () => resolve(null);
      el.src = meta.url;
    });
    if (!img || token !== thumbGenToken) return false;
    const cols = Math.max(1, Number(meta.cols) || 6);
    const tileW = Math.max(16, Number(meta.tileW) || 160);
    const tileH = Math.max(16, Number(meta.tileH) || 90);
    const dur = Math.max(0.1, Number(meta.dur) || Number(clip.dur) || 1);
    for (let i = 0; i < meta.times.length; i++) {
      const col = i % cols;
      const row = Math.floor(i / cols);
      const sx = col * tileW;
      const sy = row * tileH;
      if (sx + tileW > img.naturalWidth + 1 || sy + tileH > img.naturalHeight + 1) break;
      const c = document.createElement('canvas');
      c.width = tileW;
      c.height = tileH;
      const ctx = c.getContext('2d');
      if (ctx) {
        ctx.drawImage(img, sx, sy, tileW, tileH, 0, 0, tileW, tileH);
        putFvFrameCache(quantizeThumbTime(meta.times[i], dur), c);
      }
    }
    if (token === thumbGenToken && fvFrameCache.size > 0) {
      paintFvBlockFilmstrips(false);
      return true;
    }
    return false;
  } catch (_) {
    return false;
  }
}

thumbVideoEl.addEventListener('loadedmetadata', async () => {
  const token = ++thumbGenToken;
  const dur = thumbVideoEl.duration;
  if (!dur || Number.isNaN(dur)) return;

  if (isFullVideoMode()) {
    // Fast server-cached JPEG filmstrip sprite first (zero browser seeking on long 30-60m videos)
    const loadedFromCache = await preloadFvBackendFilmstrip(activeClip(), token);
    if (token !== thumbGenToken) return;
    if (loadedFromCache) {
      paintFvBlockFilmstrips(true);
      return;
    }
    // Fallback: client-side overview decode
    const overviewCount = 16;
    const seedTimes = [];
    for (let i = 0; i < overviewCount; i++) {
      seedTimes.push(quantizeThumbTime(((i + 0.5) / overviewCount) * dur, dur));
    }
    await decodeFvThumbTimes(seedTimes, token);
    if (token === thumbGenToken) {
      paintFvBlockFilmstrips(true);
    }
    return;
  }

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

function setSubStyle(style, skipSave = false) {
  const valid = SUBTITLE_PRESETS.some((p) => p.id === style) ? style : 'none';
  state.subStyle = valid;
  const curClip = activeClip();
  if (curClip && 'subStyle' in curClip) curClip.subStyle = valid;
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
  if (!skipSave && !isOff && (!activeClip()?.cues || !activeClip().cues.length)) {
    showToast('No transcript found for this clip — type in Current Line to add subtitle');
  }
  if (!skipSave) scheduleDraftSave();
}

function setSubSize(sz, skipSave = false) {
  state.subSize = sz;
  document.querySelectorAll('.size-chip').forEach((c) => c.classList.toggle('is-active', c.dataset.size === sz));
  document.getElementById('customScaleWrap').classList.toggle('hidden', sz !== 'custom');
  document.getElementById('customScaleSlider').value = state.customScale;
  document.getElementById('customScaleLabel').textContent = String(state.customScale);
  updateSubtitleOverlay();
  if (!skipSave) scheduleDraftSave();
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

function setSubPos(pos, skipSave = false) {
  state.subPos = pos;
  document.querySelectorAll('.pos-chip').forEach((c) => c.classList.toggle('is-active', c.dataset.pos === pos));
  document.getElementById('customXYWrap').classList.toggle('hidden', pos !== 'custom');
  document.getElementById('posXSlider').value = Math.round(state.posX);
  document.getElementById('posYSlider').value = Math.round(state.posY);
  document.getElementById('posXLabel').textContent = `${Math.round(state.posX)}%`;
  document.getElementById('posYLabel').textContent = `${Math.round(state.posY)}%`;
  updateSubtitleOverlay();
  if (!skipSave) scheduleDraftSave();
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
  if (isFullVideoMode()) {
    box?.classList.add('hidden');
    return;
  }
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
  if (btn) setLunaTooltip(btn, stageExpanded ? 'Exit full size' : 'Full size preview');
  if (window.lucide) lucide.createIcons();
  applyStageAspectAndFilters();
  updateSubtitleOverlay(true);
}

let stageResizeTimer = null;
window.addEventListener('resize', () => {
  clearTimeout(stageResizeTimer);
  stageResizeTimer = setTimeout(() => {
    applyStageAspectAndFilters();
    if (isFullVideoMode() && activeClip()) {
      renderRuler();
      updatePlayhead();
      paintFvBlockFilmstrips(true);
    }
  }, 60);
});

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

function getActiveClipSpan(clip) {
  if (!clip) return 1;
  if (isFullVideoMode()) return Math.max(0.5, computeTimelineLayout(clip).totalDur);
  return Math.max(1, (clip.end || clip.dur || 1) - (clip.start || 0));
}

function pickRulerStep(dur, trackPx) {
  const targetPxPerTick = 92;
  const maxTicks = Math.max(4, Math.floor(trackPx / targetPxPerTick));
  const rawStep = dur / maxTicks;
  const niceSteps = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 180, 300, 600, 900];
  for (const s of niceSteps) {
    if (s >= rawStep) return s;
  }
  return Math.ceil(rawStep / 60) * 60;
}

function getTimelineScaleDur(clip) {
  if (!clip) return 1;
  if (!isFullVideoMode()) return Math.max(1, Number(clip.dur) || 1);
  const videoDur = computeTimelineLayout(clip).totalDur;
  const audioMaxEnd = (clip.audioClips || []).reduce(
    (mx, ac) => Math.max(mx, (Number(ac.timelineStart) || 0) + getAudioClipSpan(ac)),
    0
  );
  const contentDur = Math.max(0.5, videoDur, audioMaxEnd);
  if (state.tlFitContent) {
    return contentDur;
  }
  return Math.max(0.5, Number(clip.dur) || 0.5, contentDur);
}

function syncFvFitButton() {
  const btn = document.getElementById('btnFvFitTimeline');
  if (!btn) return;
  const active = !!state.tlFitContent;
  btn.classList.toggle('is-active', active);
  setLunaTooltip(
    btn,
    active ? 'Full timeline scale' : 'Fit to content'
  );
}

function toggleFvFitTimeline(forceVal = null) {
  if (!isFullVideoMode()) return;
  const clip = activeClip();
  if (!clip) return;
  const next = typeof forceVal === 'boolean' ? forceVal : !state.tlFitContent;
  state.tlFitContent = next;
  syncFvFitButton();
  setTimelineZoom(1);
  renderFvTracks(clip);
  renderRuler();
  updatePlayhead();
  if (forceVal === null) {
    showToast(next ? 'Timeline fitted to content' : 'Timeline set to full length', 1800);
  }
}

function setTimelineEditingIndicator(active) {
  document.getElementById('playhead')?.classList.toggle('is-editing-clip', Boolean(active));
}

function showTlSnapGuide(sec, scaleDur) {
  const el = document.getElementById('tlSnapGuideLine');
  if (!el || !(scaleDur > 0)) return;
  const pct = Math.max(0, Math.min(100, (sec / scaleDur) * 100));
  el.style.left = `${pct.toFixed(4)}%`;
  el.style.display = 'block';
}

function hideTlSnapGuide() {
  const el = document.getElementById('tlSnapGuideLine');
  if (el) el.style.display = 'none';
}

function toggleFvSnapping() {
  state.snapEnabled = !state.snapEnabled;
  const btn = document.getElementById('btnFvSnapToggle');
  if (btn) {
    btn.classList.toggle('is-active', state.snapEnabled);
    setLunaTooltip(btn, state.snapEnabled ? 'Snapping: ON' : 'Snapping: OFF');
  }
  if (!state.snapEnabled) hideTlSnapGuide();
  showToast(state.snapEnabled ? 'Snapping ON' : 'Snapping OFF');
}

function collectTimelineSnapTargets(clip, excludeAudioId = null) {
  const layout = computeTimelineLayout(clip);
  const targets = [0, layout.totalDur, state.currentTime];
  layout.items.forEach((it) => {
    targets.push(it.tlStart, it.tlEnd);
  });
  (clip?.audioClips || []).forEach((a) => {
    if (excludeAudioId && a.id === excludeAudioId) return;
    targets.push(a.timelineStart, a.timelineStart + getAudioClipSpan(a));
  });
  return targets;
}

function findMagneticSnap(rawSec, snapPoints, trackWidthPx, scaleDur) {
  if (!state.snapEnabled || !snapPoints || !snapPoints.length) {
    return { snapped: false, value: rawSec };
  }
  // Gentle 8px screen-space pull radius (feels consistent from 1x to 20x zoom)
  const threshSec = (8 / Math.max(200, trackWidthPx)) * Math.max(0.5, scaleDur);
  let best = null;
  let bestDist = threshSec;
  for (let i = 0; i < snapPoints.length; i++) {
    const d = Math.abs(rawSec - snapPoints[i]);
    if (d <= bestDist) {
      bestDist = d;
      best = snapPoints[i];
    }
  }
  return best !== null ? { snapped: true, value: best } : { snapped: false, value: rawSec };
}

function renderRuler() {
  const clip = activeClip();
  if (!clip) return;
  const ruler = document.getElementById('timelineRuler');
  if (!ruler) return;
  const dur = getTimelineScaleDur(clip);
  const trackEl = document.getElementById('timelineZoomTrack');
  const vpEl = document.getElementById('timelineScrollViewport');
  const zoom = isFullVideoMode() ? Math.max(1, Number(state.tlZoom) || 1) : 1;
  const trackPx = Math.max(300, (vpEl?.clientWidth || 800) * zoom);
  if (trackEl) trackEl.style.width = `${(zoom * 100).toFixed(1)}%`;

  const step = pickRulerStep(dur, trackPx);
  const useMMSS = dur >= 90 || step >= 30;
  const maxMarks = Math.min(600, Math.floor(dur / step));
  const majorPx = (step / dur) * trackPx;
  const subCount = majorPx >= 76 ? 4 : (majorPx >= 42 ? 2 : 0);

  let html = '';
  for (let i = 0; i <= maxMarks; i++) {
    const sec = Math.min(dur, i * step);
    const pct = (sec / dur) * 100;
    const isStart = pct < 0.8;
    const isEnd = pct > 98.5;
    const lblAlign = isStart ? 'left-1' : (isEnd ? 'right-1' : 'left-0 -translate-x-1/2');
    const lbl = useMMSS ? fmtMMSS(sec) : (step < 1 ? `${sec.toFixed(1)}s` : `${Math.round(sec)}s`);
    html += `<span class="absolute top-0 bottom-0 pointer-events-none" style="left: ${pct.toFixed(3)}%;">`
      + `<span class="absolute top-[1px] ${lblAlign} whitespace-nowrap tabular-nums leading-none text-neutral-400">${lbl}</span>`
      + `<span class="absolute bottom-0 left-0 w-px h-[6px] bg-white/30"></span>`
      + `</span>`;

    if (subCount > 0 && sec < dur) {
      for (let s = 1; s < subCount; s++) {
        const subSec = sec + (step * s) / subCount;
        if (subSec >= dur - 0.01) break;
        const subPct = (subSec / dur) * 100;
        const isMid = subCount === 4 && s === 2;
        const hCls = isMid ? 'h-[4px] bg-white/20' : 'h-[3px] bg-white/12';
        html += `<span class="absolute bottom-0 w-px ${hCls} pointer-events-none" style="left: ${subPct.toFixed(3)}%;"></span>`;
      }
    }
  }

  // Only show final end label if it has comfortable breathing room (>= 68px) from the last major tick
  const lastSec = maxMarks * step;
  const remPx = ((dur - lastSec) / dur) * trackPx;
  if (remPx >= 68) {
    const endLbl = useMMSS ? fmtMMSS(dur) : `${Math.round(dur)}s`;
    html += `<span class="absolute top-0 bottom-0 right-0 pointer-events-none">`
      + `<span class="absolute top-[1px] right-1 whitespace-nowrap tabular-nums leading-none text-neutral-500">${endLbl}</span>`
      + `<span class="absolute bottom-0 right-0 w-px h-[6px] bg-white/25"></span>`
      + `</span>`;
  }
  ruler.innerHTML = html;
}

const TL_ZOOM_STEPS = [1, 1.5, 2, 3, 4, 6, 8, 12, 16, 20];

function setTimelineZoom(val, anchorClientX = null) {
  if (!isFullVideoMode()) return;
  const clip = activeClip();
  if (!clip) return;
  const vp = document.getElementById('timelineScrollViewport');
  const track = document.getElementById('timelineZoomTrack');
  const oldZoom = state.tlZoom || 1;
  const nextZoom = Number(Math.max(1, Math.min(20, Number(val) || 1)).toFixed(2));
  const scaleDur = getTimelineScaleDur(clip);

  // Anchor around mouse cursor (Ctrl+Wheel) or playhead (slider/buttons)
  let anchorOffsetPx = (vp?.clientWidth || 800) / 2;
  let anchorRatio = Math.max(0, Math.min(1, state.currentTime / scaleDur));
  if (vp && anchorClientX !== null) {
    const vpRect = vp.getBoundingClientRect();
    anchorOffsetPx = Math.max(0, Math.min(vp.clientWidth, ((anchorClientX - vpRect.left) / Math.max(1, vpRect.width)) * vp.clientWidth));
    const oldTrackW = Math.max(1, vp.clientWidth * oldZoom);
    anchorRatio = Math.max(0, Math.min(1, (vp.scrollLeft + anchorOffsetPx) / oldTrackW));
  }

  state.tlZoom = nextZoom;
  if (track) track.style.width = `${(nextZoom * 100).toFixed(1)}%`;
  const slider = document.getElementById('tlZoomSlider');
  const fitBtn = document.getElementById('btnTlZoomFit');
  if (slider) slider.value = String(nextZoom);
  if (fitBtn) {
    const isZoomed = nextZoom > 1.01;
    fitBtn.textContent = isZoomed ? `${nextZoom.toFixed(nextZoom >= 10 ? 0 : 1)}x` : '1x';
    fitBtn.classList.toggle('text-white', isZoomed);
    fitBtn.classList.toggle('font-medium', isZoomed);
    fitBtn.classList.toggle('text-neutral-400', !isZoomed);
  }

  renderRuler();
  updatePlayhead();
  if (vp) {
    const newTrackW = vp.clientWidth * nextZoom;
    vp.scrollLeft = nextZoom <= 1.01 ? 0 : Math.max(0, anchorRatio * newTrackW - anchorOffsetPx);
  }
  paintFvBlockFilmstrips(true);
}

function stepTimelineZoom(dir) {
  const cur = state.tlZoom || 1;
  let target = cur;
  if (dir > 0) {
    target = TL_ZOOM_STEPS.find((z) => z > cur + 0.05) || 20;
  } else {
    for (let i = TL_ZOOM_STEPS.length - 1; i >= 0; i--) {
      if (TL_ZOOM_STEPS[i] < cur - 0.05) {
        target = TL_ZOOM_STEPS[i];
        break;
      }
    }
    if (target === cur) target = 1;
  }
  setTimelineZoom(target);
}

document.getElementById('timelineScrollViewport')?.addEventListener('scroll', () => {
  if (!isFullVideoMode()) return;
  if (!fvScrollPaintRaf) {
    fvScrollPaintRaf = requestAnimationFrame(() => {
      fvScrollPaintRaf = 0;
      paintFvBlockFilmstrips(true);
    });
  }
}, { passive: true });

document.getElementById('timelineScrollViewport')?.addEventListener('wheel', (ev) => {
  if (!isFullVideoMode()) return;
  if (ev.ctrlKey || ev.metaKey || ev.altKey) {
    ev.preventDefault();
    const factor = ev.deltaY < 0 ? 1.22 : (1 / 1.22);
    setTimelineZoom((state.tlZoom || 1) * factor, ev.clientX);
  }
}, { passive: false });

function sampleMusicSlicePeaks(peaks, totalDur, sliceStart, clipSpan, outPoints = 64) {
  if (!peaks || !peaks.length) return [];
  const dur = Math.max(0.1, totalDur || clipSpan || 1);
  const span = Math.max(0.1, clipSpan || dur);
  const loops = span > dur + 0.05;
  const baseStart = loops ? 0 : Math.max(0, sliceStart || 0);
  const maxIdx = peaks.length - 1;
  const out = [];
  for (let i = 0; i < outPoints; i++) {
    const t = baseStart + (i / Math.max(1, outPoints - 1)) * span;
    const r = loops
      ? (((t % dur) + dur) % dur) / dur
      : Math.max(0, Math.min(1, t / dur));
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

  if (isFullVideoMode()) {
    renderFvTracks(clip);
    return;
  }

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
      <div class="seg-grab-bar seg-grab-left" data-edge="start"></div>
      <div class="relative z-[7] w-full h-full px-5 flex items-center justify-between text-[11px] text-white pointer-events-none drop-shadow">
        <span class="font-medium truncate">${escHtml(clip.name)}</span>
        <span class="text-neutral-200 tabular-nums">${fmtMMSS(clip.end - clip.start)}</span>
      </div>
      <div class="seg-grab-bar seg-grab-right" data-edge="end"></div>
    </div>
  `;
  const segEl = document.getElementById('videoSeg');
  segEl.insertBefore(filmstripCanvas, segEl.firstChild);

  const m = activeMusic();
  const hasMusic = Boolean(m);
  document.getElementById('musicTrackRow').classList.toggle('hidden', !hasMusic);
  document.getElementById('musicIconRail')?.classList.toggle('hidden', !hasMusic);
  document.getElementById('musicActionRail')?.classList.toggle('hidden', !hasMusic);
  const tlPanel = document.getElementById('timelinePanel');
  tlPanel.style.height = '';
  tlPanel.classList.remove('h-[174px]');
  tlPanel.classList.toggle('h-[164px]', !hasMusic);
  tlPanel.classList.toggle('h-[204px]', hasMusic);

  if (hasMusic) {
    const aArea = document.getElementById('audioTrackArea');
    const clipSpan = Math.max(1, clip.end - clip.start);
    const peaks = (m.peaks && m.peaks.length) ? m.peaks : defaultPeaks(96);
    const slicePeaks = sampleMusicSlicePeaks(peaks, m.totalDur, m.sliceStart, clipSpan, 64);
    aArea.innerHTML = `
      <div id="musicBarSeg" class="audio-track-seg" style="left: ${leftPct}%; width: ${widthPct}%;">
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
    const rowActionBtn = document.getElementById('btnMusicRowAction');
    if (rowActionBtn) {
      setLunaTooltip(rowActionBtn, canSliceMusic(clip, m) ? 'Select music section' : 'Music options');
    }
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

function onMusicRowAction() {
  const clip = activeClip();
  if (!clip) return;
  if (isFullVideoMode()) {
    document.getElementById('customAudioInput')?.click();
    return;
  }
  const m = activeMusic();
  if (!m) return;
  if (canSliceMusic(clip, m)) {
    closeMusicPopover();
    openMusicModal(false);
  } else {
    toggleMusicPopover();
  }
}

function toggleMusicPopover() {
  const clip = activeClip();
  const m = activeMusic();
  if (!m) return;
  const pop = document.getElementById('musicInlinePopover');
  const willShow = pop.classList.contains('hidden');
  if (willShow) {
    document.getElementById('inlineMusicVolSlider').value = m.volume;
    document.getElementById('inlineMusicVolText').textContent = `${m.volume}%`;
    document.getElementById('btnTrimMusicInline')?.classList.toggle('hidden', !canSliceMusic(clip, m));
    pop.classList.remove('hidden');
  } else {
    pop.classList.add('hidden');
  }
}

function closeMusicPopover() {
  document.getElementById('musicInlinePopover')?.classList.add('hidden');
}

document.addEventListener('pointerdown', (ev) => {
  if (!ev.target.closest('#musicTrackRow') && !ev.target.closest('#musicInlinePopover')) closeMusicPopover();
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
  if (isFullVideoMode()) {
    pushFvHistory();
    clip.segments = [makeDefaultSegment(0, clip.dur || 1)];
    clip.start = 0;
    clip.end = clip.dur || 1;
    clampFvAudioClipsToVideo(clip);
    state.selectedSegIdx = 0;
    state.playingSegIdx = 0;
    state.tlFitContent = false;
    syncFvFitButton();
    seekTo(0);
    renderRuler();
    renderTracks();
    syncFullVideoPanels();
    updateFvToolbarState();
    scheduleDraftSave();
    showToast('Timeline reset to full clip');
    return;
  }
  clip.start = 0;
  clip.end = clip.dur;
  seekTo(0);
  renderTracks();
  scheduleDraftSave();
  showToast('Reset clip boundaries');
}

// Serialized H.264 video seek queue (prevents Chrome decoder stutter during rapid scrubs & play flicker)
let videoSeekBusy = false;
let pendingVideoSeekTime = null;
let pendingPlayAfterSeek = false;
let isUserScrubbing = false;
let lastPlaybackRateAppliedAt = 0;

function requestVideoSeek(targetSrcTime, autoPlayWhenDone = false) {
  const dur = Number(videoEl.duration);
  const clamped = Number.isFinite(dur) && dur > 0
    ? Math.max(0, Math.min(dur - 0.01, Number(targetSrcTime) || 0))
    : Math.max(0, Number(targetSrcTime) || 0);
  if (autoPlayWhenDone) pendingPlayAfterSeek = true;

  if (videoEl.readyState < 1) {
    pendingVideoSeekTime = clamped;
    return;
  }
  if (!videoEl.seeking) {
    videoSeekBusy = false;
  }

  if (Math.abs((videoEl.currentTime || 0) - clamped) <= 0.03 && !videoEl.seeking) {
    videoSeekBusy = false;
    pendingVideoSeekTime = null;
    if (pendingPlayAfterSeek && state.playing) {
      pendingPlayAfterSeek = false;
      startPlaybackStreamsNow();
    }
    return;
  }
  if (videoSeekBusy || videoEl.seeking) {
    pendingVideoSeekTime = clamped;
    return;
  }
  videoSeekBusy = true;
  pendingVideoSeekTime = null;
  try {
    videoEl.currentTime = clamped;
    if (!videoEl.seeking) {
      videoSeekBusy = false;
      if (pendingPlayAfterSeek && state.playing) {
        pendingPlayAfterSeek = false;
        startPlaybackStreamsNow();
      }
    }
  } catch (_) {
    videoSeekBusy = false;
  }
}

function startPlaybackStreamsNow() {
  const clip = activeClip();
  if (!clip || !state.playing) return;
  if (isFullVideoMode()) {
    applyLivePlaybackSpeed(true);
    applyLiveSegmentVolume();
  }
  videoEl.play().catch(() => {});
  if (isFullVideoMode()) {
    syncMusicTimeToVideo(true);
  } else {
    const m = activeMusic();
    if (m && customAudioEl.src) {
      customAudioEl.volume = state.muted ? 0 : m.volume / 100;
      customAudioEl.play().catch(() => {});
    }
  }
}

function syncMusicTimeToVideo(playIfReady = false) {
  const clip = activeClip();
  if (!clip || state.modalPlaying) return;

  if (isFullVideoMode()) {
    const activeClips = findAudioClipsAt(clip, state.currentTime);
    const activeByLane = new Map();
    activeClips.forEach((ac) => activeByLane.set(ac.track || 0, ac));

    const canPlay = playIfReady && state.playing && !isUserScrubbing && !videoEl.paused && !videoEl.seeking && !videoEl.ended && videoEl.readyState >= 3;

    fvAudioPool.forEach((el, lane) => {
      if (!activeByLane.has(lane) && !el.paused) {
        el.pause();
      }
    });

    activeByLane.forEach((ac, lane) => {
      if (!ac.url) return;
      const el = getFvLaneAudioEl(lane);
      const resolved = encodeMediaUrl(ac.url);
      if (el.getAttribute('src') !== resolved) {
        el.src = resolved;
        el.dataset.assetName = ac.assetName || '';
        el.load();
      }
      el.loop = false;
      const localT = Math.max(0, state.currentTime - ac.timelineStart);
      const targetAudioTime = Math.min(ac.trimEnd, ac.trimStart + localT);
      const gain = evalAudioGainAt(ac, localT);
      el.volume = state.muted ? 0 : gain;
      if (el.readyState < 1) {
        el.dataset.pendingSeek = String(targetAudioTime);
        if (!el.paused) el.pause();
        return;
      }
      delete el.dataset.pendingSeek;
      if (Math.abs(el.currentTime - targetAudioTime) > 0.16) {
        el.currentTime = targetAudioTime;
      }
      if (canPlay) {
        if (el.paused) el.play().catch(() => {});
      } else if (!state.playing && !el.paused) {
        el.pause();
      }
    });
    return;
  }

  const m = activeMusic();
  if (!m || !customAudioEl.src) return;
  const offset = Math.max(0, state.currentTime - clip.start);
  const totalDur = Number(m.totalDur) || Number(customAudioEl.duration) || 0;
  const clipSpan = getActiveClipSpan(clip);
  const shouldLoop = totalDur > 0.1 && clipSpan > totalDur + 0.05;
  customAudioEl.loop = shouldLoop;
  const targetAudioTime = getMusicTargetTime(clip, m, offset);
  const rawDiff = Math.abs(customAudioEl.currentTime - targetAudioTime);
  const drift = shouldLoop && totalDur > 0.5 ? Math.min(rawDiff, Math.abs(totalDur - rawDiff)) : rawDiff;
  if (drift > 0.14) {
    customAudioEl.currentTime = targetAudioTime;
  }
  if (playIfReady && state.playing && !isUserScrubbing && !videoEl.paused && !videoEl.seeking && !videoEl.ended && videoEl.readyState >= 3) {
    customAudioEl.volume = state.muted ? 0 : m.volume / 100;
    if (customAudioEl.paused) customAudioEl.play().catch(() => {});
  }
}

function seekToStart() {
  const clip = activeClip();
  if (!clip) return;
  const now = Date.now();
  const startSec = isFullVideoMode() ? 0 : (clip.start || 0);
  const nearStart = (state.currentTime - startSec) <= 2.0;
  const doubleTap = (now - (state.lastPrevClickAt || 0)) <= 2000;
  state.lastPrevClickAt = now;

  if (!nearStart && !doubleTap) {
    seekTo(startSec);
    return;
  }
  if (state.activeIdx > 0) {
    selectWorkspaceClip(state.activeIdx - 1);
    showToast(`Switched to ${WORKSPACE_CLIPS[state.activeIdx]?.name || 'previous video'}`);
  } else {
    seekTo(startSec);
    showToast('Already at the first video');
  }
}

function seekToEnd() {
  const clip = activeClip();
  if (!clip) return;
  if (state.activeIdx + 1 < WORKSPACE_CLIPS.length) {
    selectWorkspaceClip(state.activeIdx + 1);
    showToast(`Switched to ${WORKSPACE_CLIPS[state.activeIdx]?.name || 'next video'}`);
  } else {
    showToast('Already at the last video');
  }
}

function seekTo(sec, preferSegIdx = null) {
  const clip = activeClip();
  if (!clip) return;
  const m = activeMusic();
  if (isFullVideoMode()) {
    const layout = computeTimelineLayout(clip);
    const tl = Math.max(0, Math.min(layout.totalDur, sec));
    state.currentTime = tl;
    const mapped = timelineToSource(clip, tl, preferSegIdx);
    state.playingSegIdx = mapped.segIdx;
    if (!state.modalPlaying) {
      pauseAllFvAudioPlayers();
    }
    requestVideoSeek(mapped.srcTime, false);
    if (!state.modalPlaying) {
      syncMusicTimeToVideo(false);
    }
    applyLivePlaybackSpeed(true);
    applyLiveSegmentVolume();
    applyLiveSegmentCropPosition();
    updateCurvePlayhead();
    updateFvAudioEnvPlayhead();
    updatePlayhead();
    return;
  }

  state.currentTime = Math.max(0, Math.min(clip.dur, sec));
  if (m && customAudioEl.src && !state.modalPlaying) {
    customAudioEl.pause();
  }
  requestVideoSeek(state.currentTime, false);
  if (m && customAudioEl.src && !state.modalPlaying) {
    const offset = Math.max(0, state.currentTime - clip.start);
    customAudioEl.currentTime = getMusicTargetTime(clip, m, offset);
  }
  updateSubtitleOverlay();
  updatePlayhead();
}

function stepTime(delta) {
  seekTo(state.currentTime + delta);
}

function updatePlayhead() {
  const clip = activeClip();
  const phEl = document.getElementById('playhead');
  if (!clip || !phEl) return;
  const trackEl = document.getElementById('timelineZoomTrack');
  const trackW = trackEl ? trackEl.clientWidth : 0;

  if (isFullVideoMode()) {
    const contentDur = Math.max(0.1, computeTimelineLayout(clip).totalDur);
    const scaleDur = getTimelineScaleDur(clip);
    const ratio = Math.max(0, Math.min(1, state.currentTime / scaleDur));
    if (trackW > 0) {
      phEl.style.left = '0px';
      phEl.style.transform = `translate3d(${(ratio * trackW).toFixed(2)}px, 0, 0)`;
    } else {
      phEl.style.transform = '';
      phEl.style.left = `${(ratio * 100).toFixed(4)}%`;
    }
    const badge = document.getElementById('trimRangeBadge');
    if (badge) badge.textContent = `${fmtMMSS(state.currentTime)} / ${fmtMMSS(contentDur)}`;
    return;
  }
  const ratio = clip.dur > 0 ? Math.max(0, Math.min(1, state.currentTime / clip.dur)) : 0;
  if (trackW > 0) {
    phEl.style.left = '0px';
    phEl.style.transform = `translate3d(${(ratio * trackW).toFixed(2)}px, 0, 0)`;
  } else {
    phEl.style.transform = '';
    phEl.style.left = `${(ratio * 100).toFixed(4)}%`;
  }
}

window.addEventListener('resize', () => {
  if (!activeClip()) return;
  renderRuler();
  updatePlayhead();
});

function stopPlaybackAtEnd() {
  const clip = activeClip();
  if (!clip) return;
  state.playing = false;
  pendingPlayAfterSeek = false;
  videoEl.pause();
  customAudioEl.pause();
  pauseAllFvAudioPlayers();
  if (isFullVideoMode()) {
    state.currentTime = computeTimelineLayout(clip).totalDur;
    updateCurvePlayhead();
    updateFvAudioEnvPlayhead();
  } else {
    state.currentTime = Math.min(clip.end, videoEl.duration || clip.dur);
  }
  updatePlayhead();
  updateSubtitleOverlay();
  updatePlayIcon();
}

videoEl.addEventListener('ended', () => {
  if (state.playing) {
    const clip = activeClip();
    if (isFullVideoMode() && clip && state.playingSegIdx + 1 < (clip.segments || []).length) {
      state.playingSegIdx += 1;
      const layout = computeTimelineLayout(clip);
      const nextSeg = clip.segments[state.playingSegIdx];
      state.currentTime = layout.items[state.playingSegIdx].tlStart;
      requestVideoSeek(nextSeg.sourceStart, true);
      return;
    }
    stopPlaybackAtEnd();
  } else if (!state.modalPlaying) {
    customAudioEl.pause();
    pauseAllFvAudioPlayers();
  }
});
videoEl.addEventListener('pause', () => {
  if (!state.modalPlaying) {
    customAudioEl.pause();
    pauseAllFvAudioPlayers();
  }
});
videoEl.addEventListener('seeking', () => {
  if (!state.modalPlaying) {
    customAudioEl.pause();
    pauseAllFvAudioPlayers();
  }
});
videoEl.addEventListener('waiting', () => {
  if (!state.modalPlaying) {
    customAudioEl.pause();
    pauseAllFvAudioPlayers();
  }
});
videoEl.addEventListener('seeked', () => {
  videoSeekBusy = false;
  if (pendingVideoSeekTime !== null) {
    const nextTarget = pendingVideoSeekTime;
    pendingVideoSeekTime = null;
    requestVideoSeek(nextTarget, pendingPlayAfterSeek);
    return;
  }
  const clip = activeClip();
  if (!isUserScrubbing) {
    if (isFullVideoMode() && clip) {
      state.currentTime = sourceToTimeline(clip, state.playingSegIdx, videoEl.currentTime);
      updatePlayhead();
      updateCurvePlayhead();
      updateFvAudioEnvPlayhead();
    } else if (clip) {
      state.currentTime = videoEl.currentTime;
    }
  }
  if (pendingPlayAfterSeek && state.playing && !isUserScrubbing) {
    pendingPlayAfterSeek = false;
    startPlaybackStreamsNow();
  } else {
    syncMusicTimeToVideo(true);
  }
});
videoEl.addEventListener('playing', () => {
  const clip = activeClip();
  if (isFullVideoMode() && clip && !videoEl.seeking) {
    state.currentTime = sourceToTimeline(clip, state.playingSegIdx, videoEl.currentTime);
  } else if (clip && !videoEl.seeking) {
    state.currentTime = videoEl.currentTime;
  }
  syncMusicTimeToVideo(true);
});

function togglePlay() {
  const clip = activeClip();
  if (!clip) return;
  const m = activeMusic();
  state.playing = !state.playing;
  if (state.playing) {
    if (isFullVideoMode()) {
      const layout = computeTimelineLayout(clip);
      if (videoEl.ended || state.currentTime >= layout.totalDur - 0.08) {
        state.currentTime = 0;
        const firstMapped = timelineToSource(clip, 0);
        state.playingSegIdx = firstMapped.segIdx;
        applyLiveSegmentCropPosition();
        requestVideoSeek(firstMapped.srcTime, true);
      } else {
        const mapped = timelineToSource(clip, state.currentTime);
        state.playingSegIdx = mapped.segIdx;
        applyLiveSegmentCropPosition();
        if (Math.abs((videoEl.currentTime || 0) - mapped.srcTime) > 0.08 || videoEl.seeking) {
          requestVideoSeek(mapped.srcTime, true);
        } else {
          pendingPlayAfterSeek = false;
          startPlaybackStreamsNow();
        }
      }
    } else {
      if (videoEl.ended || state.currentTime >= clip.end - 0.08 || state.currentTime < clip.start) {
        state.currentTime = clip.start || 0;
        requestVideoSeek(state.currentTime, true);
      } else {
        if (m && customAudioEl.src) {
          const offset = Math.max(0, state.currentTime - clip.start);
          customAudioEl.currentTime = getMusicTargetTime(clip, m, offset);
        }
        startPlaybackStreamsNow();
      }
    }
  } else {
    pendingPlayAfterSeek = false;
    videoEl.pause();
    customAudioEl.pause();
    pauseAllFvAudioPlayers();
  }
  updateSubtitleOverlay(true);
  updatePlayIcon();
}

function updatePlayIcon() {
  const iconName = state.playing ? 'pause' : 'play';
  const mainBtn = document.getElementById('btnMainPlay');
  if (mainBtn) {
    mainBtn.innerHTML = `<i id="playIcon" data-lucide="${iconName}" class="w-4 h-4"></i>`;
    if (window.lucide) lucide.createIcons({ root: mainBtn });
  }
  const expIcon = document.getElementById('expandedPlayIcon');
  const expBtn = expIcon?.parentElement;
  if (expBtn) {
    expBtn.innerHTML = `<i id="expandedPlayIcon" data-lucide="${iconName}" class="w-3.5 h-3.5"></i>`;
    if (window.lucide) lucide.createIcons({ root: expBtn });
  }
}

function syncAudioMuteState() {
  const clip = activeClip();
  const m = activeMusic();
  const origMuted = Boolean(clip?.origMuted);
  const previewMuted = Boolean(state.muted);

  videoEl.muted = previewMuted || origMuted;
  if (!videoEl.muted) {
    if (isFullVideoMode()) applyLiveSegmentVolume();
    else videoEl.volume = 1;
  } else {
    videoEl.volume = 0;
  }

  if (isFullVideoMode()) {
    if (previewMuted) {
      fvAudioPool.forEach((el) => { el.volume = 0; });
    } else {
      syncMusicTimeToVideo(false);
    }
  } else if (m) {
    customAudioEl.volume = previewMuted ? 0 : m.volume / 100;
  }

  const volIcon = previewMuted ? 'volume-x' : 'volume-2';
  const bottomBtn = document.getElementById('btnBottomMute');
  if (bottomBtn) {
    bottomBtn.innerHTML = `<i id="bottomMuteIcon" data-lucide="${volIcon}" class="w-4 h-4"></i>`;
    bottomBtn.classList.toggle('is-active', previewMuted);
    setLunaTooltip(bottomBtn, previewMuted ? 'Unmute preview' : 'Mute preview');
    if (window.lucide) lucide.createIcons({ root: bottomBtn });
  }
  const expBtn = document.getElementById('btnExpandedMute');
  if (expBtn) {
    expBtn.innerHTML = `<i id="expandedMuteIcon" data-lucide="${volIcon}" class="w-4 h-4"></i>`;
    expBtn.classList.toggle('is-active', previewMuted);
    if (window.lucide) lucide.createIcons({ root: expBtn });
  }
  const origWrap = document.getElementById('origAudioIconWrap');
  const origBtn = document.getElementById('btnOrigAudio');
  if (origWrap) {
    origWrap.innerHTML = `<i id="origAudioIcon" data-lucide="${origMuted ? 'volume-x' : 'check'}" class="w-2.5 h-2.5"></i>`;
    origWrap.classList.toggle('bg-white', !origMuted);
    origWrap.classList.toggle('text-black', !origMuted);
    origWrap.classList.toggle('bg-neutral-700', origMuted);
    origWrap.classList.toggle('text-neutral-200', origMuted);
    if (window.lucide) lucide.createIcons({ root: origWrap });
  }
  if (origBtn) origBtn.classList.toggle('opacity-65', origMuted);
}

function toggleOriginalAudioMute() {
  const clip = activeClip();
  if (!clip) return;
  if (isFullVideoMode()) pushFvHistory();
  clip.origMuted = !clip.origMuted;
  syncAudioMuteState();
  if (isFullVideoMode()) updateFvExportInfo();
  scheduleDraftSave();
  showToast(clip.origMuted ? 'Original audio muted' : 'Original audio enabled');
}

function toggleMute() {
  state.muted = !state.muted;
  syncAudioMuteState();
}

// --- Background Music Upload & Slice Modal ---
function defaultPeaks(n) {
  return Array.from({ length: n }, (_, i) => 0.25 + 0.7 * Math.abs(Math.sin(i * 0.45) * Math.cos(i * 0.17)));
}

async function extractPeaksFromArrayBuffer(buf) {
  try {
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
    return { peaks: defaultPeaks(160), duration: 0 };
  }
}

async function extractPeaksFromFile(file) {
  try {
    const buf = await file.arrayBuffer();
    return await extractPeaksFromArrayBuffer(buf);
  } catch (_) {
    return { peaks: defaultPeaks(160), duration: 0 };
  }
}

async function extractPeaksFromUrl(url) {
  try {
    const res = await fetch(encodeMediaUrl(url));
    if (!res.ok) return { peaks: defaultPeaks(160), duration: 0 };
    const buf = await res.arrayBuffer();
    return await extractPeaksFromArrayBuffer(buf);
  } catch (_) {
    return { peaks: defaultPeaks(160), duration: 0 };
  }
}

function isVideoUploadFile(file) {
  if (!file) return false;
  if (file.type && file.type.startsWith('video/')) return true;
  return /\.(mp4|mov|mkv|m4v|avi)$/i.test(file.name || '');
}

function getModalSliceSpan() {
  const m = state.draftMusic;
  const clip = activeClip();
  if (!m || !clip) return 1;
  const target = (typeof m.targetSpan === 'number' && m.targetSpan > 0.1)
    ? m.targetSpan
    : getActiveClipSpan(clip);
  return Math.max(0.15, Math.min(m.totalDur || target, target));
}

let musicUploading = false;
async function onSelectMusicFile(ev) {
  const file = ev.target.files?.[0];
  if (!file) return;
  ev.target.value = '';
  if (musicUploading) {
    showToast('Audio upload already in progress...');
    return;
  }
  const targetClip = activeClip();
  if (!targetClip) return;
  const targetClipId = targetClip.id;

  musicUploading = true;
  const fromVideo = isVideoUploadFile(file);
  showToast(fromVideo ? `Extracting audio from ${file.name}...` : `Uploading ${file.name}...`);
  try {
    const uploadUrl = `/api/studio/${encodeURIComponent(PROJECT_ID)}/music?clip_id=${encodeURIComponent(targetClipId)}&filename=${encodeURIComponent(file.name)}`;
    let uploadRes;
    let extracted = null;
    const useServerPeaksOnly = fromVideo || (file.size > 6 * 1024 * 1024);
    if (useServerPeaksOnly) {
      uploadRes = await fetch(uploadUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/octet-stream' },
        body: file,
      });
    } else {
      [uploadRes, extracted] = await Promise.all([
        fetch(uploadUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/octet-stream' },
          body: file,
        }),
        extractPeaksFromFile(file),
      ]);
    }
    if (!uploadRes.ok) {
      const errData = await uploadRes.json().catch(() => ({}));
      throw new Error(errData.detail || (fromVideo ? 'Could not extract audio from video' : 'Upload failed'));
    }
    const uploaded = await uploadRes.json();
    const serverPeaks = Array.isArray(uploaded.peaks) && uploaded.peaks.length >= 16 ? uploaded.peaks : null;
    if (serverPeaks) {
      extracted = { duration: Number(uploaded.duration) || Number(extracted?.duration) || 0, peaks: serverPeaks };
    } else if (!extracted) {
      extracted = await extractPeaksFromUrl(uploaded.url);
    }
    const probedDur = Number(uploaded.duration) || 0;
    const decodedDur = Number(extracted?.duration) || 0;
    const realMusicDur = probedDur > 0.05 ? probedDur : decodedDur;
    const stillActive = activeClip()?.id === targetClipId;

    if (isFullVideoMode()) {
      ensureFullVideoDefaults(targetClip);
      const totalDur = computeTimelineLayout(targetClip).totalDur;
      const safeMusicDur = realMusicDur > 0.15 ? realMusicDur : Math.min(totalDur, 30);

      // Rule: open slice picker only when still on target clip, no audio placed yet, and music exceeds video length.
      if (stillActive && targetClip.audioClips.length === 0 && safeMusicDur > totalDur + 0.5) {
        state.editingAudioClipId = null;
        state.draftMusic = {
          name: uploaded.name || file.name,
          assetName: uploaded.assetName,
          url: uploaded.url,
          totalDur: Number(safeMusicDur.toFixed(3)),
          targetSpan: Number(totalDur.toFixed(3)),
          sliceStart: 0,
          volume: 35,
          peaks: extracted.peaks,
        };
        openMusicModal(true);
        return;
      }

      const anchorTime = stillActive ? state.currentTime : 0;
      const slot = findNextAudioSlot(targetClip, anchorTime, safeMusicDur);
      if (!slot) {
        showToast('Audio track is full — trim or delete a block first');
        return;
      }
      if (stillActive) pushFvHistory();
      const newAc = makeAudioClip({
        name: uploaded.name || file.name,
        assetName: uploaded.assetName,
        url: uploaded.url,
        track: slot.track || 0,
        sourceDur: safeMusicDur,
        timelineStart: slot.start,
        trimStart: 0,
        trimEnd: Math.min(safeMusicDur, slot.span),
        volume: 35,
        fadeIn: 0,
        fadeOut: 0,
        keyframes: [],
        peaks: extracted.peaks,
      });
      targetClip.audioClips.push(newAc);
      targetClip.audioClips.sort((a, b) => (a.track - b.track) || (a.timelineStart - b.timelineStart));
      if (stillActive) {
        selectFvAudioClip(newAc.id);
        syncClipAudioElement();
        renderTracks();
        updateFvExportInfo();
      }
      scheduleDraftSave();
      showToast(
        stillActive
          ? `Added ${newAc.name} (${fmtMMSS(getAudioClipSpan(newAc))})`
          : `Added ${newAc.name} to ${targetClip.name}`
      );
      return;
    }

    const nextMusic = {
      name: uploaded.name || file.name,
      assetName: uploaded.assetName,
      url: uploaded.url,
      totalDur: realMusicDur > 0.05 ? Number(realMusicDur.toFixed(3)) : 0,
      sliceStart: 0,
      volume: 35,
      peaks: extracted.peaks,
    };

    // AI Clipper mode: only open section picker when still on target clip and uploaded music exceeds clip length.
    if (stillActive && canSliceMusic(targetClip, nextMusic)) {
      state.editingAudioClipId = null;
      state.draftMusic = nextMusic;
      openMusicModal(true);
    } else {
      if (stillActive) state.draftMusic = null;
      targetClip.music = nextMusic;
      if (stillActive) {
        syncClipAudioElement();
        renderTracks();
      }
      scheduleDraftSave();
      const durBadge = nextMusic.totalDur > 0.05 ? ` (${fmtMMSS(nextMusic.totalDur)})` : '';
      showToast(
        stillActive
          ? `Music added${durBadge}: ${targetClip.music.name}`
          : `Music added to ${targetClip.name}: ${targetClip.music.name}`
      );
    }
  } catch (err) {
    showToast(err.message || 'Could not upload audio');
  } finally {
    musicUploading = false;
  }
}

function openMusicModal(isNew = false) {
  const clip = activeClip();
  const curMusic = activeMusic();
  if (!isNew && !curMusic && !state.editingAudioClipId) return;
  if (!isNew && !state.editingAudioClipId) {
    if (!canSliceMusic(clip, curMusic)) {
      toggleMusicPopover();
      return;
    }
    state.draftMusic = { ...curMusic };
  }
  const m = state.draftMusic;
  if (!m) return;
  if (state.playing) {
    state.playing = false;
    videoEl.pause();
    customAudioEl.pause();
    pauseAllFvAudioPlayers();
    updatePlayIcon();
  }
  if (!m.peaks || !m.peaks.length) m.peaks = defaultPeaks(96);
  state.modalZoom = 1;
  document.getElementById('modalMusicName').textContent = m.name;
  document.getElementById('modalVolumeSlider').value = m.volume;
  document.getElementById('modalVolumeText').textContent = `${m.volume}%`;
  document.getElementById('btnRemoveMusic').classList.toggle('hidden', isNew && !curMusic && !state.editingAudioClipId);

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
      const clipSpan = getModalSliceSpan();
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
  const clipSpan = getModalSliceSpan();
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
  const clipSpan = getModalSliceSpan();
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
    if (isFullVideoMode()) {
      ensureFullVideoDefaults(clip);
      const dm = state.draftMusic;
      const span = getModalSliceSpan();
      pushFvHistory();
      if (state.editingAudioClipId) {
        const ac = (clip.audioClips || []).find((a) => a.id === state.editingAudioClipId);
        if (ac) {
          ac.trimStart = Number(dm.sliceStart.toFixed(3));
          ac.trimEnd = Number(Math.min(ac.sourceDur, dm.sliceStart + span).toFixed(3));
          ac.volume = Math.max(0, Math.min(100, Math.round(dm.volume)));
        }
        syncClipAudioElement();
        renderTracks();
        syncFvAudioInspector();
        updateFvExportInfo();
        scheduleDraftSave();
        showToast(`Updated song section (${fmtMMSS(dm.sliceStart)} – ${fmtMMSS(dm.sliceStart + span)})`);
      } else {
        const slot = findNextAudioSlot(clip, state.currentTime, span);
        const newAc = makeAudioClip({
          name: dm.name,
          assetName: dm.assetName,
          url: dm.url,
          track: slot ? (slot.track || 0) : 0,
          sourceDur: dm.totalDur,
          timelineStart: slot ? slot.start : 0,
          trimStart: dm.sliceStart,
          trimEnd: Math.min(dm.totalDur, dm.sliceStart + (slot ? Math.min(span, slot.span) : span)),
          volume: dm.volume,
          fadeIn: 0,
          fadeOut: 0,
          keyframes: [],
          peaks: dm.peaks,
        });
        clip.audioClips.push(newAc);
        clip.audioClips.sort((a, b) => (a.track - b.track) || (a.timelineStart - b.timelineStart));
        selectFvAudioClip(newAc.id);
        syncClipAudioElement();
        renderTracks();
        updateFvExportInfo();
        scheduleDraftSave();
        showToast(`Added ${newAc.name} (${fmtMMSS(getAudioClipSpan(newAc))})`);
      }
      state.draftMusic = null;
      state.editingAudioClipId = null;
      return;
    }

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
  state.editingAudioClipId = null;
}

function removeCustomMusic() {
  const clip = activeClip();
  if (!clip) return;
  if (isFullVideoMode()) {
    state.modalPlaying = false;
    customAudioEl.pause();
    document.getElementById('musicPickerModal').classList.add('hidden');
    if (state.editingAudioClipId) {
      state.selectedAudioId = state.editingAudioClipId;
      state.editingAudioClipId = null;
      state.draftMusic = null;
      deleteSelectedAudioClip();
    } else {
      state.draftMusic = null;
    }
    return;
  }
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
  const clipSpan = getModalSliceSpan();
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
  const clipSpan = getModalSliceSpan();

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

// --- Full Video Studio (Magnetic Multi-Block Timeline, Undo/Redo, 2D 5-Point Speed Curve, Inspector) ---
const FV_COLOR_PRESETS = {
  natural: { brightness: 0, exposure: 0, contrast: 0, saturation: 0, warmth: 0, sharpness: 0, vignette: 0 },
  warm: { brightness: 4, exposure: 4, contrast: 6, saturation: 12, warmth: 18, sharpness: 0, vignette: 0 },
  crisp: { brightness: 2, exposure: 2, contrast: 18, saturation: 14, warmth: 0, sharpness: 16, vignette: 0 },
  cinematic: { brightness: -4, exposure: -4, contrast: 16, saturation: -8, warmth: -10, sharpness: 8, vignette: 20 },
  vivid: { brightness: 4, exposure: 6, contrast: 12, saturation: 28, warmth: 6, sharpness: 10, vignette: 0 },
  bw: { brightness: 0, exposure: 0, contrast: 16, saturation: -50, warmth: 0, sharpness: 8, vignette: 12 },
};

const FV_CURVE_PRESETS = {
  none: [1.0, 1.0, 1.0, 1.0, 1.0],
  dip: [1.4, 0.9, 0.4, 0.9, 1.4],
  pulse: [0.7, 2.2, 0.5, 2.2, 0.7],
  fast_in: [2.5, 1.8, 1.0, 0.8, 1.0],
};

const CURVE_SVG_W = 230;
const CURVE_SVG_H = 138;
const CURVE_PAD_L = 28;
const CURVE_PAD_R = 12;
const CURVE_PAD_T = 12;
const CURVE_PAD_B = 24;
const CURVE_PLOT_W = CURVE_SVG_W - CURVE_PAD_L - CURVE_PAD_R;
const CURVE_PLOT_H = CURVE_SVG_H - CURVE_PAD_T - CURVE_PAD_B;
const CURVE_PT_LABELS = ['Start', 'Pt 2', 'Mid', 'Pt 4', 'End'];

function fmtSpeed(spd) {
  const n = Number(spd) || 1;
  return `${n.toFixed(2).replace(/\.?0+$/, '')}x`;
}

function sampleCurveSpeed(points, ratio, positions = null) {
  const pts = sanitizeCurvePoints(points);
  const pos = sanitizeCurvePositions(positions);
  const r = Math.max(0, Math.min(1, Number(ratio) || 0));
  for (let i = 0; i < 4; i++) {
    if (r <= pos[i + 1] + 1e-6 || i === 3) {
      const span = Math.max(0.001, pos[i + 1] - pos[i]);
      const frac = Math.max(0, Math.min(1, (r - pos[i]) / span));
      return Math.max(0.25, Math.min(4.0, pts[i] * (1 - frac) + pts[i + 1] * frac));
    }
  }
  return pts[4];
}

function sliceCurvePoints(points, r0, r1, positions = null) {
  const out = [];
  for (let i = 0; i < 5; i++) {
    const r = r0 + (i / 4) * (r1 - r0);
    out.push(Number(sampleCurveSpeed(points, r, positions).toFixed(2)));
  }
  return out;
}

function isSegmentCurveActive(seg) {
  if (!seg || seg.speedMode !== 'curve') return false;
  const pts = sanitizeCurvePoints(seg.curvePoints);
  return pts.some((p) => Math.abs(p - 1.0) >= 0.02);
}

function isSegmentSpeedActive(seg) {
  if (!seg) return false;
  if (seg.speedMode === 'curve') return isSegmentCurveActive(seg);
  return Math.abs((Number(seg.speed) || 1) - 1) >= 0.02;
}

function getSegmentSubPieces(seg) {
  const ss = Number(seg.sourceStart) || 0;
  const se = Math.max(ss + 0.1, Number(seg.sourceEnd) || ss + 0.1);
  if (seg.speedMode === 'curve') {
    const pts = sanitizeCurvePoints(seg.curvePoints);
    const pos = sanitizeCurvePositions(seg.curvePositions);
    const isFlat = pts.every((p) => Math.abs(p - pts[0]) < 0.02);
    if (isFlat) {
      const spd = pts[0];
      return [{ a: ss, b: se, spd, dt: (se - ss) / spd }];
    }
    const steps = 10;
    const stepDur = (se - ss) / steps;
    const pieces = [];
    for (let k = 0; k < steps; k++) {
      const a = ss + k * stepDur;
      const b = ss + (k + 1) * stepDur;
      const spd = sampleCurveSpeed(pts, (k + 0.5) / steps, pos);
      pieces.push({ a, b, spd, dt: (b - a) / spd });
    }
    return pieces;
  }
  const spd = Math.max(0.25, Math.min(4.0, Number(seg.speed) || 1.0));
  return [{ a: ss, b: se, spd, dt: (se - ss) / spd }];
}

function getSegmentEffDur(seg) {
  return getSegmentSubPieces(seg).reduce((acc, p) => acc + p.dt, 0);
}

function computeTimelineLayout(clip) {
  if (!clip) return { items: [], totalDur: 1 };
  if (!Array.isArray(clip.segments) || !clip.segments.length) {
    ensureFullVideoDefaults(clip);
  }
  const items = [];
  let cursor = 0;
  clip.segments.forEach((seg, idx) => {
    const effDur = Math.max(0.08, getSegmentEffDur(seg));
    items.push({ seg, idx, tlStart: cursor, tlEnd: cursor + effDur, effDur });
    cursor += effDur;
  });
  return { items, totalDur: Math.max(0.1, cursor) };
}

function timelineToSource(clip, tlSec, preferSegIdx = null) {
  const layout = computeTimelineLayout(clip);
  const t = Math.max(0, Math.min(layout.totalDur, Number(tlSec) || 0));
  let item = layout.items[layout.items.length - 1];
  if (
    preferSegIdx !== null
    && preferSegIdx !== undefined
    && layout.items[preferSegIdx]
    && t >= layout.items[preferSegIdx].tlStart - 1e-4
    && t <= layout.items[preferSegIdx].tlEnd + 1e-4
  ) {
    item = layout.items[preferSegIdx];
  } else {
    for (let i = 0; i < layout.items.length - 1; i++) {
      if (t < layout.items[i].tlEnd - 1e-4) {
        item = layout.items[i];
        break;
      }
    }
  }
  const seg = item.seg;
  let rem = Math.max(0, t - item.tlStart);
  const pieces = getSegmentSubPieces(seg);
  let srcTime = seg.sourceEnd;
  for (let i = 0; i < pieces.length; i++) {
    const p = pieces[i];
    if (rem <= p.dt + 1e-5 || i === pieces.length - 1) {
      srcTime = Math.min(p.b, p.a + Math.min(rem, p.dt) * p.spd);
      break;
    }
    rem -= p.dt;
  }
  const srcSpan = Math.max(0.05, seg.sourceEnd - seg.sourceStart);
  const localRatio = Math.max(0, Math.min(1, (srcTime - seg.sourceStart) / srcSpan));
  return { segIdx: item.idx, seg, srcTime, localRatio, item };
}

function sourceToTimeline(clip, segIdx, srcTime) {
  const layout = computeTimelineLayout(clip);
  const safeIdx = Math.max(0, Math.min(layout.items.length - 1, segIdx || 0));
  const item = layout.items[safeIdx];
  if (!item) return 0;
  const seg = item.seg;
  const clampedSrc = Math.max(seg.sourceStart, Math.min(seg.sourceEnd, Number(srcTime) || seg.sourceStart));
  const pieces = getSegmentSubPieces(seg);
  let acc = item.tlStart;
  for (let i = 0; i < pieces.length; i++) {
    const p = pieces[i];
    if (clampedSrc <= p.b + 1e-5 || i === pieces.length - 1) {
      acc += Math.max(0, clampedSrc - p.a) / p.spd;
      break;
    }
    acc += p.dt;
  }
  return Math.max(0, Math.min(layout.totalDur, acc));
}

function activeSegment() {
  const clip = activeClip();
  if (!clip) return null;
  ensureFullVideoDefaults(clip);
  state.selectedSegIdx = Math.max(0, Math.min(clip.segments.length - 1, state.selectedSegIdx));
  return clip.segments[state.selectedSegIdx] || clip.segments[0];
}

function syncClipLegacyBounds(clip) {
  if (!clip || !clip.segments || !clip.segments.length) return;
  clip.start = clip.segments[0].sourceStart;
  clip.end = clip.segments[clip.segments.length - 1].sourceEnd;
}

function snapshotFvState(clip) {
  return JSON.stringify({
    segments: clip.segments,
    audioClips: clip.audioClips || [],
    cropRatio: clip.cropRatio,
    fade: clip.fade,
    color: clip.color,
    origMuted: Boolean(clip.origMuted),
    audioEnhance: clip.audioEnhance || { normalize: false, denoise: false, autoDuck: false },
    selectedTrack: state.selectedTrack,
    selectedSegIdx: state.selectedSegIdx,
    selectedAudioId: state.selectedAudioId,
  });
}

function pushFvHistory() {
  const clip = activeClip();
  if (!clip || !isFullVideoMode()) return;
  ensureFullVideoDefaults(clip);
  const snap = snapshotFvState(clip);
  if (state.fvHistory.length && state.fvHistory[state.fvHistory.length - 1] === snap) return;
  state.fvHistory.push(snap);
  if (state.fvHistory.length > 40) state.fvHistory.shift();
  state.fvFuture = [];
  updateFvToolbarState();
}

function restoreFvSnapshot(snapStr) {
  const clip = activeClip();
  if (!clip || !snapStr) return;
  try {
    const snap = JSON.parse(snapStr);
    clip.segments = snap.segments;
    if (Array.isArray(snap.audioClips)) clip.audioClips = snap.audioClips;
    clip.cropRatio = snap.cropRatio || 'original';
    clip.fade = Number(snap.fade) || 0;
    clip.color = snap.color || { preset: 'natural', brightness: 0, contrast: 0, saturation: 0 };
    clip.origMuted = Boolean(snap.origMuted);
    if (snap.audioEnhance && typeof snap.audioEnhance === 'object') {
      clip.audioEnhance = {
        normalize: Boolean(snap.audioEnhance.normalize),
        denoise: Boolean(snap.audioEnhance.denoise),
        autoDuck: Boolean(snap.audioEnhance.autoDuck),
      };
    }
    ensureFullVideoDefaults(clip);
    syncClipLegacyBounds(clip);
    state.selectedSegIdx = Math.max(0, Math.min(clip.segments.length - 1, snap.selectedSegIdx || 0));
    const hasAudioSel = snap.selectedTrack === 'audio' && (clip.audioClips || []).some((a) => a.id === snap.selectedAudioId);
    state.selectedTrack = hasAudioSel ? 'audio' : 'video';
    state.selectedAudioId = hasAudioSel ? snap.selectedAudioId : null;
    const layout = computeTimelineLayout(clip);
    seekTo(Math.min(state.currentTime, layout.totalDur));
    syncAudioMuteState();
    syncClipAudioElement();
    renderRuler();
    renderTracks();
    applyStageAspectAndFilters();
    applyLivePlaybackSpeed();
    applyLiveSegmentVolume();
    applyFvRightPanelMode();
    syncFullVideoPanels();
    updateFvToolbarState();
    scheduleDraftSave();
  } catch (_) {}
}

function fvUndo() {
  const clip = activeClip();
  if (!clip || !isFullVideoMode() || !state.fvHistory.length) return;
  state.fvFuture.push(snapshotFvState(clip));
  const prev = state.fvHistory.pop();
  restoreFvSnapshot(prev);
  showToast('Undo');
}

function fvRedo() {
  const clip = activeClip();
  if (!clip || !isFullVideoMode() || !state.fvFuture.length) return;
  state.fvHistory.push(snapshotFvState(clip));
  const next = state.fvFuture.pop();
  restoreFvSnapshot(next);
  showToast('Redo');
}

function updateFvToolbarState() {
  if (!isFullVideoMode()) return;
  const clip = activeClip();
  const seg = activeSegment();
  const undoBtn = document.getElementById('btnFvUndo');
  const redoBtn = document.getElementById('btnFvRedo');
  const delBtn = document.getElementById('btnFvDelete');
  const spdBtn = document.getElementById('btnFvSpeedShortcut');
  if (undoBtn) undoBtn.disabled = state.fvHistory.length === 0;
  if (redoBtn) redoBtn.disabled = state.fvFuture.length === 0;
  if (delBtn) {
    if (state.selectedTrack === 'audio') {
      delBtn.disabled = !activeAudioClip();
      setLunaTooltip(delBtn, 'Delete audio');
    } else {
      delBtn.disabled = !clip || (clip.segments || []).length <= 1;
      setLunaTooltip(delBtn, 'Ripple delete');
    }
  }
  if (spdBtn) {
    const active = state.selectedTrack === 'video' && (state.fvRightTab === 'speed' || isSegmentSpeedActive(seg));
    spdBtn.classList.toggle('is-active', active);
  }
}

function applyFvRightPanelMode() {
  if (!isFullVideoMode()) return;
  const audioMode = state.selectedTrack === 'audio' && Boolean(activeAudioClip());
  if (!audioMode && state.selectedTrack === 'audio') {
    state.selectedTrack = 'video';
    state.selectedAudioId = null;
  }
  document.getElementById('fvRightTabs')?.classList.toggle('hidden', audioMode);
  document.getElementById('fvAudioHeader')?.classList.toggle('hidden', !audioMode);
  document.getElementById('panelFvAudio')?.classList.toggle('hidden', !audioMode);
  if (audioMode) {
    document.getElementById('panelFvBasic')?.classList.add('hidden');
    document.getElementById('panelFvSpeed')?.classList.add('hidden');
    document.getElementById('panelFvAdjust')?.classList.add('hidden');
    syncFvAudioInspector();
  } else {
    switchFvRightTab(state.fvRightTab || 'basic');
  }
  updateFvToolbarState();
}

function applyStudioModeLayout() {
  const fv = isFullVideoMode();
  const heading = document.getElementById('leftListHeading');
  if (heading) heading.textContent = fv ? 'Videos' : 'AI Clips';
  document.getElementById('fvAudioExtras')?.classList.remove('hidden');
  document.getElementById('aiRightTabs')?.classList.toggle('hidden', fv);
  document.getElementById('fvRightTabs')?.classList.toggle('hidden', !fv);
  document.getElementById('fvAudioHeader')?.classList.add('hidden');
  document.getElementById('panelFvAudio')?.classList.add('hidden');
  document.getElementById('fvTimelineTools')?.classList.toggle('hidden', !fv);
  document.getElementById('fvTimelineZoomWrap')?.classList.toggle('hidden', !fv);
  if (fv) {
    document.getElementById('panelSubtitle')?.classList.add('hidden');
    document.getElementById('panelCaption')?.classList.add('hidden');
    document.getElementById('subtitleOverlay')?.classList.add('hidden');
    applyFvRightPanelMode();
  } else {
    document.getElementById('panelFvBasic')?.classList.add('hidden');
    document.getElementById('panelFvSpeed')?.classList.add('hidden');
    document.getElementById('panelFvAdjust')?.classList.add('hidden');
    document.getElementById('stageSpeedBadge')?.classList.add('hidden');
    switchRightTab(state.rightTab || 'subtitle');
  }
}

function switchFvRightTab(tab) {
  state.fvRightTab = ['basic', 'speed', 'adjust'].includes(tab) ? tab : 'basic';
  if (state.selectedTrack === 'audio') {
    state.selectedTrack = 'video';
    state.selectedAudioId = null;
    document.getElementById('fvRightTabs')?.classList.remove('hidden');
    document.getElementById('fvAudioHeader')?.classList.add('hidden');
    document.getElementById('panelFvAudio')?.classList.add('hidden');
    document.querySelectorAll('#audioTrackArea .fv-audio-block').forEach((el) => el.classList.remove('is-selected'));
  }
  document.querySelectorAll('.fv-right-tab').forEach((b) => b.classList.toggle('is-active', b.dataset.fvTab === state.fvRightTab));
  document.getElementById('panelFvBasic')?.classList.toggle('hidden', state.fvRightTab !== 'basic');
  document.getElementById('panelFvSpeed')?.classList.toggle('hidden', state.fvRightTab !== 'speed');
  document.getElementById('panelFvAdjust')?.classList.toggle('hidden', state.fvRightTab !== 'adjust');
  if (state.fvRightTab === 'speed') renderFvSpeedInspector();
  if (state.fvRightTab === 'adjust') updateFvExportInfo();
  updateFvToolbarState();
}

function openFvSpeedPanel() {
  if (!isFullVideoMode()) return;
  selectFvVideoTrack();
  switchFvRightTab('speed');
}

function selectFvVideoTrack() {
  if (!isFullVideoMode()) return;
  state.selectedTrack = 'video';
  state.selectedAudioId = null;
  document.querySelectorAll('#audioTrackArea .fv-audio-block').forEach((el) => el.classList.remove('is-selected'));
  document.querySelectorAll('#videoTrackArea .fv-tl-block').forEach((el) => {
    el.classList.toggle('is-selected', Number(el.dataset.segIdx) === state.selectedSegIdx);
  });
  applyFvRightPanelMode();
  syncFullVideoPanels();
}

function selectFvSegment(idx) {
  const clip = activeClip();
  if (!clip || !isFullVideoMode()) return;
  ensureFullVideoDefaults(clip);
  const clamped = Math.max(0, Math.min(clip.segments.length - 1, idx));
  state.selectedTrack = 'video';
  state.selectedAudioId = null;
  state.selectedSegIdx = clamped;
  document.querySelectorAll('#videoTrackArea .fv-tl-block').forEach((el) => {
    el.classList.toggle('is-selected', Number(el.dataset.segIdx) === clamped);
  });
  document.querySelectorAll('#audioTrackArea .fv-audio-block').forEach((el) => {
    el.classList.remove('is-selected');
  });
  applyLiveSegmentCropPosition();
  applyFvRightPanelMode();
  syncFullVideoPanels();
}

function selectFvAudioClip(audioId) {
  const clip = activeClip();
  if (!clip || !isFullVideoMode()) return;
  ensureFullVideoDefaults(clip);
  const found = (clip.audioClips || []).find((a) => a.id === audioId);
  if (!found) {
    selectFvVideoTrack();
    return;
  }
  state.selectedTrack = 'audio';
  state.selectedAudioId = found.id;
  document.querySelectorAll('#videoTrackArea .fv-tl-block').forEach((el) => {
    el.classList.remove('is-selected');
  });
  document.querySelectorAll('#audioTrackArea .fv-audio-block').forEach((el) => {
    el.classList.toggle('is-selected', el.dataset.audioId === found.id);
  });
  applyFvRightPanelMode();
}

function paintFvBlockFilmstrips(requestMissing = true) {
  const clip = activeClip();
  if (!clip || !isFullVideoMode()) return;
  const dur = Math.max(0.1, clip.dur || 1);
  const vp = document.getElementById('timelineScrollViewport');
  const vpScrollLeft = vp ? vp.scrollLeft : 0;
  const vpW = vp ? (vp.clientWidth || 1000) : 1000;
  const visLeft = vpScrollLeft - 120;
  const visRight = vpScrollLeft + vpW + 120;
  const dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
  const vidW = videoEl.videoWidth || thumbVideoEl.videoWidth || 16;
  const vidH = videoEl.videoHeight || thumbVideoEl.videoHeight || 9;
  const vidAspect = Math.max(0.9, Math.min(1.78, vidW / Math.max(1, vidH)));
  const neededTimes = [];

  document.querySelectorAll('#videoTrackArea .fv-tl-block').forEach((blockEl) => {
    const canvas = blockEl.querySelector('.fv-block-filmstrip');
    if (!canvas) return;
    const blkLeft = blockEl.offsetLeft;
    const blkW = blockEl.offsetWidth;
    const blkH = blockEl.offsetHeight || 40;

    // Keep clip labels tidy when a short block is narrow at low zoom, revealing automatically when zoomed in
    const lblWrap = blockEl.querySelector('.fv-block-label-wrap');
    const durEl = blockEl.querySelector('.fv-block-dur');
    if (lblWrap) lblWrap.style.display = blkW >= 46 ? '' : 'none';
    if (durEl) durEl.style.display = blkW >= 124 ? '' : 'none';

    const drawStart = Math.max(0, visLeft - blkLeft);
    const drawEnd = Math.min(blkW, visRight - blkLeft);
    const drawW = Math.ceil(drawEnd - drawStart);
    if (drawW <= 0 || blkW <= 0) {
      canvas.style.display = 'none';
      if (canvas.width !== 0) canvas.width = 0;
      return;
    }

    canvas.style.display = 'block';
    canvas.style.left = `${Math.floor(drawStart)}px`;
    canvas.style.width = `${drawW}px`;

    const cw = Math.max(2, Math.round(drawW * dpr));
    const ch = Math.max(2, Math.round(blkH * dpr));
    if (canvas.width !== cw) canvas.width = cw;
    if (canvas.height !== ch) canvas.height = ch;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    ctx.fillStyle = '#141414';
    ctx.fillRect(0, 0, cw, ch);

    const ss = Number(canvas.dataset.ss) || 0;
    const se = Number(canvas.dataset.se) || dur;
    const segSpan = Math.max(0.05, se - ss);
    const tileW = Math.max(36, Math.round(blkH * vidAspect));
    const firstTile = Math.floor(drawStart / tileW);
    const lastTile = Math.floor((drawEnd - 0.5) / tileW);

    for (let k = firstTile; k <= lastTile; k++) {
      const tileLocalX = k * tileW;
      const centerFrac = Math.max(0, Math.min(1, (tileLocalX + tileW * 0.5) / Math.max(1, blkW)));
      const srcT = ss + centerFrac * segSpan;
      const qKey = quantizeThumbTime(srcT, dur);
      let frame = fvFrameCache.get(qKey);
      if (!frame) {
        if (requestMissing) neededTimes.push(qKey);
        frame = getNearestFvCachedFrame(srcT);
      }
      if (frame) {
        const dx = Math.floor((tileLocalX - drawStart) * dpr);
        const dw = Math.ceil(tileW * dpr) + 1;
        drawCoverFrameToTile(ctx, frame, dx, 0, dw, ch);
      }
    }
  });

  if (requestMissing && neededTimes.length > 0 && thumbVideoEl.readyState >= 1) {
    scheduleFvVisibleThumbDecode(neededTimes);
  }
}

function renderFvTracks(clip) {
  clip = clip || activeClip();
  if (!clip) return;
  const layout = computeTimelineLayout(clip);
  const contentDur = layout.totalDur;
  const scaleDur = getTimelineScaleDur(clip);
  const multi = layout.items.length > 1;
  const vArea = document.getElementById('videoTrackArea');

  let html = '';
  layout.items.forEach((item) => {
    const { seg, idx, tlStart, effDur } = item;
    const leftPct = (tlStart / scaleDur) * 100;
    const widthPct = (effDur / scaleDur) * 100;
    const isSel = state.selectedTrack === 'video' && idx === state.selectedSegIdx;
    const gapStyle = multi
      ? `left: calc(${leftPct.toFixed(4)}% + ${idx > 0 ? 1 : 0}px); width: max(3px, calc(${widthPct.toFixed(4)}% - ${idx > 0 && idx < layout.items.length - 1 ? 2 : 1}px));`
      : `left: ${leftPct.toFixed(4)}%; width: max(3px, ${widthPct.toFixed(4)}%);`;
    let speedBadge = '';
    if (seg.speedMode === 'curve' && isSegmentCurveActive(seg)) {
      speedBadge = `<span class="fv-block-badge"><i data-lucide="spline" class="w-2.5 h-2.5"></i><span>Curve</span></span>`;
    } else if (seg.speedMode === 'normal' && Math.abs((seg.speed || 1) - 1) >= 0.02) {
      speedBadge = `<span class="fv-block-badge">${fmtSpeed(seg.speed)}</span>`;
    }
    const label = multi ? `Clip ${idx + 1}` : clip.name;
    html += `
      <div class="fv-tl-block ${isSel ? 'is-selected' : ''}" data-seg-idx="${idx}" style="${gapStyle}">
        <canvas class="fv-block-filmstrip" data-ss="${seg.sourceStart}" data-se="${seg.sourceEnd}"></canvas>
        <div class="absolute inset-0 bg-gradient-to-t from-black/60 via-transparent to-black/35 pointer-events-none z-[1]"></div>
        <div class="seg-grab-bar seg-grab-left" data-edge="start" data-seg-idx="${idx}"></div>
        <div class="relative z-[7] w-full h-full px-3 flex items-center justify-between gap-1.5 text-[11px] text-white pointer-events-none drop-shadow">
          <div class="fv-block-label-wrap flex items-center gap-1.5 min-w-0">
            <span class="font-medium truncate">${escHtml(label)}</span>
            ${speedBadge}
          </div>
          <span class="fv-block-dur text-neutral-200 tabular-nums shrink-0 text-[10.5px]">${fmtMMSS(effDur)}</span>
        </div>
        <div class="seg-grab-bar seg-grab-right" data-edge="end" data-seg-idx="${idx}"></div>
      </div>
    `;
  });

  vArea.innerHTML = html;
  paintFvBlockFilmstrips(true);
  if (window.lucide) lucide.createIcons({ root: vArea });

  vArea.querySelectorAll('.fv-tl-block').forEach((blockEl) => {
    blockEl.addEventListener('pointerdown', (ev) => {
      const idx = Number(blockEl.dataset.segIdx);
      const edge = ev.target?.dataset?.edge;
      if (edge === 'start' || edge === 'end') {
        ev.stopPropagation();
        ev.preventDefault();
        selectFvSegment(idx);
        startFvSegmentTrimDrag(ev, idx, edge);
        return;
      }
      selectFvSegment(idx);
      if (clip.segments.length > 1) {
        ev.stopPropagation();
        startFvSegmentHoldOrScrub(ev, idx, blockEl);
      }
    });
  });

  renderFvAudioTrack(clip, scaleDur);

  const badge = document.getElementById('trimRangeBadge');
  if (badge) badge.textContent = `${fmtMMSS(state.currentTime)} / ${fmtMMSS(contentDur)}`;
}

// Long-press (~250ms) on a video block lifts it for drag-to-reorder; immediate click/drag scrubs playhead cleanly.
function startFvSegmentHoldOrScrub(ev, segIdx, blockEl) {
  const clip = activeClip();
  if (!clip || !isFullVideoMode() || clip.segments.length <= 1) return;
  ev.preventDefault();
  const vArea = document.getElementById('videoTrackArea');
  const vRect = vArea.getBoundingClientRect();
  const scaleDur = getTimelineScaleDur(clip);
  const startX = ev.clientX;
  const startY = ev.clientY;
  let mode = 'pending'; // 'pending' | 'scrub' | 'reorder'
  let targetDropIdx = segIdx;
  let indicatorEl = null;
  const wasPlaying = state.playing;

  const enterScrub = (e) => {
    mode = 'scrub';
    isUserScrubbing = true;
    if (wasPlaying) {
      videoEl.pause();
      pauseAllFvAudioPlayers();
    }
    const ratio = Math.max(0, Math.min(1, (e.clientX - vRect.left) / Math.max(1, vRect.width)));
    seekTo(ratio * scaleDur);
  };

  const holdTimer = setTimeout(() => {
    if (mode !== 'pending') return;
    mode = 'reorder';
    setTimelineEditingIndicator(true);
    blockEl.classList.add('is-reordering');
    indicatorEl = document.createElement('div');
    indicatorEl.className = 'fv-reorder-indicator';
    indicatorEl.style.display = 'none';
    vArea.appendChild(indicatorEl);
  }, 250);

  const onMove = (e) => {
    if (mode === 'pending') {
      if (Math.hypot(e.clientX - startX, e.clientY - startY) >= 5) {
        clearTimeout(holdTimer);
        enterScrub(e);
      }
      return;
    }
    if (mode === 'scrub') {
      const ratio = Math.max(0, Math.min(1, (e.clientX - vRect.left) / Math.max(1, vRect.width)));
      seekTo(ratio * scaleDur);
      return;
    }
    if (mode === 'reorder') {
      const layout = computeTimelineLayout(clip);
      const curRatio = Math.max(0, Math.min(1, (e.clientX - vRect.left) / Math.max(1, vRect.width)));
      const curSec = curRatio * scaleDur;
      let insertAt = layout.items.length;
      for (let i = 0; i < layout.items.length; i++) {
        const mid = layout.items[i].tlStart + layout.items[i].effDur / 2;
        if (curSec < mid) {
          insertAt = i;
          break;
        }
      }
      targetDropIdx = insertAt;
      if (indicatorEl) {
        const pct = insertAt >= layout.items.length
          ? (layout.totalDur / scaleDur) * 100
          : (layout.items[insertAt].tlStart / scaleDur) * 100;
        indicatorEl.style.left = `calc(${pct.toFixed(3)}% - 1px)`;
        indicatorEl.style.display = '';
      }
    }
  };

  const onUp = (e) => {
    clearTimeout(holdTimer);
    window.removeEventListener('pointermove', onMove);
    window.removeEventListener('pointerup', onUp);
    window.removeEventListener('pointercancel', onCancel);
    setTimelineEditingIndicator(false);
    blockEl.classList.remove('is-reordering');
    indicatorEl?.remove();
    if (mode === 'pending') {
      // Quick click: move playhead to clicked position
      const ratio = Math.max(0, Math.min(1, (e.clientX - vRect.left) / Math.max(1, vRect.width)));
      seekTo(ratio * scaleDur);
      return;
    }
    if (mode === 'scrub') {
      isUserScrubbing = false;
      if (wasPlaying && state.playing) {
        const mapped = timelineToSource(clip, state.currentTime);
        requestVideoSeek(mapped.srcTime, true);
      }
      return;
    }
    if (mode === 'reorder') {
      let dest = targetDropIdx > segIdx ? targetDropIdx - 1 : targetDropIdx;
      dest = Math.max(0, Math.min(clip.segments.length - 1, dest));
      if (dest !== segIdx) {
        pushFvHistory();
        const [movedSeg] = clip.segments.splice(segIdx, 1);
        clip.segments.splice(dest, 0, movedSeg);
        syncClipLegacyBounds(clip);
        state.selectedSegIdx = dest;
        state.playingSegIdx = dest;
        const newLayout = computeTimelineLayout(clip);
        seekTo(newLayout.items[dest]?.tlStart || 0, dest);
        renderRuler();
        renderTracks();
        syncFullVideoPanels();
        scheduleDraftSave();
        showToast(`Moved clip to position ${dest + 1}`);
      }
    }
  };

  const onCancel = () => {
    clearTimeout(holdTimer);
    window.removeEventListener('pointermove', onMove);
    window.removeEventListener('pointerup', onUp);
    window.removeEventListener('pointercancel', onCancel);
    setTimelineEditingIndicator(false);
    blockEl.classList.remove('is-reordering');
    indicatorEl?.remove();
    if (mode === 'scrub') {
      isUserScrubbing = false;
      if (wasPlaying && state.playing) {
        const mapped = timelineToSource(clip, state.currentTime);
        requestVideoSeek(mapped.srcTime, true);
      }
    }
  };

  window.addEventListener('pointermove', onMove);
  window.addEventListener('pointerup', onUp);
  window.addEventListener('pointercancel', onCancel);
}

// --- Full Video Multi-Layer NLE Audio Track & Diamond Volume Keyframes ---
const AUDIO_ENV_W = 230;
const AUDIO_ENV_H = 82;
const AUDIO_ENV_PAD_L = 26;
const AUDIO_ENV_PAD_R = 10;
const AUDIO_ENV_PAD_T = 8;
const AUDIO_ENV_PAD_B = 10;
const AUDIO_ENV_PLOT_W = AUDIO_ENV_W - AUDIO_ENV_PAD_L - AUDIO_ENV_PAD_R;
const AUDIO_ENV_PLOT_H = AUDIO_ENV_H - AUDIO_ENV_PAD_T - AUDIO_ENV_PAD_B;

function getAudioFreeGapsOnLane(clip, laneIdx, totalDur, excludeId = null) {
  const list = (clip?.audioClips || [])
    .filter((a) => (a.track || 0) === laneIdx && a.id !== excludeId)
    .slice()
    .sort((a, b) => a.timelineStart - b.timelineStart);
  const gaps = [];
  let cursor = 0;
  for (const ac of list) {
    const s = Math.max(cursor, ac.timelineStart);
    if (s - cursor >= 0.2) gaps.push({ start: cursor, end: s });
    cursor = Math.max(cursor, ac.timelineStart + getAudioClipSpan(ac));
  }
  if (totalDur - cursor >= 0.2) gaps.push({ start: cursor, end: totalDur });
  return gaps;
}

function findNextAudioSlot(clip, desiredStart, desiredDur, excludeId = null, preferredTrack = null) {
  const totalDur = computeTimelineLayout(clip).totalDur;
  const d = Math.max(0.25, Number(desiredDur) || 1);
  const pref = Math.max(0, Math.min(totalDur, Number(desiredStart) || 0));

  const tryLane = (lane) => {
    const gaps = getAudioFreeGapsOnLane(clip, lane, totalDur, excludeId);
    const containing = gaps.find((g) => pref >= g.start - 0.05 && pref <= g.end + 0.05 && (g.end - g.start) >= 0.35);
    if (containing) {
      const avail = containing.end - containing.start;
      if (avail >= d) {
        const st = Math.max(containing.start, Math.min(pref, containing.end - d));
        return { track: lane, start: Number(st.toFixed(3)), span: Number(d.toFixed(3)), exact: true };
      }
      return { track: lane, start: Number(containing.start.toFixed(3)), span: Number(avail.toFixed(3)), exact: false };
    }
    return null;
  };

  // If a preferred lane was requested (e.g. duplicate), try it first
  if (preferredTrack !== null) {
    const hit = tryLane(preferredTrack);
    if (hit) return hit;
  }

  // Try existing lanes (0..7) for a clean slot right at desiredStart (enables overlapping Music + SFX!)
  const usedMax = (clip?.audioClips || []).reduce((m, a) => Math.max(m, a.track || 0), 0);
  const maxLane = Math.min(7, usedMax + 1);
  for (let lane = 0; lane <= maxLane; lane++) {
    const hit = tryLane(lane);
    if (hit && hit.exact) return hit;
  }

  // Fallback: any available gap on lanes 0..maxLane
  for (let lane = 0; lane <= maxLane; lane++) {
    const gaps = getAudioFreeGapsOnLane(clip, lane, totalDur, excludeId);
    const after = gaps.find((g) => g.start >= pref && (g.end - g.start) >= 0.35);
    const chosen = after || gaps.slice().sort((a, b) => (b.end - b.start) - (a.end - a.start))[0];
    if (chosen && (chosen.end - chosen.start) >= 0.3) {
      return {
        track: lane,
        start: Number(chosen.start.toFixed(3)),
        span: Number(Math.min(d, chosen.end - chosen.start).toFixed(3)),
      };
    }
  }
  return null;
}

function getAudioNeighborBounds(clip, audioId, totalDur, overrideLane = null) {
  const target = (clip?.audioClips || []).find((a) => a.id === audioId);
  const lane = overrideLane !== null ? overrideLane : (target?.track || 0);
  const sorted = (clip?.audioClips || [])
    .filter((a) => (a.track || 0) === lane && a.id !== audioId)
    .slice()
    .sort((a, b) => a.timelineStart - b.timelineStart);
  const refStart = target ? target.timelineStart : 0;
  let minStart = 0;
  let maxEnd = totalDur;
  for (const other of sorted) {
    const oEnd = other.timelineStart + getAudioClipSpan(other);
    if (oEnd <= refStart + 0.05) {
      minStart = Math.max(minStart, oEnd);
    } else if (other.timelineStart >= refStart - 0.05) {
      maxEnd = Math.min(maxEnd, other.timelineStart);
      break;
    }
  }
  return { minStart: Math.max(0, minStart), maxEnd: Math.max(minStart, Math.min(totalDur, maxEnd)) };
}

function compactAudioTrackLanes(clip) {
  if (!clip || !Array.isArray(clip.audioClips)) return;
  const used = Array.from(new Set(clip.audioClips.map((a) => a.track || 0))).sort((a, b) => a - b);
  const remap = new Map();
  used.forEach((oldLane, idx) => remap.set(oldLane, idx));
  clip.audioClips.forEach((a) => {
    a.track = remap.get(a.track || 0) ?? 0;
  });
  clip.audioClips.sort((a, b) => (a.track - b.track) || (a.timelineStart - b.timelineStart));
}

function clampFvAudioClipsToVideo(clip) {
  if (!clip || !isFullVideoMode()) return;
  const totalDur = computeTimelineLayout(clip).totalDur;
  const list = clip.audioClips || [];
  for (let i = list.length - 1; i >= 0; i--) {
    const ac = list[i];
    if (ac.timelineStart >= totalDur - 0.15) {
      list.splice(i, 1);
      continue;
    }
    const maxSpan = totalDur - ac.timelineStart;
    if (getAudioClipSpan(ac) > maxSpan) {
      ac.trimEnd = Number((ac.trimStart + maxSpan).toFixed(3));
    }
    const span = getAudioClipSpan(ac);
    if (span < 0.15) {
      list.splice(i, 1);
      continue;
    }
    const maxFade = Number((span / 2).toFixed(2));
    ac.fadeIn = Math.min(ac.fadeIn || 0, maxFade);
    ac.fadeOut = Math.min(ac.fadeOut || 0, maxFade);
    ac.keyframes = sanitizeAudioKeyframes(ac.keyframes, span);
  }
  compactAudioTrackLanes(clip);
  if (state.selectedTrack === 'audio' && !list.some((a) => a.id === state.selectedAudioId)) {
    state.selectedTrack = 'video';
    state.selectedAudioId = null;
    applyFvRightPanelMode();
  }
}

function buildAudioBlockMiniOverlay(ac, span) {
  const W = 400;
  const H = 32;
  let svg = '';
  const fi = Math.max(0, Math.min(span / 2, Number(ac.fadeIn) || 0));
  const fo = Math.max(0, Math.min(span / 2, Number(ac.fadeOut) || 0));
  if (fi > 0.02) {
    const x = Math.min(W * 0.5, (fi / span) * W).toFixed(1);
    svg += `<polygon points="0,0 ${x},0 0,${H}" fill="rgba(0,0,0,0.52)" />`;
    svg += `<line x1="0" y1="${H}" x2="${x}" y2="2" stroke="rgba(255,255,255,0.45)" stroke-width="1.2" />`;
  }
  if (fo > 0.02) {
    const x = Math.max(W * 0.5, W - (fo / span) * W).toFixed(1);
    svg += `<polygon points="${x},0 ${W},0 ${W},${H}" fill="rgba(0,0,0,0.52)" />`;
    svg += `<line x1="${x}" y1="2" x2="${W}" y2="${H}" stroke="rgba(255,255,255,0.45)" stroke-width="1.2" />`;
  }
  const kfs = ac.keyframes || [];
  if (kfs.length > 0) {
    const pts = [];
    const volToY = (v) => (H - 3 - (Math.max(0, Math.min(100, v)) / 100) * (H - 6)).toFixed(1);
    pts.push(`0,${volToY(kfs[0].vol)}`);
    kfs.forEach((k) => {
      pts.push(`${((k.t / span) * W).toFixed(1)},${volToY(k.vol)}`);
    });
    pts.push(`${W},${volToY(kfs[kfs.length - 1].vol)}`);
    svg += `<polyline points="${pts.join(' ')}" fill="none" stroke="rgba(255,255,255,0.72)" stroke-width="1.2" vector-effect="non-scaling-stroke" />`;
  }
  return svg;
}

function buildAudioBlockKfMarkers(ac, span) {
  const kfs = ac.keyframes || [];
  if (!kfs.length) return '';
  return kfs.map((k) => {
    const leftPct = Math.max(0, Math.min(100, (k.t / span) * 100)).toFixed(2);
    const v = Math.max(0, Math.min(100, Number(k.vol) || 0));
    const topPx = (3 + (1 - v / 100) * 26).toFixed(1);
    return `<span class="pointer-events-none absolute z-[5] w-[6px] h-[6px] bg-white border border-[#0d0d0d]" style="left:${leftPct}%;top:${topPx}px;transform:translate(-50%,-50%) rotate(45deg);border-radius:1px;"></span>`;
  }).join('');
}

function renderFvAudioTrack(clip, totalDur) {
  const audioClips = clip.audioClips || [];
  const hasMusic = audioClips.length > 0;
  document.getElementById('musicTrackRow').classList.toggle('hidden', !hasMusic);
  document.getElementById('musicIconRail')?.classList.toggle('hidden', !hasMusic);
  document.getElementById('musicActionRail')?.classList.toggle('hidden', !hasMusic);

  const laneCount = hasMusic
    ? Math.min(8, audioClips.reduce((m, a) => Math.max(m, (a.track || 0) + 1), 1))
    : 0;
  const tlPanel = document.getElementById('timelinePanel');
  tlPanel.classList.remove('h-[164px]', 'h-[174px]', 'h-[204px]');
  const visibleLanes = Math.min(3, laneCount);
  const targetH = hasMusic ? (178 + visibleLanes * 38) : 174;
  tlPanel.style.height = `${targetH}px`;

  const lbl = document.getElementById('customAudioLabel');
  if (lbl) {
    lbl.textContent = !hasMusic ? 'Add Music' : (audioClips.length === 1 ? audioClips[0].name : `Music (${audioClips.length})`);
  }

  const rowActionBtn = document.getElementById('btnMusicRowAction');
  if (rowActionBtn) {
    setLunaTooltip(rowActionBtn, 'Add audio track');
    rowActionBtn.innerHTML = '<i data-lucide="plus" class="w-4 h-4"></i>';
    if (window.lucide) lucide.createIcons({ root: rowActionBtn });
  }

  const iconRail = document.getElementById('musicIconRail');
  if (iconRail && hasMusic) {
    let railHtml = '';
    for (let l = 0; l < visibleLanes; l++) {
      railHtml += `<div class="h-8 shrink-0 flex items-center justify-center text-neutral-500"><i data-lucide="music" class="w-3.5 h-3.5"></i></div>`;
    }
    iconRail.innerHTML = railHtml;
    if (window.lucide) lucide.createIcons({ root: iconRail });
  }

  if (!hasMusic) return;

  const aArea = document.getElementById('audioTrackArea');
  aArea.className = 'relative flex flex-col gap-1.5 cursor-pointer';
  let lanesHtml = '';
  for (let lane = 0; lane < laneCount; lane++) {
    const laneClips = audioClips.filter((a) => (a.track || 0) === lane);
    let blocksHtml = '';
    laneClips.forEach((ac) => {
      const span = getAudioClipSpan(ac);
      const leftPct = Math.max(0, Math.min(99.9, (ac.timelineStart / totalDur) * 100));
      const widthPct = Math.max(0.05, Math.min(100 - leftPct, (span / totalDur) * 100));
      const isSel = state.selectedTrack === 'audio' && state.selectedAudioId === ac.id;
      const peaks = (ac.peaks && ac.peaks.length) ? ac.peaks : defaultPeaks(96);
      const slicePeaks = sampleMusicSlicePeaks(peaks, ac.sourceDur, ac.trimStart, span, 64);
      const durHtml = widthPct * (state.tlZoom || 1) >= 11 ? `<span class="text-neutral-300 tabular-nums shrink-0 text-[10px]">${fmtMMSS(span)}</span>` : '';
      blocksHtml += `
        <div class="fv-audio-block ${isSel ? 'is-selected' : ''}" data-audio-id="${escHtml(ac.id)}" data-lane="${lane}"
          style="left: ${leftPct.toFixed(4)}%; width: max(4px, ${widthPct.toFixed(4)}%);">
          <svg class="h-full w-full absolute inset-0 pointer-events-none" viewBox="0 0 400 32" preserveAspectRatio="none">
            ${buildModernWaveArea(slicePeaks, 400, 32)}
            ${buildAudioBlockMiniOverlay(ac, span)}
          </svg>
          ${buildAudioBlockKfMarkers(ac, span)}
          <div class="seg-grab-bar seg-grab-left" data-edge="start" data-audio-id="${escHtml(ac.id)}"></div>
          <div class="relative z-[6] px-3.5 h-full flex items-center justify-between gap-1.5 text-[10.5px] text-neutral-100 pointer-events-none drop-shadow min-w-0">
            <span class="truncate font-medium min-w-0">${escHtml(ac.name)}</span>
            ${durHtml}
          </div>
          <div class="seg-grab-bar seg-grab-right" data-edge="end" data-audio-id="${escHtml(ac.id)}"></div>
        </div>
      `;
    });
    lanesHtml += `<div class="fv-audio-lane" data-lane="${lane}">${blocksHtml}</div>`;
  }

  aArea.innerHTML = lanesHtml;

  aArea.querySelectorAll('.fv-audio-block').forEach((el) => {
    el.addEventListener('pointerdown', (ev) => {
      ev.stopPropagation();
      const audioId = el.dataset.audioId;
      const edge = ev.target?.dataset?.edge;
      selectFvAudioClip(audioId);
      if (edge === 'start' || edge === 'end') {
        ev.preventDefault();
        startFvAudioTrimDrag(ev, audioId, edge);
        return;
      }
      startFvAudioMoveDrag(ev, audioId, el);
    });
  });
}

function startFvAudioMoveDrag(ev, audioId, blockEl) {
  const clip = activeClip();
  if (!clip || !isFullVideoMode()) return;
  const ac = (clip.audioClips || []).find((a) => a.id === audioId);
  if (!ac) return;
  const layout = computeTimelineLayout(clip);
  const contentDur = Math.max(0.5, layout.totalDur);
  const scaleDur = getTimelineScaleDur(clip);
  const span = getAudioClipSpan(ac);
  const trackEl = document.getElementById('audioTrackArea');
  const trackRect = trackEl.getBoundingClientRect();
  const startX = ev.clientX;
  const startY = ev.clientY;
  const origStart = ac.timelineStart;
  const origTrack = ac.track || 0;
  const preSnap = snapshotFvState(clip);
  const snapPointsBase = collectTimelineSnapTargets(clip, audioId);
  let moved = false;
  let targetLane = origTrack;

  const canPlaceOnLane = (lane, startSec) => {
    const others = (clip.audioClips || []).filter((a) => (a.track || 0) === lane && a.id !== audioId);
    const endSec = startSec + span;
    return !others.some((o) => {
      const oEnd = o.timelineStart + getAudioClipSpan(o);
      return startSec < oEnd - 0.04 && endSec > o.timelineStart + 0.04;
    });
  };

  const onMove = (e) => {
    const dx = e.clientX - startX;
    const dy = e.clientY - startY;
    if (!moved && Math.hypot(dx, dy) < 4) return;
    if (!moved) {
      moved = true;
      setTimelineEditingIndicator(true);
      state.fvHistory.push(preSnap);
      if (state.fvHistory.length > 40) state.fvHistory.shift();
      state.fvFuture = [];
      blockEl.classList.add('is-dragging');
    }

    // Determine target lane from vertical drag offset (each lane is ~38px tall)
    const laneDelta = Math.round(dy / 36);
    const usedMax = (clip.audioClips || []).reduce((m, a) => Math.max(m, a.track || 0), 0);
    const maxAllowedLane = Math.min(7, usedMax + 1);
    const candidateLane = Math.max(0, Math.min(maxAllowedLane, origTrack + laneDelta));

    const deltaSec = (dx / Math.max(120, trackRect.width)) * scaleDur;
    let nextStart = Math.max(0, Math.min(Math.max(0, contentDur - span), origStart + deltaSec));

    if (candidateLane === ac.track || canPlaceOnLane(candidateLane, nextStart)) {
      targetLane = candidateLane;
    }

    const bounds = getAudioNeighborBounds(clip, audioId, contentDur, targetLane);
    if (targetLane === origTrack) {
      nextStart = Math.max(bounds.minStart, Math.min(bounds.maxEnd - span, nextStart));
    }

    // Gentle magnetic snap (8px screen-space radius) on start or end edge
    const snapCandidates = [...snapPointsBase, bounds.minStart, bounds.maxEnd];
    const startSnap = findMagneticSnap(nextStart, snapCandidates, trackRect.width, scaleDur);
    const endSnap = findMagneticSnap(nextStart + span, snapCandidates, trackRect.width, scaleDur);
    let snappedLineSec = null;
    if (startSnap.snapped && startSnap.value >= 0 && startSnap.value + span <= contentDur + 0.01 && canPlaceOnLane(targetLane, startSnap.value)) {
      nextStart = startSnap.value;
      snappedLineSec = startSnap.value;
    } else if (endSnap.snapped && endSnap.value - span >= 0 && endSnap.value <= contentDur + 0.01 && canPlaceOnLane(targetLane, endSnap.value - span)) {
      nextStart = endSnap.value - span;
      snappedLineSec = endSnap.value;
    }
    if (snappedLineSec !== null) showTlSnapGuide(snappedLineSec, scaleDur);
    else hideTlSnapGuide();

    if (canPlaceOnLane(targetLane, nextStart)) {
      ac.timelineStart = Number(Math.max(0, Math.min(Math.max(0, contentDur - span), nextStart)).toFixed(3));
      ac.track = targetLane;
    }
    blockEl.style.left = `${((ac.timelineStart / scaleDur) * 100).toFixed(4)}%`;
    trackEl.querySelectorAll('.fv-audio-lane').forEach((ln) => {
      ln.classList.toggle('is-drop-target', Number(ln.dataset.lane) === targetLane && targetLane !== origTrack);
    });
    const rangeEl = document.getElementById('fvAudioTimeRange');
    if (rangeEl) rangeEl.textContent = `${fmtMMSS(ac.timelineStart)} – ${fmtMMSS(ac.timelineStart + span)}`;
    updateFvAudioEnvPlayhead();
  };

  const onUp = () => {
    window.removeEventListener('pointermove', onMove);
    window.removeEventListener('pointerup', onUp);
    setTimelineEditingIndicator(false);
    hideTlSnapGuide();
    blockEl.classList.remove('is-dragging');
    trackEl.querySelectorAll('.fv-audio-lane').forEach((ln) => ln.classList.remove('is-drop-target'));
    if (moved) {
      compactAudioTrackLanes(clip);
      syncClipAudioElement();
      renderTracks();
      syncFvAudioInspector();
      updateFvToolbarState();
      scheduleDraftSave();
    }
  };
  window.addEventListener('pointermove', onMove);
  window.addEventListener('pointerup', onUp);
}

function startFvAudioTrimDrag(ev, audioId, edge) {
  const clip = activeClip();
  if (!clip || !isFullVideoMode()) return;
  const ac = (clip.audioClips || []).find((a) => a.id === audioId);
  if (!ac) return;
  const contentDur = Math.max(0.5, computeTimelineLayout(clip).totalDur);
  const scaleDur = getTimelineScaleDur(clip);
  const bounds = getAudioNeighborBounds(clip, audioId, contentDur);
  const snapTargets = collectTimelineSnapTargets(clip, audioId);
  const trackRect = document.getElementById('audioTrackArea').getBoundingClientRect();
  const startX = ev.clientX;
  const origTlStart = ac.timelineStart;
  const origTrimStart = ac.trimStart;
  const origTrimEnd = ac.trimEnd;
  const origKfs = (ac.keyframes || []).map((k) => ({ ...k }));
  const preSnap = snapshotFvState(clip);
  let moved = false;

  const onMove = (e) => {
    const dx = e.clientX - startX;
    if (!moved && Math.abs(dx) < 3) return;
    if (!moved) {
      moved = true;
      setTimelineEditingIndicator(true);
      state.fvHistory.push(preSnap);
      if (state.fvHistory.length > 40) state.fvHistory.shift();
      state.fvFuture = [];
    }
    const deltaSec = (dx / Math.max(120, trackRect.width)) * scaleDur;
    if (edge === 'start') {
      const minDelta = Math.max(-origTrimStart, bounds.minStart - origTlStart);
      const maxDelta = (origTrimEnd - origTrimStart) - 0.3;
      let rawStart = origTlStart + Math.max(minDelta, Math.min(maxDelta, deltaSec));
      const snap = findMagneticSnap(rawStart, snapTargets, trackRect.width, scaleDur);
      if (snap.snapped) {
        const snappedDelta = snap.value - origTlStart;
        if (snappedDelta >= minDelta - 0.005 && snappedDelta <= maxDelta + 0.005) {
          rawStart = snap.value;
          showTlSnapGuide(snap.value, scaleDur);
        } else {
          hideTlSnapGuide();
        }
      } else {
        hideTlSnapGuide();
      }
      const applied = Math.max(minDelta, Math.min(maxDelta, rawStart - origTlStart));
      ac.timelineStart = Number((origTlStart + applied).toFixed(3));
      ac.trimStart = Number((origTrimStart + applied).toFixed(3));
      const newSpan = getAudioClipSpan(ac);
      ac.keyframes = sanitizeAudioKeyframes(
        origKfs.map((k) => ({ t: k.t - applied, vol: k.vol })).filter((k) => k.t >= -0.01 && k.t <= newSpan + 0.01),
        newSpan
      );
    } else {
      const maxEndBySource = ac.sourceDur;
      const maxEndByBound = origTrimStart + (bounds.maxEnd - origTlStart);
      const maxTrimEnd = Math.min(maxEndBySource, maxEndByBound);
      let nextTrimEnd = Math.max(origTrimStart + 0.3, Math.min(maxTrimEnd, origTrimEnd + deltaSec));
      const rawTlEnd = origTlStart + (nextTrimEnd - origTrimStart);
      const snap = findMagneticSnap(rawTlEnd, snapTargets, trackRect.width, scaleDur);
      if (snap.snapped) {
        const candTrimEnd = origTrimStart + (snap.value - origTlStart);
        if (candTrimEnd >= origTrimStart + 0.3 && candTrimEnd <= maxTrimEnd + 0.005) {
          nextTrimEnd = Math.min(maxTrimEnd, candTrimEnd);
          showTlSnapGuide(snap.value, scaleDur);
        } else {
          hideTlSnapGuide();
        }
      } else {
        hideTlSnapGuide();
      }
      ac.trimEnd = Number(nextTrimEnd.toFixed(3));
      const newSpan = getAudioClipSpan(ac);
      ac.keyframes = sanitizeAudioKeyframes(
        origKfs.filter((k) => k.t <= newSpan + 0.01),
        newSpan
      );
    }
    const span = getAudioClipSpan(ac);
    const maxFade = Number((span / 2).toFixed(2));
    ac.fadeIn = Math.min(ac.fadeIn || 0, maxFade);
    ac.fadeOut = Math.min(ac.fadeOut || 0, maxFade);
    renderFvAudioTrack(clip, scaleDur);
    syncFvAudioInspector();
    updateFvToolbarState();
  };

  const onUp = () => {
    window.removeEventListener('pointermove', onMove);
    window.removeEventListener('pointerup', onUp);
    window.removeEventListener('pointercancel', onUp);
    setTimelineEditingIndicator(false);
    hideTlSnapGuide();
    if (moved) {
      syncClipAudioElement();
      scheduleDraftSave();
    }
  };
  window.addEventListener('pointermove', onMove);
  window.addEventListener('pointerup', onUp);
  window.addEventListener('pointercancel', onUp);
}

function splitAudioClipAtPlayhead() {
  const clip = activeClip();
  const ac = activeAudioClip();
  if (!clip || !ac || !isFullVideoMode()) return;
  const span = getAudioClipSpan(ac);
  const splitOffset = state.currentTime - ac.timelineStart;
  if (splitOffset <= 0.25 || splitOffset >= span - 0.25) {
    showToast('Move playhead inside the selected audio clip to split');
    return;
  }
  pushFvHistory();
  const kfs = ac.keyframes || [];
  const boundaryVol = Number(evalAudioVolumeAt(ac, splitOffset).toFixed(1));
  const leftKfs = kfs.length
    ? sanitizeAudioKeyframes([...kfs.filter((k) => k.t < splitOffset - 0.02), { t: splitOffset, vol: boundaryVol }], splitOffset)
    : [];
  const rightSpan = span - splitOffset;
  const rightKfs = kfs.length
    ? sanitizeAudioKeyframes([{ t: 0, vol: boundaryVol }, ...kfs.filter((k) => k.t > splitOffset + 0.02).map((k) => ({ t: k.t - splitOffset, vol: k.vol }))], rightSpan)
    : [];

  const leftAc = makeAudioClip({
    ...ac,
    trimEnd: ac.trimStart + splitOffset,
    fadeOut: 0,
    fadeIn: Math.min(ac.fadeIn || 0, splitOffset / 2),
    keyframes: leftKfs,
  });
  const rightAc = makeAudioClip({
    ...ac,
    id: `aud_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 5)}`,
    timelineStart: ac.timelineStart + splitOffset,
    trimStart: ac.trimStart + splitOffset,
    trimEnd: ac.trimEnd,
    fadeIn: 0,
    fadeOut: Math.min(ac.fadeOut || 0, rightSpan / 2),
    keyframes: rightKfs,
  });
  const idx = clip.audioClips.findIndex((a) => a.id === ac.id);
  clip.audioClips.splice(idx, 1, leftAc, rightAc);
  selectFvAudioClip(rightAc.id);
  syncClipAudioElement();
  renderTracks();
  updateFvToolbarState();
  scheduleDraftSave();
  showToast(`Split audio into ${clip.audioClips.length} blocks`);
}

function duplicateSelectedAudioClip() {
  const clip = activeClip();
  const ac = activeAudioClip();
  if (!clip || !ac || !isFullVideoMode()) return;
  const span = getAudioClipSpan(ac);
  const slot = findNextAudioSlot(clip, ac.timelineStart + span, span, null, ac.track || 0);
  if (!slot) {
    showToast('No free space left on audio tracks');
    return;
  }
  pushFvHistory();
  const copy = makeAudioClip({
    ...ac,
    id: `aud_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 5)}`,
    track: slot.track || 0,
    timelineStart: slot.start,
    trimEnd: Math.min(ac.sourceDur, ac.trimStart + slot.span),
    keyframes: (ac.keyframes || []).map((k) => ({ ...k })).filter((k) => k.t <= slot.span),
  });
  clip.audioClips.push(copy);
  compactAudioTrackLanes(clip);
  selectFvAudioClip(copy.id);
  syncClipAudioElement();
  renderTracks();
  updateFvExportInfo();
  scheduleDraftSave();
  showToast(`Duplicated audio at ${fmtMMSS(copy.timelineStart)}`);
}

function deleteSelectedAudioClip() {
  const clip = activeClip();
  const ac = activeAudioClip();
  if (!clip || !ac || !isFullVideoMode()) return;
  pushFvHistory();
  const idx = clip.audioClips.findIndex((a) => a.id === ac.id);
  if (idx >= 0) clip.audioClips.splice(idx, 1);
  compactAudioTrackLanes(clip);
  if (clip.audioClips.length > 0) {
    const next = clip.audioClips[Math.min(idx, clip.audioClips.length - 1)];
    state.selectedAudioId = next.id;
  } else {
    state.selectedTrack = 'video';
    state.selectedAudioId = null;
  }
  syncClipAudioElement();
  renderTracks();
  applyFvRightPanelMode();
  updateFvExportInfo();
  scheduleDraftSave();
  showToast('Audio clip removed');
}

function openFvAudioTrimModal() {
  const ac = activeAudioClip();
  if (!ac || !isFullVideoMode()) return;
  const span = getAudioClipSpan(ac);
  if (ac.sourceDur <= span + 0.5) return;
  state.editingAudioClipId = ac.id;
  state.draftMusic = {
    name: ac.name,
    assetName: ac.assetName,
    url: ac.url,
    totalDur: ac.sourceDur,
    targetSpan: span,
    sliceStart: ac.trimStart,
    volume: ac.volume,
    peaks: ac.peaks || [],
  };
  openMusicModal(false);
}

function findKeyframeNear(ac, localT) {
  if (!ac || !ac.keyframes || !ac.keyframes.length) return -1;
  const span = getAudioClipSpan(ac);
  const thresh = Math.max(0.25, span * 0.025);
  let best = -1;
  let bestD = thresh;
  ac.keyframes.forEach((k, idx) => {
    const d = Math.abs(k.t - localT);
    if (d <= bestD) {
      bestD = d;
      best = idx;
    }
  });
  return best;
}

function setFvAudioVolume(val) {
  const ac = activeAudioClip();
  if (!ac || !isFullVideoMode()) return;
  const v = Math.max(0, Math.min(100, Math.round(Number(val) || 0)));
  const span = getAudioClipSpan(ac);
  const localT = state.currentTime - ac.timelineStart;
  const playheadInside = localT >= -0.05 && localT <= span + 0.05;

  if (ac.keyframes && ac.keyframes.length > 0) {
    let clampedT = 0;
    if (playheadInside) {
      clampedT = Number(Math.max(0, Math.min(span, localT)).toFixed(3));
    } else {
      // Seek playhead onto clip start so the user edits the visible keyframe value instead of snapping back
      seekTo(ac.timelineStart);
    }
    const nearIdx = findKeyframeNear(ac, clampedT);
    if (nearIdx >= 0) {
      ac.keyframes[nearIdx].vol = v;
    } else {
      if (ac.keyframes.length >= 32) {
        showToast('Maximum 32 volume keyframes per audio clip');
        syncFvAudioInspector();
        return;
      }
      ac.keyframes.push({ t: clampedT, vol: v });
      ac.keyframes = sanitizeAudioKeyframes(ac.keyframes, span);
    }
  } else {
    ac.volume = v;
  }

  syncFvAudioInspector();
  renderFvAudioTrack(activeClip(), getTimelineScaleDur(activeClip()));
  syncMusicTimeToVideo(false);
  scheduleDraftSave();
}

function jumpAudioKeyframe(dir) {
  const ac = activeAudioClip();
  if (!ac || !isFullVideoMode() || !ac.keyframes?.length) return;
  const kfs = ac.keyframes;
  const localT = state.currentTime - ac.timelineStart;
  let target = null;
  if (dir < 0) {
    for (let i = kfs.length - 1; i >= 0; i--) {
      if (kfs[i].t < localT - 0.08) {
        target = kfs[i];
        break;
      }
    }
    if (!target) target = kfs[0];
  } else {
    for (let i = 0; i < kfs.length; i++) {
      if (kfs[i].t > localT + 0.08) {
        target = kfs[i];
        break;
      }
    }
    if (!target) target = kfs[kfs.length - 1];
  }
  if (target) {
    seekTo(ac.timelineStart + target.t);
    syncFvAudioInspector();
  }
}

function toggleAudioKeyframeAtPlayhead() {
  const ac = activeAudioClip();
  if (!ac || !isFullVideoMode()) return;
  const span = getAudioClipSpan(ac);
  let localT = state.currentTime - ac.timelineStart;
  if (localT < -0.05 || localT > span + 0.05) {
    showToast('Move playhead inside the audio clip to place a keyframe');
    return;
  }
  const clampedT = Number(Math.max(0, Math.min(span, localT)).toFixed(3));
  const nearIdx = findKeyframeNear(ac, clampedT);
  if (nearIdx < 0 && (ac.keyframes || []).length >= 32) {
    showToast('Maximum 32 volume keyframes per audio clip');
    return;
  }
  pushFvHistory();
  if (nearIdx >= 0) {
    ac.keyframes.splice(nearIdx, 1);
    showToast('Removed volume keyframe');
  } else {
    const curVol = Math.round(evalAudioVolumeAt(ac, clampedT));
    ac.keyframes = sanitizeAudioKeyframes([...(ac.keyframes || []), { t: clampedT, vol: curVol }], span);
    showToast(`Added keyframe at ${fmtMMSS(ac.timelineStart + clampedT)} (${curVol}%)`);
  }
  syncFvAudioInspector();
  renderTracks();
  syncMusicTimeToVideo(false);
  scheduleDraftSave();
}

function clearAudioKeyframes() {
  const ac = activeAudioClip();
  if (!ac || !isFullVideoMode() || !ac.keyframes?.length) return;
  pushFvHistory();
  ac.keyframes = [];
  syncFvAudioInspector();
  renderTracks();
  syncMusicTimeToVideo(false);
  scheduleDraftSave();
  showToast('Cleared volume points');
}

function setFvAudioFade(side, val) {
  const ac = activeAudioClip();
  if (!ac || !isFullVideoMode()) return;
  const span = getAudioClipSpan(ac);
  const maxFade = Number(Math.min(10, span / 2).toFixed(1));
  const v = Number(Math.max(0, Math.min(maxFade, Number(val) || 0)).toFixed(1));
  if (side === 'in') ac.fadeIn = v;
  else ac.fadeOut = v;
  syncFvAudioInspector();
  renderFvAudioTrack(activeClip(), getTimelineScaleDur(activeClip()));
  syncMusicTimeToVideo(false);
  scheduleDraftSave();
}

function resetFvAudioFades() {
  const ac = activeAudioClip();
  if (!ac || !isFullVideoMode()) return;
  if (!ac.fadeIn && !ac.fadeOut) return;
  pushFvHistory();
  ac.fadeIn = 0;
  ac.fadeOut = 0;
  syncFvAudioInspector();
  renderTracks();
  syncMusicTimeToVideo(false);
  scheduleDraftSave();
  showToast('Audio fades reset');
}

function audioEnvVolToY(vol) {
  const frac = Math.max(0, Math.min(1, (Number(vol) || 0) / 100));
  return AUDIO_ENV_PAD_T + (1 - frac) * AUDIO_ENV_PLOT_H;
}

function audioEnvYToVol(y) {
  const frac = Math.max(0, Math.min(1, 1 - (y - AUDIO_ENV_PAD_T) / AUDIO_ENV_PLOT_H));
  return Math.round(frac * 100);
}

function audioEnvTimeToX(localT, span) {
  const frac = Math.max(0, Math.min(1, (Number(localT) || 0) / Math.max(0.15, span)));
  return AUDIO_ENV_PAD_L + frac * AUDIO_ENV_PLOT_W;
}

function audioEnvXToTime(x, span) {
  const frac = Math.max(0, Math.min(1, (x - AUDIO_ENV_PAD_L) / AUDIO_ENV_PLOT_W));
  return Number((frac * Math.max(0.15, span)).toFixed(3));
}

function syncFvAudioInspector() {
  const ac = activeAudioClip();
  if (!ac || !isFullVideoMode()) return;
  const span = getAudioClipSpan(ac);
  const nameEl = document.getElementById('fvAudioName');
  const rangeEl = document.getElementById('fvAudioTimeRange');
  if (nameEl) nameEl.textContent = ac.name;
  if (rangeEl) rangeEl.textContent = `${fmtMMSS(ac.timelineStart)} – ${fmtMMSS(ac.timelineStart + span)}`;

  const localT = state.currentTime - ac.timelineStart;
  const inside = localT >= -0.05 && localT <= span + 0.05;
  const curVol = Math.round(inside ? evalAudioVolumeAt(ac, Math.max(0, Math.min(span, localT))) : (ac.keyframes?.length ? evalAudioVolumeAt(ac, 0) : ac.volume));

  const volSlider = document.getElementById('fvAudioVolSlider');
  const volLabel = document.getElementById('fvAudioVolLabel');
  if (volSlider) volSlider.value = curVol;
  if (volLabel) volLabel.textContent = `${curVol}%`;

  const kfCount = (ac.keyframes || []).length;
  const kfCountEl = document.getElementById('fvAudioKfCount');
  if (kfCountEl) kfCountEl.textContent = `${kfCount} ${kfCount === 1 ? 'pt' : 'pts'}`;
  document.getElementById('btnAudioKfClear')?.classList.toggle('hidden', kfCount === 0);

  const onKf = inside && findKeyframeNear(ac, Math.max(0, Math.min(span, localT))) >= 0;
  const kfBtn = document.getElementById('btnAudioKfToggle');
  if (kfBtn) {
    kfBtn.classList.toggle('is-on-kf', onKf);
    setLunaTooltip(kfBtn, onKf ? 'Remove keyframe' : 'Add keyframe');
  }
  const prevBtn = document.getElementById('btnAudioKfPrev');
  const nextBtn = document.getElementById('btnAudioKfNext');
  if (prevBtn) prevBtn.disabled = kfCount === 0;
  if (nextBtn) nextBtn.disabled = kfCount === 0;

  const readout = document.getElementById('fvAudioEnvReadout');
  if (readout) {
    readout.textContent = kfCount > 0 ? `Envelope · ${curVol}%` : `Flat · ${ac.volume}%`;
  }

  const maxFade = Number(Math.min(10, span / 2).toFixed(1));
  const fiSlider = document.getElementById('fvAudioFadeInSlider');
  const foSlider = document.getElementById('fvAudioFadeOutSlider');
  const fiLabel = document.getElementById('fvAudioFadeInLabel');
  const foLabel = document.getElementById('fvAudioFadeOutLabel');
  if (fiSlider) { fiSlider.max = String(maxFade); fiSlider.value = String(ac.fadeIn || 0); }
  if (foSlider) { foSlider.max = String(maxFade); foSlider.value = String(ac.fadeOut || 0); }
  if (fiLabel) fiLabel.textContent = `${(ac.fadeIn || 0).toFixed(1)}s`;
  if (foLabel) foLabel.textContent = `${(ac.fadeOut || 0).toFixed(1)}s`;

  const trimBtn = document.getElementById('btnFvAudioTrimSource');
  if (trimBtn) trimBtn.classList.toggle('hidden', ac.sourceDur <= span + 0.5);

  renderFvAudioEnvSvg();
}

function renderFvAudioEnvSvg(dragIdx = -1) {
  const svg = document.getElementById('fvAudioEnvSvg');
  const ac = activeAudioClip();
  if (!svg || !ac || !isFullVideoMode()) return;
  const span = getAudioClipSpan(ac);
  const kfs = ac.keyframes || [];

  const gridLevels = [
    { v: 100, label: '100' },
    { v: 50, label: '50' },
    { v: 0, label: '0' },
  ];
  let gridHtml = '';
  gridLevels.forEach((g) => {
    const y = audioEnvVolToY(g.v);
    gridHtml += `<line x1="${AUDIO_ENV_PAD_L}" y1="${y.toFixed(1)}" x2="${AUDIO_ENV_W - AUDIO_ENV_PAD_R}" y2="${y.toFixed(1)}" stroke="rgba(255,255,255,0.08)" stroke-width="1" stroke-dasharray="2 3" />`;
    gridHtml += `<text x="${AUDIO_ENV_PAD_L - 4}" y="${(y + 3).toFixed(1)}" text-anchor="end" fill="#6b6b6b" font-size="8" font-family="ui-monospace,monospace">${g.label}</text>`;
  });

  // Fade In / Fade Out translucent ramp shading on the envelope graph
  let fadeHtml = '';
  const baseY = audioEnvVolToY(0);
  if ((ac.fadeIn || 0) > 0.02) {
    const fx = audioEnvTimeToX(Math.min(ac.fadeIn, span / 2), span);
    fadeHtml += `<polygon points="${AUDIO_ENV_PAD_L},${AUDIO_ENV_PAD_T} ${fx.toFixed(1)},${AUDIO_ENV_PAD_T} ${AUDIO_ENV_PAD_L},${baseY.toFixed(1)}" fill="rgba(255,255,255,0.05)" />`;
  }
  if ((ac.fadeOut || 0) > 0.02) {
    const fx = audioEnvTimeToX(Math.max(span / 2, span - ac.fadeOut), span);
    const rx = AUDIO_ENV_W - AUDIO_ENV_PAD_R;
    fadeHtml += `<polygon points="${fx.toFixed(1)},${AUDIO_ENV_PAD_T} ${rx},${AUDIO_ENV_PAD_T} ${rx},${baseY.toFixed(1)}" fill="rgba(255,255,255,0.05)" />`;
  }

  // Build piecewise volume path
  const linePts = [];
  if (kfs.length === 0) {
    const y = audioEnvVolToY(ac.volume);
    linePts.push([AUDIO_ENV_PAD_L, y], [AUDIO_ENV_W - AUDIO_ENV_PAD_R, y]);
  } else {
    linePts.push([AUDIO_ENV_PAD_L, audioEnvVolToY(kfs[0].vol)]);
    kfs.forEach((k) => linePts.push([audioEnvTimeToX(k.t, span), audioEnvVolToY(k.vol)]));
    linePts.push([AUDIO_ENV_W - AUDIO_ENV_PAD_R, audioEnvVolToY(kfs[kfs.length - 1].vol)]);
  }
  const polyStr = linePts.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ');
  const areaStr = `${polyStr} ${(AUDIO_ENV_W - AUDIO_ENV_PAD_R).toFixed(1)},${baseY.toFixed(1)} ${AUDIO_ENV_PAD_L},${baseY.toFixed(1)}`;

  let dotsHtml = '';
  kfs.forEach((k, i) => {
    const cx = audioEnvTimeToX(k.t, span).toFixed(1);
    const cy = audioEnvVolToY(k.vol).toFixed(1);
    const dragging = i === dragIdx ? 'is-dragging' : '';
    dotsHtml += `
      <g class="audio-kf-group ${dragging}" data-kf-idx="${i}">
        <circle cx="${cx}" cy="${cy}" r="11" fill="transparent" />
        <circle class="audio-kf-dot" cx="${cx}" cy="${cy}" r="4.2" />
      </g>
    `;
  });

  svg.innerHTML = `
    <defs>
      <linearGradient id="audioEnvAreaGrad" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="rgba(255,255,255,0.22)" />
        <stop offset="100%" stop-color="rgba(255,255,255,0.02)" />
      </linearGradient>
    </defs>
    ${gridHtml}
    ${fadeHtml}
    <polygon points="${areaStr}" fill="url(#audioEnvAreaGrad)" />
    <polyline points="${polyStr}" fill="none" stroke="#ffffff" stroke-width="1.75" stroke-linejoin="round" stroke-linecap="round" />
    <line id="fvAudioEnvPlayhead" x1="${AUDIO_ENV_PAD_L}" y1="${AUDIO_ENV_PAD_T}" x2="${AUDIO_ENV_PAD_L}" y2="${baseY.toFixed(1)}" stroke="rgba(255,255,255,0.55)" stroke-width="1" stroke-dasharray="2 2" style="display:none;" />
    ${dotsHtml}
  `;

  updateFvAudioEnvPlayhead();
}

function updateFvAudioEnvPlayhead() {
  const line = document.getElementById('fvAudioEnvPlayhead');
  const ac = activeAudioClip();
  if (!line || !ac || !isFullVideoMode() || state.selectedTrack !== 'audio') return;
  const span = getAudioClipSpan(ac);
  const localT = state.currentTime - ac.timelineStart;
  const kfBtn = document.getElementById('btnAudioKfToggle');
  if (localT >= 0 && localT <= span) {
    const x = audioEnvTimeToX(localT, span).toFixed(1);
    line.setAttribute('x1', x);
    line.setAttribute('x2', x);
    line.style.display = '';
    const onKf = findKeyframeNear(ac, localT) >= 0;
    if (kfBtn) {
      kfBtn.classList.toggle('is-on-kf', onKf);
      setLunaTooltip(kfBtn, onKf ? 'Remove keyframe' : 'Add keyframe');
    }
    const curVol = Math.round(evalAudioVolumeAt(ac, localT));
    const volSlider = document.getElementById('fvAudioVolSlider');
    const volLabel = document.getElementById('fvAudioVolLabel');
    if (volSlider && document.activeElement !== volSlider) volSlider.value = curVol;
    if (volLabel) volLabel.textContent = `${curVol}%`;
  } else {
    line.style.display = 'none';
    if (kfBtn) {
      kfBtn.classList.remove('is-on-kf');
      setLunaTooltip(kfBtn, 'Add keyframe');
    }
  }
}

function initAudioEnvGraphEvents() {
  const box = document.getElementById('fvAudioEnvBox');
  if (!box) return;

  box.addEventListener('contextmenu', (ev) => {
    const grp = ev.target.closest('.audio-kf-group');
    if (!grp) return;
    ev.preventDefault();
    const ac = activeAudioClip();
    if (!ac) return;
    const idx = Number(grp.dataset.kfIdx);
    if (idx >= 0 && idx < (ac.keyframes || []).length) {
      pushFvHistory();
      ac.keyframes.splice(idx, 1);
      syncFvAudioInspector();
      renderTracks();
      syncMusicTimeToVideo(false);
      scheduleDraftSave();
      showToast('Removed volume keyframe');
    }
  });

  // NLE timeline behavior: clicking empty envelope area scrubs playhead (never spawns stray dots).
  // Dragging an existing keyframe dot reshapes its time & volume cleanly.
  box.addEventListener('pointerdown', (ev) => {
    if (ev.button !== 0) return;
    const clip = activeClip();
    const ac = activeAudioClip();
    if (!clip || !ac || !isFullVideoMode()) return;
    ev.preventDefault();
    const span = getAudioClipSpan(ac);
    const rect = box.getBoundingClientRect();
    const toSvg = (e) => ({
      x: ((e.clientX - rect.left) / Math.max(1, rect.width)) * AUDIO_ENV_W,
      y: ((e.clientY - rect.top) / Math.max(1, rect.height)) * AUDIO_ENV_H,
    });

    const grp = ev.target.closest('.audio-kf-group');
    if (!grp) {
      const wasPlaying = state.playing;
      isUserScrubbing = true;
      if (wasPlaying) {
        videoEl.pause();
        customAudioEl.pause();
        pauseAllFvAudioPlayers();
      }
      const scrubTo = (e) => {
        const pt = toSvg(e);
        const localT = audioEnvXToTime(pt.x, span);
        seekTo(ac.timelineStart + localT);
      };
      scrubTo(ev);
      const onUpScrub = () => {
        window.removeEventListener('pointermove', scrubTo);
        window.removeEventListener('pointerup', onUpScrub);
        window.removeEventListener('pointercancel', onUpScrub);
        isUserScrubbing = false;
        if (wasPlaying && state.playing) {
          const mapped = timelineToSource(clip, state.currentTime);
          requestVideoSeek(mapped.srcTime, true);
        }
      };
      window.addEventListener('pointermove', scrubTo);
      window.addEventListener('pointerup', onUpScrub);
      window.addEventListener('pointercancel', onUpScrub);
      return;
    }

    const idx = Number(grp.dataset.kfIdx);
    if (!Array.isArray(ac.keyframes) || !ac.keyframes[idx]) return;
    const preSnap = snapshotFvState(clip);
    const startX = ev.clientX;
    const startY = ev.clientY;
    let dragIdx = idx;
    let moved = false;
    seekTo(ac.timelineStart + ac.keyframes[dragIdx].t);

    const updatePt = (e) => {
      const targetPt = ac.keyframes?.[dragIdx];
      if (!targetPt) return;
      if (!moved && Math.hypot(e.clientX - startX, e.clientY - startY) < 2) return;
      if (!moved) {
        moved = true;
        state.fvHistory.push(preSnap);
        if (state.fvHistory.length > 40) state.fvHistory.shift();
        state.fvFuture = [];
        updateFvToolbarState();
      }
      const pt = toSvg(e);
      targetPt.t = audioEnvXToTime(pt.x, span);
      targetPt.vol = audioEnvYToVol(pt.y);
      ac.keyframes.sort((a, b) => a.t - b.t);
      dragIdx = Math.max(0, ac.keyframes.indexOf(targetPt));
      renderFvAudioEnvSvg(dragIdx);
      const readout = document.getElementById('fvAudioEnvReadout');
      if (readout) readout.textContent = `${fmtMMSS(ac.timelineStart + targetPt.t)} · ${Math.round(targetPt.vol)}%`;
      const volSlider = document.getElementById('fvAudioVolSlider');
      const volLabel = document.getElementById('fvAudioVolLabel');
      if (volSlider) volSlider.value = Math.round(targetPt.vol);
      if (volLabel) volLabel.textContent = `${Math.round(targetPt.vol)}%`;
      syncMusicTimeToVideo(false);
    };

    const onUp = () => {
      window.removeEventListener('pointermove', updatePt);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('pointercancel', onUp);
      const finalT = ac.keyframes?.[dragIdx]?.t ?? 0;
      if (moved) {
        ac.keyframes = sanitizeAudioKeyframes(ac.keyframes, span);
        seekTo(ac.timelineStart + finalT);
        syncFvAudioInspector();
        renderFvAudioTrack(clip, getTimelineScaleDur(clip));
        scheduleDraftSave();
      } else {
        syncFvAudioInspector();
      }
    };
    window.addEventListener('pointermove', updatePt);
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointercancel', onUp);
  });
}

initAudioEnvGraphEvents();

function startFvSegmentTrimDrag(ev, segIdx, edge) {
  const clip = activeClip();
  if (!clip || !isFullVideoMode()) return;
  const seg = clip.segments[segIdx];
  if (!seg) return;
  const rect = document.getElementById('videoTrackArea').getBoundingClientRect();
  const initScaleDur = getTimelineScaleDur(clip);
  const initLayout = computeTimelineLayout(clip);
  const initItem = initLayout.items[segIdx];
  const initStartX = ev.clientX;
  const origSS = seg.sourceStart;
  const origSE = seg.sourceEnd;
  const avgSpeed = (origSE - origSS) / Math.max(0.1, getSegmentEffDur(seg));
  const preSnap = snapshotFvState(clip);
  const snapTargets = [state.currentTime];
  (clip.audioClips || []).forEach((a) => {
    snapTargets.push(a.timelineStart, a.timelineStart + getAudioClipSpan(a));
  });
  let moved = false;

  const onMove = (e) => {
    const dx = e.clientX - initStartX;
    if (!moved && Math.abs(dx) < 3) return;
    if (!moved) {
      moved = true;
      setTimelineEditingIndicator(true);
      state.fvHistory.push(preSnap);
      if (state.fvHistory.length > 40) state.fvHistory.shift();
      state.fvFuture = [];
    }
    const deltaTl = (dx / Math.max(120, rect.width)) * initScaleDur;
    let deltaSrc = deltaTl * avgSpeed;
    const liveScaleDur = getTimelineScaleDur(clip);
    if (edge === 'start') {
      let nextSS = Math.max(0, Math.min(origSE - 0.35, origSS + deltaSrc));
      if (initItem && state.snapEnabled) {
        // In ripple mode the block's left stays at initItem.tlStart while its right edge moves
        const candRightTl = initItem.tlStart + (origSE - nextSS) / avgSpeed;
        const snap = findMagneticSnap(candRightTl, snapTargets, rect.width, liveScaleDur);
        if (snap.snapped) {
          const snappedSS = origSE - (snap.value - initItem.tlStart) * avgSpeed;
          if (snappedSS >= 0 && snappedSS <= origSE - 0.35) {
            nextSS = snappedSS;
            showTlSnapGuide(snap.value, liveScaleDur);
          } else {
            hideTlSnapGuide();
          }
        } else {
          hideTlSnapGuide();
        }
      } else {
        hideTlSnapGuide();
      }
      seg.sourceStart = Number(nextSS.toFixed(3));
      const newTl = sourceToTimeline(clip, segIdx, seg.sourceStart);
      seekTo(newTl, segIdx);
    } else {
      let nextSE = Math.min(clip.dur || origSE, Math.max(origSS + 0.35, origSE + deltaSrc));
      if (initItem && state.snapEnabled) {
        const edgeTl = initItem.tlStart + (nextSE - origSS) / avgSpeed;
        const snap = findMagneticSnap(edgeTl, snapTargets, rect.width, liveScaleDur);
        if (snap.snapped) {
          const snappedSE = origSS + (snap.value - initItem.tlStart) * avgSpeed;
          if (snappedSE >= origSS + 0.35 && snappedSE <= (clip.dur || origSE)) {
            nextSE = snappedSE;
            showTlSnapGuide(snap.value, liveScaleDur);
          } else {
            hideTlSnapGuide();
          }
        } else {
          hideTlSnapGuide();
        }
      } else {
        hideTlSnapGuide();
      }
      seg.sourceEnd = Number(nextSE.toFixed(3));
      const newTl = sourceToTimeline(clip, segIdx, seg.sourceEnd);
      seekTo(newTl, segIdx);
    }
    syncClipLegacyBounds(clip);
    renderRuler();
    renderTracks();
    syncFullVideoPanels();
    updateFvToolbarState();
  };
  const onUp = () => {
    window.removeEventListener('pointermove', onMove);
    window.removeEventListener('pointerup', onUp);
    window.removeEventListener('pointercancel', onUp);
    setTimelineEditingIndicator(false);
    hideTlSnapGuide();
    if (moved) {
      clampFvAudioClipsToVideo(clip);
      renderRuler();
      renderTracks();
      syncFullVideoPanels();
      scheduleDraftSave();
    }
  };
  window.addEventListener('pointermove', onMove);
  window.addEventListener('pointerup', onUp);
  window.addEventListener('pointercancel', onUp);
}

function trimClipToPlayhead(side) {
  const clip = activeClip();
  if (!clip || !isFullVideoMode()) return;
  ensureFullVideoDefaults(clip);
  const isLeft = side === 'left';

  if (state.selectedTrack === 'audio' && activeAudioClip()) {
    const ac = activeAudioClip();
    const span = getAudioClipSpan(ac);
    const localT = state.currentTime - ac.timelineStart;
    if (localT <= 0.2 || localT >= span - 0.2) {
      showToast(`Move playhead inside audio clip to trim ${isLeft ? 'left' : 'right'}`);
      return;
    }
    pushFvHistory();
    if (isLeft) {
      ac.timelineStart = Number((ac.timelineStart + localT).toFixed(3));
      ac.trimStart = Number((ac.trimStart + localT).toFixed(3));
      const newSpan = getAudioClipSpan(ac);
      ac.keyframes = sanitizeAudioKeyframes(
        (ac.keyframes || []).map((k) => ({ t: k.t - localT, vol: k.vol })).filter((k) => k.t >= -0.01 && k.t <= newSpan + 0.01),
        newSpan
      );
    } else {
      ac.trimEnd = Number((ac.trimStart + localT).toFixed(3));
      const newSpan = getAudioClipSpan(ac);
      ac.keyframes = sanitizeAudioKeyframes(
        (ac.keyframes || []).filter((k) => k.t <= newSpan + 0.01),
        newSpan
      );
    }
    const newSpan = getAudioClipSpan(ac);
    const maxFade = Number((newSpan / 2).toFixed(2));
    ac.fadeIn = Math.min(ac.fadeIn || 0, maxFade);
    ac.fadeOut = Math.min(ac.fadeOut || 0, maxFade);
    syncClipAudioElement();
    renderTracks();
    syncFvAudioInspector();
    updateFvToolbarState();
    scheduleDraftSave();
    showToast(isLeft ? 'Trimmed audio left of playhead' : 'Trimmed audio right of playhead');
    return;
  }

  const mapped = timelineToSource(clip, state.currentTime);
  const seg = mapped.seg;
  const srcT = mapped.srcTime;
  if (!seg || srcT <= seg.sourceStart + 0.25 || srcT >= seg.sourceEnd - 0.25) {
    showToast(`Move playhead inside a clip block to trim ${isLeft ? 'left' : 'right'}`);
    return;
  }
  pushFvHistory();
  const ratio = (srcT - seg.sourceStart) / Math.max(0.1, seg.sourceEnd - seg.sourceStart);
  const segPos = sanitizeCurvePositions(seg.curvePositions);
  if (isLeft) {
    if (seg.speedMode === 'curve') {
      seg.curvePoints = sliceCurvePoints(seg.curvePoints, ratio, 1, segPos);
      seg.curvePositions = [0.0, 0.25, 0.5, 0.75, 1.0];
      if (isSegmentCurveActive(seg)) seg.curvePreset = 'custom';
    }
    seg.sourceStart = Number(srcT.toFixed(3));
  } else {
    if (seg.speedMode === 'curve') {
      seg.curvePoints = sliceCurvePoints(seg.curvePoints, 0, ratio, segPos);
      seg.curvePositions = [0.0, 0.25, 0.5, 0.75, 1.0];
      if (isSegmentCurveActive(seg)) seg.curvePreset = 'custom';
    }
    seg.sourceEnd = Number(srcT.toFixed(3));
  }
  syncClipLegacyBounds(clip);
  clampFvAudioClipsToVideo(clip);
  state.selectedSegIdx = mapped.segIdx;
  const targetTl = sourceToTimeline(clip, mapped.segIdx, isLeft ? seg.sourceStart : seg.sourceEnd);
  seekTo(targetTl, mapped.segIdx);
  renderRuler();
  renderTracks();
  syncFullVideoPanels();
  updateFvToolbarState();
  scheduleDraftSave();
  showToast(isLeft ? 'Trimmed left of playhead' : 'Trimmed right of playhead');
}

function splitAtPlayhead() {
  const clip = activeClip();
  if (!clip || !isFullVideoMode()) return;
  ensureFullVideoDefaults(clip);
  if (state.selectedTrack === 'audio' && activeAudioClip()) {
    splitAudioClipAtPlayhead();
    return;
  }
  const mapped = timelineToSource(clip, state.currentTime);
  const seg = mapped.seg;
  const srcT = mapped.srcTime;
  if (!seg || srcT <= seg.sourceStart + 0.25 || srcT >= seg.sourceEnd - 0.25) {
    showToast('Move playhead inside a clip block to split');
    return;
  }
  pushFvHistory();
  const splitRatio = (srcT - seg.sourceStart) / Math.max(0.1, seg.sourceEnd - seg.sourceStart);
  const segPos = sanitizeCurvePositions(seg.curvePositions);
  const leftSeg = {
    ...seg,
    sourceEnd: Number(srcT.toFixed(3)),
    curvePoints: seg.speedMode === 'curve'
      ? sliceCurvePoints(seg.curvePoints, 0, splitRatio, segPos)
      : [...seg.curvePoints],
    curvePositions: [0.0, 0.25, 0.5, 0.75, 1.0],
  };
  const rightSeg = {
    ...seg,
    id: `seg_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 5)}`,
    sourceStart: Number(srcT.toFixed(3)),
    curvePoints: seg.speedMode === 'curve'
      ? sliceCurvePoints(seg.curvePoints, splitRatio, 1, segPos)
      : [...seg.curvePoints],
    curvePositions: [0.0, 0.25, 0.5, 0.75, 1.0],
  };
  if (seg.speedMode === 'curve' && isSegmentCurveActive(seg)) {
    leftSeg.curvePreset = 'custom';
    rightSeg.curvePreset = 'custom';
  }
  clip.segments.splice(mapped.segIdx, 1, leftSeg, rightSeg);
  syncClipLegacyBounds(clip);
  state.selectedSegIdx = mapped.segIdx + 1;
  state.playingSegIdx = mapped.segIdx + 1;
  renderRuler();
  renderTracks();
  syncFullVideoPanels();
  updateFvToolbarState();
  updatePlayhead();
  scheduleDraftSave();
  showToast(`Split into ${clip.segments.length} blocks`);
}

function deleteSelectedSegment() {
  const clip = activeClip();
  if (!clip || !isFullVideoMode()) return;
  ensureFullVideoDefaults(clip);
  if (state.selectedTrack === 'audio' && activeAudioClip()) {
    deleteSelectedAudioClip();
    return;
  }
  if (clip.segments.length <= 1) {
    showToast('Keep at least one clip block on the timeline');
    return;
  }
  const layoutBefore = computeTimelineLayout(clip);
  const delIdx = Math.max(0, Math.min(clip.segments.length - 1, state.selectedSegIdx));
  const targetTl = layoutBefore.items[delIdx]?.tlStart || 0;
  pushFvHistory();
  clip.segments.splice(delIdx, 1);
  syncClipLegacyBounds(clip);
  clampFvAudioClipsToVideo(clip);
  state.selectedSegIdx = Math.min(delIdx, clip.segments.length - 1);
  const layoutAfter = computeTimelineLayout(clip);
  seekTo(Math.min(targetTl, Math.max(0, layoutAfter.totalDur - 0.01)), state.selectedSegIdx);
  renderRuler();
  renderTracks();
  syncFullVideoPanels();
  updateFvToolbarState();
  scheduleDraftSave();
  showToast('Deleted selected block');
}

function syncFvBarTrack(inputEl, val) {
  if (!inputEl) return;
  inputEl.value = val;
  const track = inputEl.closest('.fv-bar-track');
  if (!track) return;
  const min = Number(inputEl.min ?? 0);
  const max = Number(inputEl.max ?? 100);
  const pct = max > min ? Math.max(0, Math.min(100, ((Number(val) - min) / (max - min)) * 100)) : 0;
  track.style.setProperty('--pct', `${pct.toFixed(2)}%`);
}

function setFvSegVolume(val) {
  const seg = activeSegment();
  if (!seg || !isFullVideoMode()) return;
  const nextVol = Math.max(0, Math.min(100, Math.round(Number(val) || 0)));
  if (!activeSliderUndoEl && seg.volume !== nextVol) pushFvHistory();
  seg.volume = nextVol;
  syncFvBarTrack(document.getElementById('fvSegVolSlider'), seg.volume);
  const lbl = document.getElementById('fvSegVolLabel');
  if (lbl) lbl.textContent = `${seg.volume}%`;
  applyLiveSegmentVolume();
  updateFvExportInfo();
  scheduleDraftSave();
}

function applyLiveSegmentVolume() {
  const clip = activeClip();
  if (!clip || !isFullVideoMode()) return;
  if (state.muted || clip.origMuted) {
    videoEl.volume = 0;
    return;
  }
  const seg = clip.segments[state.playingSegIdx] || activeSegment();
  videoEl.volume = Math.max(0, Math.min(1, (seg?.volume ?? 100) / 100));
}

function getActiveSpeedAtPlayhead(clip) {
  if (!clip || !isFullVideoMode()) return 1.0;
  const mapped = timelineToSource(clip, state.currentTime);
  const seg = mapped.seg;
  if (!seg) return 1.0;
  if (seg.speedMode === 'curve') {
    return sampleCurveSpeed(seg.curvePoints, mapped.localRatio, seg.curvePositions);
  }
  return Math.max(0.25, Math.min(4.0, Number(seg.speed) || 1.0));
}

function applyLivePlaybackSpeed(force = false) {
  const clip = activeClip();
  const badge = document.getElementById('stageSpeedBadge');
  if (!clip || !isFullVideoMode()) {
    if (videoEl.playbackRate !== 1.0) videoEl.playbackRate = 1.0;
    badge?.classList.add('hidden');
    return;
  }
  const spd = getActiveSpeedAtPlayhead(clip);
  const now = performance.now();
  const diff = Math.abs(videoEl.playbackRate - spd);
  if ((force && diff > 0.01) || (diff >= 0.04 && now - lastPlaybackRateAppliedAt >= 90)) {
    videoEl.playbackRate = spd;
    lastPlaybackRateAppliedAt = now;
  }
  if (badge) {
    const active = Math.abs(spd - 1.0) >= 0.02;
    badge.classList.toggle('hidden', !active);
    if (active) badge.textContent = fmtSpeed(spd);
  }
}

function applyLiveFadeOpacity() {
  if (videoEl.style.opacity !== '1') {
    videoEl.style.opacity = '1';
  }
}

// --- Speed Inspector: Normal Slider & Interactive 2D 5-Point SVG Curve ---
function speedToCurveY(spd) {
  const logV = Math.log2(Math.max(0.25, Math.min(4.0, Number(spd) || 1.0)));
  const t = (2 - logV) / 4;
  return CURVE_PAD_T + t * CURVE_PLOT_H;
}

function curveYToSpeed(y) {
  const t = Math.max(0, Math.min(1, (y - CURVE_PAD_T) / CURVE_PLOT_H));
  const raw = Math.pow(2, 2 - t * 4);
  if (Math.abs(raw - 1.0) <= 0.06) return 1.0;
  return Number(Math.max(0.25, Math.min(4.0, Math.round(raw * 20) / 20)).toFixed(2));
}

function curvePosToX(posRatio) {
  return CURVE_PAD_L + Math.max(0, Math.min(1, Number(posRatio) || 0)) * CURVE_PLOT_W;
}

function curveXToPos(x) {
  return Math.max(0, Math.min(1, (x - CURVE_PAD_L) / CURVE_PLOT_W));
}

function setFvSpeedMode(mode) {
  const clip = activeClip();
  const seg = activeSegment();
  if (!clip || !seg || !isFullVideoMode()) return;
  const next = mode === 'curve' ? 'curve' : 'normal';
  if (seg.speedMode !== next) {
    pushFvHistory();
    seg.speedMode = next;
    clampFvAudioClipsToVideo(clip);
    const layout = computeTimelineLayout(clip);
    if (state.currentTime > layout.totalDur) seekTo(layout.totalDur);
    renderRuler();
    renderTracks();
    applyLivePlaybackSpeed(true);
    updatePlayhead();
    updateFvExportInfo();
    updateFvToolbarState();
    scheduleDraftSave();
  }
  renderFvSpeedInspector();
}

function setFvNormalSpeed(val) {
  const clip = activeClip();
  const seg = activeSegment();
  if (!clip || !seg || !isFullVideoMode()) return;
  const nextSpd = Number(Math.max(0.25, Math.min(4.0, Math.round(Number(val) * 20) / 20)).toFixed(2));
  if (!activeSliderUndoEl && (seg.speedMode !== 'normal' || Math.abs(seg.speed - nextSpd) >= 0.005)) {
    pushFvHistory();
  }
  seg.speedMode = 'normal';
  seg.speed = nextSpd;
  clampFvAudioClipsToVideo(clip);
  const layout = computeTimelineLayout(clip);
  if (state.currentTime > layout.totalDur) seekTo(layout.totalDur);
  renderFvSpeedInspector();
  renderRuler();
  renderTracks();
  applyLivePlaybackSpeed(true);
  updatePlayhead();
  updateFvExportInfo();
  updateFvToolbarState();
  scheduleDraftSave();
}

function setFvCurvePreset(preset) {
  const clip = activeClip();
  const seg = activeSegment();
  if (!clip || !seg || !isFullVideoMode()) return;
  pushFvHistory();
  seg.speedMode = 'curve';
  seg.curvePreset = preset;
  seg.curvePositions = [0.0, 0.25, 0.5, 0.75, 1.0];
  if (FV_CURVE_PRESETS[preset]) {
    seg.curvePoints = [...FV_CURVE_PRESETS[preset]];
  } else if (preset === 'custom' && !isSegmentCurveActive(seg)) {
    seg.curvePoints = [1.0, 1.8, 0.5, 1.8, 1.0];
  }
  clampFvAudioClipsToVideo(clip);
  const layout = computeTimelineLayout(clip);
  if (state.currentTime > layout.totalDur) seekTo(layout.totalDur);
  renderFvSpeedInspector();
  renderRuler();
  renderTracks();
  applyLivePlaybackSpeed(true);
  updatePlayhead();
  updateFvExportInfo();
  updateFvToolbarState();
  scheduleDraftSave();
}

function resetFvCurve() {
  setFvCurvePreset('none');
  showToast('Speed curve reset to 1x');
}

function renderFvSpeedInspector() {
  const seg = activeSegment();
  if (!seg || !isFullVideoMode()) return;
  const isCurve = seg.speedMode === 'curve';
  document.querySelectorAll('.fv-speed-mode-btn').forEach((b) => {
    b.classList.toggle('is-active', b.dataset.speedMode === seg.speedMode);
  });
  document.getElementById('fvSpeedNormalWrap')?.classList.toggle('hidden', isCurve);
  document.getElementById('fvSpeedCurveWrap')?.classList.toggle('hidden', !isCurve);

  const slider = document.getElementById('fvNormalSpeedSlider');
  const lbl = document.getElementById('fvNormalSpeedLabel');
  const durLbl = document.getElementById('fvSpeedDurLabel');
  if (slider) slider.value = seg.speed;
  if (lbl) lbl.textContent = fmtSpeed(seg.speed);
  if (durLbl) {
    const rawSpan = seg.sourceEnd - seg.sourceStart;
    const effSpan = getSegmentEffDur(seg);
    durLbl.textContent = Math.abs(effSpan - rawSpan) >= 0.2
      ? `${fmtMMSS(rawSpan)} → ${fmtMMSS(effSpan)}`
      : fmtMMSS(effSpan);
  }
  document.querySelectorAll('.fv-speed-quick').forEach((c) => {
    c.classList.toggle('is-active', Math.abs(Number(c.dataset.spd) - seg.speed) < 0.02);
  });

  document.querySelectorAll('.curve-preset-card').forEach((card) => {
    card.classList.toggle('is-active', card.dataset.curve === seg.curvePreset);
  });
  if (isCurve) renderFvCurveEditor();
}

function buildCurvePath(coords) {
  let d = `M ${coords[0].x.toFixed(1)} ${coords[0].y.toFixed(1)}`;
  for (let i = 0; i < coords.length - 1; i++) {
    const p0 = coords[i];
    const p1 = coords[i + 1];
    const dx = (p1.x - p0.x) * 0.44;
    d += ` C ${(p0.x + dx).toFixed(1)} ${p0.y.toFixed(1)}, ${(p1.x - dx).toFixed(1)} ${p1.y.toFixed(1)}, ${p1.x.toFixed(1)} ${p1.y.toFixed(1)}`;
  }
  return d;
}

function renderFvCurveEditor(activeDotIdx = -1) {
  const svg = document.getElementById('fvCurveSvg');
  const clip = activeClip();
  const seg = activeSegment();
  if (!svg || !clip || !seg || !isFullVideoMode()) return;

  const pts = sanitizeCurvePoints(seg.curvePoints);
  const pos = sanitizeCurvePositions(seg.curvePositions);
  const midY = speedToCurveY(1.0);
  const coords = pts.map((spd, i) => ({
    x: curvePosToX(pos[i]),
    y: speedToCurveY(spd),
    spd,
    pos: pos[i],
  }));

  const curveD = buildCurvePath(coords);
  const fillD = `${curveD} L ${coords[4].x.toFixed(1)} ${midY.toFixed(1)} L ${coords[0].x.toFixed(1)} ${midY.toFixed(1)} Z`;

  const y4 = speedToCurveY(4.0);
  const y025 = speedToCurveY(0.25);
  const axisY = CURVE_SVG_H - CURVE_PAD_B + 5;
  const labelY = CURVE_SVG_H - 5;
  const segSpan = Math.max(0.1, seg.sourceEnd - seg.sourceStart);
  const tStart = fmtMMSS(seg.sourceStart);
  const tMid = fmtMMSS(seg.sourceStart + segSpan * 0.5);
  const tEnd = fmtMMSS(seg.sourceEnd);

  const activeGuide = activeDotIdx >= 0 && activeDotIdx < 5
    ? `<line x1="${coords[activeDotIdx].x.toFixed(1)}" y1="${CURVE_PAD_T - 2}" x2="${coords[activeDotIdx].x.toFixed(1)}" y2="${axisY.toFixed(1)}" stroke="rgba(255,255,255,0.28)" stroke-width="1" stroke-dasharray="2 2" />`
    : '';

  const dotsHtml = coords
    .map((pt, i) => `
      <g class="curve-dot-group ${activeDotIdx === i ? 'is-dragging' : ''}" data-dot-idx="${i}">
        <circle cx="${pt.x.toFixed(1)}" cy="${pt.y.toFixed(1)}" r="12" fill="transparent" />
        <circle class="curve-dot" cx="${pt.x.toFixed(1)}" cy="${pt.y.toFixed(1)}" r="4.5" />
      </g>
    `)
    .join('');

  svg.innerHTML = `
    <line x1="${CURVE_PAD_L}" y1="${y4.toFixed(1)}" x2="${CURVE_SVG_W - CURVE_PAD_R}" y2="${y4.toFixed(1)}" stroke="rgba(255,255,255,0.06)" stroke-width="1" />
    <line x1="${CURVE_PAD_L}" y1="${midY.toFixed(1)}" x2="${CURVE_SVG_W - CURVE_PAD_R}" y2="${midY.toFixed(1)}" stroke="rgba(255,255,255,0.22)" stroke-width="1" stroke-dasharray="3 3" />
    <line x1="${CURVE_PAD_L}" y1="${y025.toFixed(1)}" x2="${CURVE_SVG_W - CURVE_PAD_R}" y2="${y025.toFixed(1)}" stroke="rgba(255,255,255,0.06)" stroke-width="1" />
    <line x1="${CURVE_PAD_L}" y1="${axisY.toFixed(1)}" x2="${CURVE_SVG_W - CURVE_PAD_R}" y2="${axisY.toFixed(1)}" stroke="rgba(255,255,255,0.08)" stroke-width="1" />
    <text x="5" y="${(y4 + 3).toFixed(1)}" fill="#737373" font-size="8.5" font-family="Inter,sans-serif">4x</text>
    <text x="5" y="${(midY + 3).toFixed(1)}" fill="#a3a3a3" font-size="8.5" font-family="Inter,sans-serif">1x</text>
    <text x="2" y="${(y025 + 3).toFixed(1)}" fill="#737373" font-size="8" font-family="Inter,sans-serif">0.25</text>
    <text x="${CURVE_PAD_L}" y="${labelY}" text-anchor="start" fill="#737373" font-size="8" font-family="Inter,sans-serif">${tStart}</text>
    <text x="${(CURVE_PAD_L + CURVE_PLOT_W / 2).toFixed(1)}" y="${labelY}" text-anchor="middle" fill="#737373" font-size="8" font-family="Inter,sans-serif">${tMid}</text>
    <text x="${CURVE_SVG_W - CURVE_PAD_R}" y="${labelY}" text-anchor="end" fill="#737373" font-size="8" font-family="Inter,sans-serif">${tEnd}</text>
    ${activeGuide}
    <path d="${fillD}" fill="rgba(255,255,255,0.08)" />
    <path d="${curveD}" fill="none" stroke="#ffffff" stroke-width="2" stroke-linecap="round" />
    <line id="fvCurvePlayhead" x1="${CURVE_PAD_L}" y1="${CURVE_PAD_T - 4}" x2="${CURVE_PAD_L}" y2="${axisY.toFixed(1)}" stroke="rgba(255,255,255,0.5)" stroke-width="1" stroke-dasharray="2 2" style="display:none;" />
    ${dotsHtml}
  `;

  const readout = document.getElementById('fvCurveReadout');
  if (readout) {
    if (activeDotIdx >= 0 && activeDotIdx < 5) {
      const dotTime = seg.sourceStart + pos[activeDotIdx] * segSpan;
      readout.textContent = `${fmtMMSS(dotTime)} · ${fmtSpeed(pts[activeDotIdx])}`;
    } else if (isSegmentCurveActive(seg)) {
      const label = seg.curvePreset === 'fast_in'
        ? 'Fast In'
        : seg.curvePreset.charAt(0).toUpperCase() + seg.curvePreset.slice(1);
      readout.textContent = `${label} · ${fmtMMSS(getSegmentEffDur(seg))}`;
    } else {
      readout.textContent = `Normal · ${tStart}–${tEnd}`;
    }
  }

  svg.querySelectorAll('.curve-dot-group').forEach((g) => {
    const idx = Number(g.dataset.dotIdx);
    g.addEventListener('pointerdown', (ev) => {
      ev.stopPropagation();
      ev.preventDefault();
      startCurveDotDrag(ev, idx);
    });
    g.addEventListener('dblclick', (ev) => {
      ev.stopPropagation();
      pushFvHistory();
      seg.curvePoints[idx] = 1.0;
      const curPos = sanitizeCurvePositions(seg.curvePositions);
      if (idx === 0) curPos[0] = 0.0;
      else if (idx === 4) curPos[4] = 1.0;
      else curPos[idx] = Number(Math.max(curPos[idx - 1] + 0.04, Math.min(curPos[idx + 1] - 0.04, idx / 4)).toFixed(4));
      seg.curvePositions = sanitizeCurvePositions(curPos);
      seg.curvePreset = isSegmentCurveActive(seg) ? 'custom' : 'none';
      clampFvAudioClipsToVideo(clip);
      renderFvSpeedInspector();
      renderRuler();
      renderTracks();
      applyLivePlaybackSpeed(true);
      updatePlayhead();
      updateFvExportInfo();
      updateFvToolbarState();
      scheduleDraftSave();
    });
  });

  updateCurvePlayhead();
}

function updateCurvePlayhead() {
  const line = document.getElementById('fvCurvePlayhead');
  const clip = activeClip();
  if (!line || !clip || !isFullVideoMode()) return;
  const mapped = timelineToSource(clip, state.currentTime, state.selectedSegIdx);
  if (mapped.segIdx !== state.selectedSegIdx) {
    line.style.display = 'none';
    return;
  }
  const x = CURVE_PAD_L + mapped.localRatio * CURVE_PLOT_W;
  line.setAttribute('x1', x.toFixed(1));
  line.setAttribute('x2', x.toFixed(1));
  line.style.display = 'block';
}

function startCurveDotDrag(ev, dotIdx) {
  const clip = activeClip();
  const seg = activeSegment();
  const svg = document.getElementById('fvCurveSvg');
  if (!clip || !seg || !svg) return;
  seg.curvePositions = sanitizeCurvePositions(seg.curvePositions);
  const preSnap = snapshotFvState(clip);
  const startX = ev.clientX;
  const startY = ev.clientY;
  let moved = false;

  const updateFromEvent = (e) => {
    if (!moved && Math.hypot(e.clientX - startX, e.clientY - startY) < 3) return;
    const rect = svg.getBoundingClientRect();
    const svgX = ((e.clientX - rect.left) / Math.max(1, rect.width)) * CURVE_SVG_W;
    const svgY = ((e.clientY - rect.top) / Math.max(1, rect.height)) * CURVE_SVG_H;
    const newSpd = curveYToSpeed(svgY);
    if (!moved) {
      moved = true;
      state.fvHistory.push(preSnap);
      if (state.fvHistory.length > 40) state.fvHistory.shift();
      state.fvFuture = [];
    }
    seg.speedMode = 'curve';
    seg.curvePoints[dotIdx] = newSpd;
    if (dotIdx > 0 && dotIdx < 4) {
      const lo = seg.curvePositions[dotIdx - 1] + 0.04;
      const hi = seg.curvePositions[dotIdx + 1] - 0.04;
      seg.curvePositions[dotIdx] = Number(Math.max(lo, Math.min(hi, curveXToPos(svgX))).toFixed(4));
    }
    const posShifted = seg.curvePositions.some((p, i) => Math.abs(p - i / 4) >= 0.01);
    seg.curvePreset = (isSegmentCurveActive(seg) || posShifted) ? 'custom' : 'none';
    document.querySelectorAll('.curve-preset-card').forEach((card) => {
      card.classList.toggle('is-active', card.dataset.curve === seg.curvePreset);
    });
    renderFvCurveEditor(dotIdx);
    renderRuler();
    renderTracks();
    applyLivePlaybackSpeed(true);
    updatePlayhead();
    updateFvToolbarState();
  };

  const onUp = () => {
    window.removeEventListener('pointermove', updateFromEvent);
    window.removeEventListener('pointerup', onUp);
    window.removeEventListener('pointercancel', onUp);
    if (moved) {
      clampFvAudioClipsToVideo(clip);
      renderFvCurveEditor(-1);
      renderTracks();
      updateFvExportInfo();
      scheduleDraftSave();
    }
  };
  window.addEventListener('pointermove', updateFromEvent);
  window.addEventListener('pointerup', onUp);
  window.addEventListener('pointercancel', onUp);
}

function setFvCropRatio(ratio) {
  const clip = activeClip();
  if (!clip || !isFullVideoMode()) return;
  pushFvHistory();
  clip.cropRatio = ratio || 'original';
  document.querySelectorAll('.fv-crop-chip').forEach((c) => c.classList.toggle('is-active', c.dataset.crop === clip.cropRatio));
  applyStageAspectAndFilters();
  syncFvCropFocusUi();
  updateFvExportInfo();
  scheduleDraftSave();
}

const FV_CROP_RATIO_MAP = {
  '16:9': [16, 9],
  '9:16': [9, 16],
  '1:1': [1, 1],
  '3:4': [3, 4],
};

function getFvCropOverflowAxis(clip) {
  if (!clip || !isFullVideoMode()) return 'none';
  const chosen = FV_CROP_RATIO_MAP[clip.cropRatio];
  if (!chosen) return 'none';
  const nativeW = videoEl.videoWidth || 16;
  const nativeH = videoEl.videoHeight || 9;
  if (nativeW <= 0 || nativeH <= 0) return 'none';
  const nativeRatio = nativeW / nativeH;
  const targetRatio = chosen[0] / chosen[1];
  if (Math.abs(nativeRatio - targetRatio) < 0.015) return 'none';
  return nativeRatio > targetRatio ? 'x' : 'y';
}

function applyLiveSegmentCropPosition() {
  const clip = activeClip();
  const frameBox = document.getElementById('mediaFrameBox');
  const ghostOverlay = document.getElementById('fvCropGhostOverlay');
  const ghostBox = document.getElementById('fvCropGhostBox');
  if (!clip || !isFullVideoMode()) {
    videoEl.style.objectPosition = '50% 50%';
    ghostOverlay?.classList.add('hidden');
    frameBox?.classList.remove('fv-crop-draggable', 'is-panning');
    return;
  }
  const axis = getFvCropOverflowAxis(clip);
  const seg = clip.segments[state.playingSegIdx] || activeSegment();
  const cx = seg && typeof seg.cropX === 'number' ? seg.cropX : 50;
  const cy = seg && typeof seg.cropY === 'number' ? seg.cropY : 50;
  const showGhost = axis !== 'none' && !state.cropLocked;

  if (showGhost && ghostOverlay && ghostBox) {
    const nativeW = videoEl.videoWidth || 16;
    const nativeH = videoEl.videoHeight || 9;
    const nativeRatio = nativeW / nativeH;
    const chosen = FV_CROP_RATIO_MAP[clip.cropRatio];
    const targetRatio = chosen ? (chosen[0] / chosen[1]) : nativeRatio;
    videoEl.style.objectPosition = '50% 50%';
    ghostOverlay.classList.remove('hidden');
    if (axis === 'x') {
      const wFrac = Math.max(0.05, Math.min(1, targetRatio / nativeRatio));
      const leftPct = (1 - wFrac) * cx;
      ghostBox.style.width = `${(wFrac * 100).toFixed(3)}%`;
      ghostBox.style.height = '100%';
      ghostBox.style.left = `${leftPct.toFixed(3)}%`;
      ghostBox.style.top = '0%';
    } else {
      const hFrac = Math.max(0.05, Math.min(1, nativeRatio / targetRatio));
      const topPct = (1 - hFrac) * cy;
      ghostBox.style.width = '100%';
      ghostBox.style.height = `${(hFrac * 100).toFixed(3)}%`;
      ghostBox.style.left = '0%';
      ghostBox.style.top = `${topPct.toFixed(3)}%`;
    }
  } else {
    ghostOverlay?.classList.add('hidden');
    videoEl.style.objectPosition = axis === 'none' ? '50% 50%' : `${cx}% ${cy}%`;
  }

  if (frameBox) {
    frameBox.classList.toggle('fv-crop-draggable', showGhost);
    if (!showGhost) frameBox.classList.remove('is-panning');
  }
}

function syncFvCropFocusUi() {
  const wrap = document.getElementById('fvCropFocusWrap');
  const clip = activeClip();
  const seg = activeSegment();
  if (!wrap || !clip || !seg || !isFullVideoMode()) {
    wrap?.classList.add('hidden');
    return;
  }
  const axis = getFvCropOverflowAxis(clip);
  if (axis === 'none') {
    wrap.classList.add('hidden');
    applyLiveSegmentCropPosition();
    return;
  }
  wrap.classList.remove('hidden');
  const val = axis === 'x' ? seg.cropX : seg.cropY;
  const isCentered = Math.abs(val - 50) < 0.5;
  const axisLbl = document.getElementById('fvCropAxisLabel');
  const posLbl = document.getElementById('fvCropPosLabel');
  const slider = document.getElementById('fvCropPosSlider');
  const tabCenter = document.getElementById('tabFvCropCenter');
  const tabLock = document.getElementById('tabFvCropLockToggle');
  const hintEl = document.getElementById('fvCropLockHint');

  if (axisLbl) axisLbl.textContent = axis === 'x' ? 'Focus X' : 'Focus Y';
  if (posLbl) posLbl.textContent = `${Math.round(val)}%`;
  if (slider) {
    slider.value = Math.round(val);
    slider.disabled = state.cropLocked;
    slider.classList.toggle('opacity-40', state.cropLocked);
  }
  if (tabCenter) {
    tabCenter.classList.toggle('is-active', !state.cropLocked && isCentered);
  }
  if (tabLock) {
    tabLock.classList.toggle('is-active', state.cropLocked || !isCentered);
    tabLock.innerHTML = `<i data-lucide="${state.cropLocked ? 'lock' : 'lock-open'}" class="w-3 h-3"></i><span>${state.cropLocked ? 'Locked' : 'Unlocked'}</span>`;
    if (window.lucide) lucide.createIcons({ root: tabLock });
  }
  if (hintEl) {
    hintEl.textContent = state.cropLocked
      ? 'Cropped output locked. Click Locked to unlock.'
      : 'Drag the bright crop box over the preview to reframe.';
  }
  applyLiveSegmentCropPosition();
}

function setFvCropLocked(locked) {
  if (!isFullVideoMode()) return;
  state.cropLocked = Boolean(locked);
  applyStageAspectAndFilters();
  syncFvCropFocusUi();
}

function toggleFvCropLock() {
  setFvCropLocked(!state.cropLocked);
}

function setFvSegCropPos(val) {
  const clip = activeClip();
  const seg = activeSegment();
  if (!clip || !seg || !isFullVideoMode() || state.cropLocked) return;
  const axis = getFvCropOverflowAxis(clip);
  if (axis === 'none') return;
  if (!state.playing && state.playingSegIdx !== state.selectedSegIdx) {
    const layout = computeTimelineLayout(clip);
    const targetItem = layout.items[state.selectedSegIdx];
    if (targetItem) seekTo(targetItem.tlStart, state.selectedSegIdx);
  }
  const clamped = Number(Math.max(0, Math.min(100, Number(val) || 0)).toFixed(1));
  if (axis === 'x') seg.cropX = clamped;
  else seg.cropY = clamped;
  const posLbl = document.getElementById('fvCropPosLabel');
  if (posLbl) posLbl.textContent = `${Math.round(clamped)}%`;
  const isCentered = Math.abs(clamped - 50) < 0.5;
  document.getElementById('tabFvCropCenter')?.classList.toggle('is-active', isCentered);
  document.getElementById('tabFvCropLockToggle')?.classList.toggle('is-active', !isCentered);
  applyLiveSegmentCropPosition();
  scheduleDraftSave();
}

function resetFvSegCropPos() {
  const clip = activeClip();
  const seg = activeSegment();
  if (!clip || !seg || !isFullVideoMode()) return;
  pushFvHistory();
  state.cropLocked = false;
  seg.cropX = 50;
  seg.cropY = 50;
  applyStageAspectAndFilters();
  syncFvCropFocusUi();
  scheduleDraftSave();
  showToast('Frame focus centered');
}

let suppressNextStageClick = false;

function onStageFrameClick(ev) {
  if (suppressNextStageClick) {
    suppressNextStageClick = false;
    return;
  }
  if (ev.target.closest('#subtitleOverlay')) return;
  togglePlay();
}

// Drag-to-reframe bright crop box directly over the dimmed full original preview when Unlocked
document.getElementById('mediaFrameBox')?.addEventListener('pointerdown', (ev) => {
  if (!isFullVideoMode() || state.cropLocked) return;
  if (ev.button !== 0) return;
  const clip = activeClip();
  if (!clip) return;
  ensureFullVideoDefaults(clip);
  const targetSegIdx = (state.playingSegIdx >= 0 && state.playingSegIdx < clip.segments.length)
    ? state.playingSegIdx
    : state.selectedSegIdx;
  const seg = clip.segments[targetSegIdx] || activeSegment();
  if (!seg) return;
  const axis = getFvCropOverflowAxis(clip);
  if (axis === 'none') return;
  if (state.selectedSegIdx !== targetSegIdx) {
    state.selectedSegIdx = targetSegIdx;
    syncFvCropFocusUi();
  }

  ev.preventDefault();
  const frameBox = document.getElementById('mediaFrameBox');
  const rect = frameBox.getBoundingClientRect();
  const nativeW = videoEl.videoWidth || 16;
  const nativeH = videoEl.videoHeight || 9;
  const nativeRatio = nativeW / nativeH;
  const chosen = FV_CROP_RATIO_MAP[clip.cropRatio];
  const targetRatio = chosen ? (chosen[0] / chosen[1]) : nativeRatio;
  const travelPx = axis === 'x'
    ? Math.max(24, rect.width * Math.max(0.05, 1 - targetRatio / nativeRatio))
    : Math.max(24, rect.height * Math.max(0.05, 1 - nativeRatio / targetRatio));

  const startX = ev.clientX;
  const startY = ev.clientY;
  const origVal = axis === 'x' ? seg.cropX : seg.cropY;
  const preSnap = snapshotFvState(clip);
  const guide = document.getElementById(axis === 'x' ? 'snapGuideV' : 'snapGuideH');
  let dragged = false;

  const onMove = (e) => {
    const delta = axis === 'x' ? (e.clientX - startX) : (e.clientY - startY);
    if (!dragged && Math.abs(delta) < 4) return;
    if (!dragged) {
      dragged = true;
      frameBox.classList.add('is-panning');
      state.fvHistory.push(preSnap);
      if (state.fvHistory.length > 40) state.fvHistory.shift();
      state.fvFuture = [];
      updateFvToolbarState();
    }
    const raw = Math.max(0, Math.min(100, origVal + (delta / travelPx) * 100));
    const snapped = Math.abs(raw - 50) <= 3.0;
    const nextVal = snapped ? 50 : Number(raw.toFixed(1));
    if (axis === 'x') seg.cropX = nextVal;
    else seg.cropY = nextVal;
    guide?.classList.toggle('is-visible', snapped);
    const slider = document.getElementById('fvCropPosSlider');
    const posLbl = document.getElementById('fvCropPosLabel');
    if (slider) slider.value = Math.round(nextVal);
    if (posLbl) posLbl.textContent = `${Math.round(nextVal)}%`;
    const isCen = Math.abs(nextVal - 50) < 0.5;
    document.getElementById('tabFvCropCenter')?.classList.toggle('is-active', isCen);
    document.getElementById('tabFvCropLockToggle')?.classList.toggle('is-active', !isCen);
    applyLiveSegmentCropPosition();
  };

  const onUp = () => {
    window.removeEventListener('pointermove', onMove);
    window.removeEventListener('pointerup', onUp);
    window.removeEventListener('pointercancel', onUp);
    frameBox.classList.remove('is-panning');
    guide?.classList.remove('is-visible');
    if (dragged) {
      suppressNextStageClick = true;
      setTimeout(() => { suppressNextStageClick = false; }, 120);
      scheduleDraftSave();
    }
  };
  window.addEventListener('pointermove', onMove);
  window.addEventListener('pointerup', onUp);
  window.addEventListener('pointercancel', onUp);
});

function setFvColorPreset(preset) {
  const clip = activeClip();
  if (!clip || !isFullVideoMode()) return;
  pushFvHistory();
  const p = FV_COLOR_PRESETS[preset] || FV_COLOR_PRESETS.natural;
  clip.color = {
    preset,
    brightness: p.brightness,
    exposure: p.exposure,
    contrast: p.contrast,
    saturation: p.saturation,
    warmth: p.warmth,
    sharpness: p.sharpness,
    vignette: p.vignette,
  };
  syncFvColorUi(clip);
  applyStageAspectAndFilters();
  updateFvExportInfo();
  scheduleDraftSave();
}

function setFvColorSlider(key, val) {
  const clip = activeClip();
  if (!clip || !isFullVideoMode()) return;
  ensureFullVideoDefaults(clip);
  const isPositiveOnly = key === 'sharpness' || key === 'vignette';
  const nextVal = Math.max(isPositiveOnly ? 0 : -50, Math.min(50, Math.round(Number(val) || 0)));
  if (!activeSliderUndoEl && clip.color[key] !== nextVal) pushFvHistory();
  clip.color[key] = nextVal;
  if (clip.color.preset !== 'bw' || key === 'saturation' || key === 'warmth') {
    const col = clip.color;
    const allZero = !col.brightness && !col.exposure && !col.contrast
      && !col.saturation && !col.warmth && !col.sharpness && !col.vignette;
    col.preset = allZero ? 'natural' : 'custom';
  }
  syncFvColorUi(clip);
  applyStageAspectAndFilters();
  updateFvExportInfo();
  scheduleDraftSave();
}

function resetFvColor() {
  setFvColorPreset('natural');
  showToast('Color reset to Natural');
}

function syncFvColorUi(clip) {
  const col = clip?.color || FV_COLOR_PRESETS.natural;
  document.querySelectorAll('.fv-color-chip').forEach((c) => c.classList.toggle('is-active', c.dataset.color === col.preset));
  const pairs = [
    ['fvBrightSlider', 'fvBrightLabel', col.brightness || 0],
    ['fvExposureSlider', 'fvExposureLabel', col.exposure || 0],
    ['fvContrastSlider', 'fvContrastLabel', col.contrast || 0],
    ['fvSatSlider', 'fvSatLabel', col.saturation || 0],
    ['fvWarmthSlider', 'fvWarmthLabel', col.warmth || 0],
    ['fvSharpSlider', 'fvSharpLabel', col.sharpness || 0],
    ['fvVignetteSlider', 'fvVignetteLabel', col.vignette || 0],
  ];
  pairs.forEach(([sId, lId, val]) => {
    const sEl = document.getElementById(sId);
    const lEl = document.getElementById(lId);
    syncFvBarTrack(sEl, val);
    if (lEl) lEl.textContent = val > 0 ? `+${val}` : String(val);
  });
}

document.addEventListener('pointerdown', (e) => {
  const inp = e.target?.closest?.('.fv-bar-input');
  const track = inp?.closest?.('.fv-bar-track');
  if (!track) return;
  track.classList.add('is-dragging');
  const clear = () => {
    track.classList.remove('is-dragging');
    window.removeEventListener('pointerup', clear);
    window.removeEventListener('pointercancel', clear);
  };
  window.addEventListener('pointerup', clear);
  window.addEventListener('pointercancel', clear);
});

function applyStageAspectAndFilters() {
  const clip = activeClip();
  const frameBox = document.getElementById('mediaFrameBox');
  const stage = document.getElementById('stageSection');
  const vigEl = document.getElementById('stageVignetteOverlay');
  if (!clip || !frameBox) return;

  const nativeW = videoEl.videoWidth || 16;
  const nativeH = videoEl.videoHeight || 9;
  const axis = isFullVideoMode() ? getFvCropOverflowAxis(clip) : 'none';
  const showGhost = isFullVideoMode() && axis !== 'none' && !state.cropLocked;
  const chosen = (isFullVideoMode() && !showGhost) ? FV_CROP_RATIO_MAP[clip.cropRatio] : null;
  const rw = chosen ? chosen[0] : nativeW;
  const rh = chosen ? chosen[1] : nativeH;
  frameBox.style.aspectRatio = `${rw} / ${rh}`;

  const stageRect = stage ? stage.getBoundingClientRect() : { width: 16, height: 9 };
  const stageRatio = stageRect.height > 0 ? stageRect.width / stageRect.height : 1.77;
  const boxRatio = rw / rh;
  const fitWidth = boxRatio > stageRatio;
  frameBox.classList.toggle('w-full', fitWidth);
  frameBox.classList.toggle('h-full', !fitWidth);

  if (isFullVideoMode()) {
    const col = clip.color || FV_COLOR_PRESETS.natural;
    const b = col.brightness || 0;
    const ex = col.exposure || 0;
    const ct = col.contrast || 0;
    const sa = col.saturation || 0;
    const wm = col.warmth || 0;
    const sh = col.sharpness || 0;
    const vg = col.vignette || 0;
    const isDefaultColor = (col.preset === 'natural' || col.preset === 'custom')
      && !b && !ex && !ct && !sa && !wm && !sh && !vg;

    if (isDefaultColor) {
      // Keep videoEl.style.filter empty when default so Chromium keeps hardware video overlay promotion (fixes Play flicker).
      if (videoEl.style.filter) videoEl.style.filter = '';
    } else {
      const bCss = Math.max(0.2, 1 + b / 100 + ex / 80).toFixed(3);
      const cCss = Math.max(0.2, 1 + ct / 100 + sh / 350).toFixed(3);
      const sCss = Math.max(0, 1 + sa / 50).toFixed(3);
      const parts = [`brightness(${bCss})`, `contrast(${cCss})`, `saturate(${sCss})`];
      if (col.preset === 'bw') {
        parts.push('grayscale(1)');
      } else {
        const effWarm = wm + (col.preset === 'warm' ? 17 : (col.preset === 'cinematic' ? -11 : 0));
        if (effWarm > 0) {
          parts.push(`sepia(${Math.min(0.45, effWarm / 110).toFixed(3)})`);
        } else if (effWarm < 0) {
          parts.push(`hue-rotate(${Math.max(-24, effWarm * 0.4).toFixed(1)}deg)`);
        }
      }
      videoEl.style.filter = parts.join(' ');
    }

    if (vigEl) {
      if (vg > 0) {
        vigEl.style.background = 'radial-gradient(ellipse at center, rgba(0,0,0,0) 46%, rgba(0,0,0,0.88) 100%)';
        vigEl.style.opacity = ((vg / 50) * 0.85).toFixed(3);
      } else {
        vigEl.style.opacity = '0';
      }
    }
    applyLiveSegmentCropPosition();
    applyLiveFadeOpacity();
  } else {
    videoEl.style.filter = '';
    videoEl.style.opacity = '1';
    videoEl.style.objectPosition = '50% 50%';
    document.getElementById('fvCropGhostOverlay')?.classList.add('hidden');
    if (vigEl) vigEl.style.opacity = '0';
  }
}

function getFvExportSummary(clip) {
  if (!clip) return { mode: 'Fast Lossless', hint: 'Instant stream copy (-c copy) with original quality.', outDur: 0 };
  ensureFullVideoDefaults(clip);
  const layout = computeTimelineLayout(clip);
  const outDur = layout.totalDur;
  const segs = clip.segments || [];
  const col = clip.color || {};
  const hasColor = (col.preset && col.preset !== 'natural' && col.preset !== 'custom')
    || col.brightness || col.exposure || col.contrast || col.saturation || col.warmth || col.sharpness || col.vignette;
  const hasSpeed = segs.some((s) => isSegmentSpeedActive(s));
  const multiSeg = segs.length > 1;
  const hasVolChange = segs.some((s) => Math.abs((s.volume ?? 100) - 100) >= 1);
  const hasVideoFx = (clip.cropRatio && clip.cropRatio !== 'original') || hasColor || (clip.fade > 0) || hasSpeed || multiSeg;
  const hasAudioClips = (clip.audioClips && clip.audioClips.length > 0);
  const hasAudioFx = hasAudioClips || state.muted || hasVolChange || (clip.fade > 0) || hasSpeed || multiSeg;

  if (!hasVideoFx && !hasAudioFx) {
    return { mode: 'Fast Lossless', hint: 'Instant stream copy (-c copy) with zero quality loss.', outDur };
  }
  if (!hasVideoFx && hasAudioFx) {
    return { mode: 'Fast Audio Remix', hint: 'Video stream copied untouched (-c:v copy); audio remixed.', outDur };
  }
  return { mode: 'Smart Render', hint: 'Cleanly renders multi-block cuts, speed curve, crop, or color.', outDur };
}

function updateFvExportInfo() {
  if (!isFullVideoMode()) return;
  const clip = activeClip();
  const info = getFvExportSummary(clip);
  const modeEl = document.getElementById('fvExportModeLabel');
  const durEl = document.getElementById('fvOutputDurLabel');
  const hintEl = document.getElementById('fvExportModeHint');
  if (modeEl) modeEl.textContent = info.mode;
  if (durEl) durEl.textContent = fmtMMSS(info.outDur);
  if (hintEl) hintEl.textContent = info.hint;
}

function syncFvAudioEnhanceUi(clip) {
  const ae = clip?.audioEnhance || { normalize: false, denoise: false, autoDuck: false };
  document.querySelectorAll('.fv-ae-row').forEach((btn) => {
    const key = btn.dataset.ae;
    const on = !!ae[key];
    btn.classList.toggle('is-active', on);
    btn.setAttribute('aria-checked', on ? 'true' : 'false');
  });
  const hint = document.getElementById('fvAudioEnhanceHint');
  if (hint) {
    const active = [];
    if (ae.normalize) active.push('-14 LUFS');
    if (ae.denoise) active.push('Denoise');
    if (ae.autoDuck) active.push('Auto-Duck');
    hint.textContent = active.length
      ? `${active.join(' · ')} active (fast lossless video copy).`
      : 'Applied on export with instant video copy.';
  }
}

function toggleFvAudioEnhance(key) {
  const clip = ensureFullVideoDefaults(activeClip());
  if (!clip || !['normalize', 'denoise', 'autoDuck'].includes(key)) return;
  pushFvHistory();
  clip.audioEnhance[key] = !clip.audioEnhance[key];
  syncFvAudioEnhanceUi(clip);
  scheduleDraftSave();
}

function resetFvAudioEnhance() {
  const clip = ensureFullVideoDefaults(activeClip());
  if (!clip) return;
  const ae = clip.audioEnhance || {};
  if (!ae.normalize && !ae.denoise && !ae.autoDuck) return;
  pushFvHistory();
  clip.audioEnhance = { normalize: false, denoise: false, autoDuck: false };
  syncFvAudioEnhanceUi(clip);
  scheduleDraftSave();
}

let silenceDetecting = false;
async function autoCutFvSilence() {
  const targetClip = ensureFullVideoDefaults(activeClip());
  if (!targetClip || !isFullVideoMode() || silenceDetecting || state.exporting) return;
  const targetClipId = targetClip.id;
  silenceDetecting = true;
  const btn = document.getElementById('btnFvCutSilence');
  if (btn) btn.disabled = true;
  showProgressToast('Auto Cut', null, 'Detecting silent pauses...', false);
  try {
    const res = await fetch(
      `/api/studio/${encodeURIComponent(PROJECT_ID)}/detect-silence/${encodeURIComponent(targetClipId)}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ payload: buildClipExportBody(targetClip) }),
      }
    );
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.ok) {
      throw new Error(data.detail || 'Could not detect silence');
    }
    const savedSec = Number(data.savedSec) || 0;
    const removedCount = Number(data.removedCount) || 0;
    if (!Array.isArray(data.segments) || !data.segments.length || savedSec < 0.2) {
      showToast('No long pauses detected', 2400);
      return;
    }
    const stillActive = activeClip()?.id === targetClipId;
    if (stillActive) pushFvHistory();
    targetClip.segments = data.segments;
    ensureFullVideoDefaults(targetClip);
    syncClipLegacyBounds(targetClip);
    clampFvAudioClipsToVideo(targetClip);
    if (stillActive) {
      state.selectedSegIdx = 0;
      state.selectedTrack = 'video';
      state.selectedAudioId = null;
      const layout = computeTimelineLayout(targetClip);
      state.currentTime = Math.min(state.currentTime, Math.max(0, layout.totalDur - 0.05));
      renderFvTracks(targetClip);
      renderRuler();
      applyFvRightPanelMode();
      syncFullVideoPanels();
      seekTo(state.currentTime);
      updatePlayhead();
      showToast(`Cut ${removedCount || 1} pause${removedCount === 1 ? '' : 's'} (-${savedSec.toFixed(1)}s)`, 3000);
    } else {
      showToast(`Auto Cut applied to ${targetClip.name} (-${savedSec.toFixed(1)}s)`, 3000);
    }
    scheduleDraftSave();
  } catch (err) {
    showToast(err.message || 'Silence detection failed', 3200, 'error');
  } finally {
    silenceDetecting = false;
    if (btn) btn.disabled = false;
  }
}

function syncFullVideoPanels() {
  const clip = ensureFullVideoDefaults(activeClip());
  if (!clip || !isFullVideoMode()) return;
  const seg = activeSegment();

  document.querySelectorAll('.fv-crop-chip').forEach((c) => c.classList.toggle('is-active', c.dataset.crop === clip.cropRatio));

  const volSlider = document.getElementById('fvSegVolSlider');
  const volLabel = document.getElementById('fvSegVolLabel');
  if (volSlider && seg) syncFvBarTrack(volSlider, seg.volume);
  if (volLabel && seg) volLabel.textContent = `${seg.volume}%`;

  syncFvAudioEnhanceUi(clip);
  syncFvCropFocusUi();
  syncFvColorUi(clip);
  renderFvSpeedInspector();
  if (state.selectedTrack === 'audio') syncFvAudioInspector();
  updateFvExportInfo();
  updateFvToolbarState();
}

function onHeaderDownloadClick(ev) {
  ev?.stopPropagation();
  if (!isFullVideoMode()) {
    downloadClip();
    return;
  }
  const menu = document.getElementById('exportDropdownMenu');
  if (!menu) {
    downloadClip();
    return;
  }
  menu.classList.toggle('hidden');
  if (!menu.classList.contains('hidden') && window.lucide) {
    lucide.createIcons({ root: menu });
  }
}

function closeExportMenu() {
  document.getElementById('exportDropdownMenu')?.classList.add('hidden');
}

document.addEventListener('pointerdown', (ev) => {
  if (!ev.target.closest('#exportMenuWrap')) closeExportMenu();
});

async function extractMp3() {
  const clip = activeClip();
  if (!clip || state.extractingAudio) return;
  state.extractingAudio = true;
  const dlBtn = document.getElementById('btnDownloadClip');
  const mp3Btn = document.getElementById('btnExportAudioMp3');
  if (dlBtn) dlBtn.disabled = true;
  if (mp3Btn) mp3Btn.disabled = true;
  showToast(`Exporting MP3 from ${clip.name}...`);
  try {
    await persistDraftToServer(false);
    const res = await fetch(
      `/api/studio/${encodeURIComponent(PROJECT_ID)}/extract-audio/${encodeURIComponent(clip.id)}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          start: clip.start,
          end: clip.end,
          muted: state.muted,
          fade: clip.fade,
          segments: clip.segments || [],
          music: clip.music || null,
          audioClips: isFullVideoMode() ? (clip.audioClips || []) : undefined,
        }),
      }
    );
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || 'Audio export failed');
    }
    const blob = await res.blob();
    const dlUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = dlUrl;
    const stem = (clip.filename || clip.id).replace(/\.[^.]+$/, '');
    a.download = `${stem}_audio.mp3`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(dlUrl), 10000);
    showToast(`Downloaded ${stem}_audio.mp3`);
  } catch (err) {
    showToast(err.message || 'Audio export failed');
  } finally {
    state.extractingAudio = false;
    if (dlBtn) dlBtn.disabled = false;
    if (mp3Btn) mp3Btn.disabled = false;
  }
}

// --- Save Draft (Auto-Save + Ctrl+S), Export to Workspace & Direct Download ---
function buildClipExportBody(clip) {
  return {
    start: clip.start,
    end: clip.end,
    muted: Boolean(clip.origMuted),
    subStyle: state.subStyle,
    subSize: state.subSize,
    customScale: state.customScale,
    subPos: state.subPos,
    posX: state.posX,
    posY: state.posY,
    cues: clip.cues || [],
    music: clip.music || null,
    audioClips: isFullVideoMode() ? (clip.audioClips || []) : undefined,
    cropRatio: clip.cropRatio,
    fade: clip.fade,
    color: clip.color,
    audioEnhance: clip.audioEnhance || { normalize: false, denoise: false, autoDuck: false },
    segments: clip.segments || [],
  };
}

async function saveClip() {
  const clip = activeClip();
  if (!clip) return;
  if (!isFullVideoMode()) {
    clip.caption = document.getElementById('captionBox').value;
    clip.title = document.getElementById('clipTitleInput').value;
    clip.tags = document.getElementById('clipTagsInput').value;
  }
  await persistDraftToServer(true);
}

let activeRenderJobId = null;
let renderCancelRequested = false;

function setExportControlsBusy(busy) {
  const dlBtn = document.getElementById('btnDownloadClip');
  const expBtn = document.getElementById('btnExportWorkspace');
  if (dlBtn) dlBtn.disabled = Boolean(busy);
  if (expBtn) expBtn.disabled = Boolean(busy);
}

function setToastIcon(kind) {
  const wrap = document.getElementById('editorToastIconWrap');
  if (!wrap) return;
  if (kind === 'loading') {
    wrap.innerHTML = `<svg id="editorToastIcon" class="luna-arc-spinner" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle class="luna-arc-spinner-track" cx="12" cy="12" r="9" stroke-width="2.2" />
      <circle class="luna-arc-spinner-head" cx="12" cy="12" r="9" stroke-width="2.2" />
    </svg>`;
    return;
  } else if (kind === 'error') {
    wrap.innerHTML = '<i id="editorToastIcon" data-lucide="alert-circle" class="w-4 h-4 text-red-400"></i>';
  } else {
    wrap.innerHTML = '<i id="editorToastIcon" data-lucide="check-circle-2" class="w-4 h-4 text-white"></i>';
  }
  if (window.lucide) lucide.createIcons({ root: wrap });
}

function showProgressToast(label, pct = null, stage = '', allowCancel = true) {
  const el = document.getElementById('editorToast');
  const txt = document.getElementById('editorToastText');
  const sub = document.getElementById('editorToastSub');
  const pctEl = document.getElementById('editorToastPct');
  const cancelBtn = document.getElementById('btnEditorToastCancel');
  const track = document.getElementById('editorToastProgressTrack');
  const bar = document.getElementById('editorToastProgressBar');
  if (!el) return;

  clearTimeout(toastTimer);
  if (txt) txt.textContent = label;
  if (sub) {
    const cleanStage = String(stage || '').trim();
    if (cleanStage) {
      sub.textContent = cleanStage;
      sub.classList.remove('hidden');
    } else {
      sub.classList.add('hidden');
    }
  }
  if (cancelBtn) {
    cancelBtn.classList.toggle('hidden', !allowCancel);
  }
  if (el.dataset.toastKind !== 'loading') {
    el.dataset.toastKind = 'loading';
    setToastIcon('loading');
  }
  if (track) track.classList.remove('hidden');

  const hasPct = typeof pct === 'number' && Number.isFinite(pct) && pct > 0;
  if (hasPct) {
    const clamped = Math.max(1, Math.min(100, Math.round(pct)));
    if (pctEl) {
      pctEl.textContent = `${clamped}%`;
      pctEl.classList.remove('hidden');
    }
    if (bar) {
      bar.classList.remove('is-indeterminate');
      bar.classList.add('is-determinate');
      bar.style.width = `${clamped}%`;
    }
  } else {
    if (pctEl) pctEl.classList.add('hidden');
    if (bar) {
      bar.classList.remove('is-determinate');
      bar.classList.add('is-indeterminate');
      bar.style.width = '';
    }
  }
  el.classList.add('show');
}

async function cancelStudioRenderJob() {
  if (!state.exporting) return;
  renderCancelRequested = true;
  const jid = activeRenderJobId;
  showProgressToast('Cancelling...', null, '', false);
  if (jid) {
    try {
      await fetch(`/api/studio/jobs/${encodeURIComponent(jid)}/cancel`, { method: 'POST' });
    } catch (_) {}
  }
}

let reencodeConfirmResolver = null;
let lastRenderedExportSig = null;

const FV_LOOK_LABELS = {
  natural: 'Natural',
  warm: 'Warm',
  crisp: 'Crisp',
  cinematic: 'Cinema',
  vivid: 'Vivid',
  bw: 'B&W',
  custom: 'Custom',
};

const FV_ADJUST_LABELS = [
  ['brightness', 'Brightness'],
  ['exposure', 'Exposure'],
  ['contrast', 'Contrast'],
  ['saturation', 'Saturation'],
  ['warmth', 'Warmth'],
  ['sharpness', 'Sharpness'],
  ['vignette', 'Vignette'],
];

function getClipReencodeReasons(clip) {
  if (!clip) return [];
  const reasons = [];

  if (!isFullVideoMode()) {
    const stateSub = String(state.subStyle || 'none').toLowerCase();
    const clipSub = String(clip.subStyle || 'none').toLowerCase();
    const subStyle = stateSub !== 'none' ? stateSub : clipSub;
    const hasCues = Array.isArray(clip.cues) && clip.cues.length > 0;
    if (subStyle !== 'none' && hasCues) {
      reasons.push({
        kind: 'subtitle',
        label: 'Subtitles',
        detail: 'Burned into video',
      });
    }
    return reasons;
  }

  const col = clip.color || {};
  const preset = String(col.preset || 'natural').toLowerCase();

  if (preset && preset !== 'natural' && preset !== 'custom') {
    const lbl = FV_LOOK_LABELS[preset] || preset;
    reasons.push({
      kind: 'color',
      label: `Look: ${lbl}`,
      detail: 'Color grading',
    });
  }

  const presetDef = FV_COLOR_PRESETS[preset] || FV_COLOR_PRESETS.natural;
  const changedAdjust = [];
  for (const [key, title] of FV_ADJUST_LABELS) {
    const val = Number(col[key]) || 0;
    const base = (preset && preset !== 'natural' && preset !== 'custom') ? (Number(presetDef[key]) || 0) : 0;
    if (val !== base) changedAdjust.push(title);
  }
  if (changedAdjust.length > 0) {
    const shown = changedAdjust.slice(0, 3).join(', ') + (changedAdjust.length > 3 ? ` +${changedAdjust.length - 3}` : '');
    reasons.push({
      kind: 'color',
      label: `Adjust (${shown})`,
      detail: 'Color & light',
    });
  }

  if (clip.cropRatio && clip.cropRatio !== 'original') {
    const targetPair = FV_CROP_RATIO_MAP[clip.cropRatio];
    const targetRatio = targetPair ? (targetPair[0] / targetPair[1]) : null;
    const curRatio = (videoEl && videoEl.videoWidth > 0 && videoEl.videoHeight > 0)
      ? (videoEl.videoWidth / videoEl.videoHeight)
      : null;
    const needsCrop = !targetRatio || !curRatio || Math.abs(curRatio - targetRatio) >= 0.015;
    if (needsCrop) {
      reasons.push({
        kind: 'crop',
        label: `Aspect Ratio: ${clip.cropRatio}`,
        detail: 'Frame crop',
      });
    }
  }

  const segs = Array.isArray(clip.segments) ? clip.segments : [];
  const hasCurve = segs.some(
    (s) => s.speedMode === 'curve' && Array.isArray(s.curvePoints) && s.curvePoints.some((p) => Math.abs((Number(p) || 1) - 1) >= 0.02)
  );
  const normalSpeeds = [];
  for (const s of segs) {
    if (s.speedMode === 'curve') continue;
    const sp = Number(s.speed) || 1;
    if (Math.abs(sp - 1) >= 0.01) {
      const txt = `${sp.toFixed(2).replace(/\.?0+$/, '')}x`;
      if (!normalSpeeds.includes(txt)) normalSpeeds.push(txt);
    }
  }
  if (hasCurve && normalSpeeds.length > 0) {
    reasons.push({
      kind: 'speed',
      label: `Speed Curve & ${normalSpeeds.slice(0, 2).join(', ')}`,
      detail: 'Variable speed',
    });
  } else if (hasCurve) {
    reasons.push({
      kind: 'speed',
      label: 'Speed Curve',
      detail: 'Variable speed',
    });
  } else if (normalSpeeds.length > 0) {
    reasons.push({
      kind: 'speed',
      label: `Speed: ${normalSpeeds.slice(0, 3).join(', ')}`,
      detail: 'Clip speed',
    });
  }

  const fadeVal = Number(clip.fade) || 0;
  if (fadeVal > 0) {
    reasons.push({
      kind: 'fade',
      label: `Video Fade (${fadeVal}s)`,
      detail: 'Fade transition',
    });
  }

  return reasons;
}

function buildReencodeModalDesc(reasons) {
  const kinds = new Set(reasons.map((r) => r.kind));
  if (kinds.size === 1) {
    const only = [...kinds][0];
    if (only === 'color') {
      return 'Color adjustments require re-encoding every frame, so this will take longer than instant copy. Original quality is preserved.';
    }
    if (only === 'crop') {
      return 'Cropping to a new aspect ratio requires re-encoding every frame, so this will take longer than instant copy. Original quality is preserved.';
    }
    if (only === 'speed') {
      return 'Changing clip speed requires re-timing and re-encoding the video, so this will take longer than instant copy. Original quality is preserved.';
    }
    if (only === 'fade') {
      return 'Video fade transitions require re-encoding frames, so this will take longer than instant copy. Original quality is preserved.';
    }
    if (only === 'subtitle') {
      return 'Burning subtitles into the video requires re-encoding every frame, so this will take longer than instant copy. Original quality is preserved.';
    }
  }
  return 'These edits require re-encoding every frame, so this will take longer than instant copy. Original quality is preserved.';
}

function resolveReencodeConfirm(accepted) {
  const modal = document.getElementById('reencodeConfirmModal');
  if (modal) modal.classList.add('hidden');
  const fn = reencodeConfirmResolver;
  reencodeConfirmResolver = null;
  if (typeof fn === 'function') fn(!!accepted);
}

function confirmReencodeIfNeeded(clip, mode, exportSig) {
  if (exportSig && exportSig === lastRenderedExportSig) return Promise.resolve(true);
  const reasons = getClipReencodeReasons(clip);
  if (!reasons.length) return Promise.resolve(true);

  const modal = document.getElementById('reencodeConfirmModal');
  const titleEl = document.getElementById('reencodeModalTitle');
  const descEl = document.getElementById('reencodeModalDesc');
  const listEl = document.getElementById('reencodeModalReasons');
  const contBtn = document.getElementById('btnReencodeContinue');
  if (!modal || !listEl) return Promise.resolve(true);

  const isWorkspace = mode === 'workspace';
  if (titleEl) titleEl.textContent = isWorkspace ? 'Full render required to export' : 'Full render required to download';
  if (descEl) descEl.textContent = buildReencodeModalDesc(reasons);
  if (contBtn) contBtn.textContent = 'Continue';

  listEl.innerHTML = reasons
    .map(
      (r) =>
        `<li class="flex items-center justify-between gap-3">`
        + `<span class="inline-flex items-center gap-2 min-w-0">`
        + `<span class="w-1.5 h-1.5 rounded-full bg-neutral-500 shrink-0"></span>`
        + `<span class="font-medium text-neutral-100 truncate">${escHtml(r.label)}</span>`
        + `</span>`
        + `<span class="text-[11px] text-neutral-500 shrink-0">${escHtml(r.detail)}</span>`
        + `</li>`
    )
    .join('');

  modal.classList.remove('hidden');
  if (window.lucide) lucide.createIcons({ nodes: [modal] });

  return new Promise((resolve) => {
    reencodeConfirmResolver = resolve;
  });
}

async function runStudioRenderJob(mode) {
  const initClip = ensureFullVideoDefaults(activeClip());
  if (!initClip || state.exporting || reencodeConfirmResolver) return;
  const isWorkspace = mode === 'workspace';
  const activeLabel = isWorkspace ? 'Exporting' : 'Downloading';
  const preSig = `${initClip.id}:${JSON.stringify(buildClipExportBody(initClip))}`;

  const confirmed = await confirmReencodeIfNeeded(initClip, mode, preSig);
  if (!confirmed) return;

  const clip = ensureFullVideoDefaults(activeClip());
  if (!clip || state.exporting) return;
  const exportPayload = buildClipExportBody(clip);
  const exportSig = `${clip.id}:${JSON.stringify(exportPayload)}`;

  state.exporting = true;
  clearTimeout(autoSaveTimer);
  autoSaveTimer = null;
  clearTimeout(preRenderTimer);
  preRenderTimer = null;
  activeRenderJobId = null;
  renderCancelRequested = false;
  setExportControlsBusy(true);
  showProgressToast(activeLabel, null, 'Preparing...', true);

  try {
    await persistDraftToServer(false);
    if (renderCancelRequested) {
      showToast('Cancelled', 2200);
      return;
    }
    const startRes = await fetch(
      `/api/studio/${encodeURIComponent(PROJECT_ID)}/jobs/${encodeURIComponent(clip.id)}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: isWorkspace ? 'workspace' : 'download', payload: exportPayload }),
      }
    );
    if (!startRes.ok) {
      const errData = await startRes.json().catch(() => ({}));
      if (startRes.status === 404 && String(errData.detail || '').toLowerCase() === 'not found') {
        throw new Error('Restart start.bat to load latest Studio server');
      }
      throw new Error(errData.detail || (isWorkspace ? 'Export failed' : 'Download failed'));
    }
    const started = await startRes.json();
    const jobId = started?.jobId;
    if (!jobId) throw new Error('Could not start render job');
    activeRenderJobId = jobId;

    if (renderCancelRequested) {
      await fetch(`/api/studio/jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' }).catch(() => {});
      showToast('Cancelled', 2200);
      return;
    }

    let finalJob = null;
    while (true) {
      await new Promise((r) => setTimeout(r, 260));
      if (renderCancelRequested) {
        finalJob = { status: 'cancelled' };
        break;
      }
      const pollRes = await fetch(`/api/studio/jobs/${encodeURIComponent(jobId)}`);
      if (!pollRes.ok) throw new Error('Lost connection to render job');
      const job = await pollRes.json();
      if (renderCancelRequested) {
        finalJob = { status: 'cancelled' };
        break;
      }
      if (job.status === 'running') {
        const p = Number(job.progress) || 0;
        showProgressToast(activeLabel, p > 0 ? p : null, job.stage || 'Preparing...', true);
        continue;
      }
      finalJob = job;
      break;
    }

    if (renderCancelRequested || finalJob?.status === 'cancelled') {
      showToast('Cancelled', 2200, 'success', true);
      return;
    }

    if (!finalJob || finalJob.status !== 'done') {
      throw new Error(finalJob?.error || (isWorkspace ? 'Export failed' : 'Download failed'));
    }

    lastRenderedExportSig = exportSig;
    showProgressToast(activeLabel, 100, isWorkspace ? 'Saving to workspace...' : 'Starting download...', false);
    await new Promise((r) => setTimeout(r, 160));

    if (isWorkspace) {
      if (finalJob.clip && !WORKSPACE_CLIPS.some((c) => c.id === finalJob.clip.id)) {
        WORKSPACE_CLIPS.push(ensureFullVideoDefaults(finalJob.clip));
        renderWorkspaceClips();
      }
      showToast('Exported to workspace', 2800, 'success', true);
    } else {
      if (!finalJob.downloadUrl) throw new Error('Download link unavailable');
      let frame = document.getElementById('lunaDownloadFrame');
      if (!frame) {
        frame = document.createElement('iframe');
        frame.id = 'lunaDownloadFrame';
        frame.style.display = 'none';
        document.body.appendChild(frame);
      }
      const sep = finalJob.downloadUrl.includes('?') ? '&' : '?';
      frame.src = `${finalJob.downloadUrl}${sep}_dl=${Date.now()}`;
      showToast('Download started', 2800, 'success', true);
    }
  } catch (err) {
    if (renderCancelRequested) {
      showToast('Cancelled', 2200, 'success', true);
    } else {
      showToast(err.message || (isWorkspace ? 'Export failed' : 'Download failed'), 4200, 'error', true);
    }
  } finally {
    state.exporting = false;
    activeRenderJobId = null;
    renderCancelRequested = false;
    setExportControlsBusy(false);
  }
}

async function exportToWorkspace() {
  return runStudioRenderJob('workspace');
}

async function downloadClip() {
  return runStudioRenderJob('download');
}

let toastTimer = null;
function showToast(msg, durationMs = 2600, kind = 'success', force = false) {
  if (state.exporting && !force) return;
  const el = document.getElementById('editorToast');
  const txt = document.getElementById('editorToastText');
  const sub = document.getElementById('editorToastSub');
  const pctEl = document.getElementById('editorToastPct');
  const cancelBtn = document.getElementById('btnEditorToastCancel');
  const track = document.getElementById('editorToastProgressTrack');
  if (!el) return;
  if (txt) txt.textContent = msg;
  if (sub) sub.classList.add('hidden');
  if (pctEl) pctEl.classList.add('hidden');
  if (cancelBtn) cancelBtn.classList.add('hidden');
  if (track) track.classList.add('hidden');
  if (el.dataset.toastKind !== kind) {
    el.dataset.toastKind = kind;
    setToastIcon(kind);
  }
  el.classList.add('show');
  clearTimeout(toastTimer);
  if (durationMs > 0) {
    toastTimer = setTimeout(() => el.classList.remove('show'), durationMs);
  }
}

function startScrub(ev) {
  ev.preventDefault();
  const clip = activeClip();
  if (!clip) return;
  const scaleDur = getTimelineScaleDur(clip);
  const wasPlaying = state.playing;
  isUserScrubbing = true;
  if (wasPlaying) {
    videoEl.pause();
    customAudioEl.pause();
    pauseAllFvAudioPlayers();
  }
  const update = (e) => {
    const rect = document.getElementById('videoTrackArea').getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / Math.max(1, rect.width)));
    seekTo(ratio * scaleDur);
  };
  update(ev);
  const onUp = () => {
    window.removeEventListener('pointermove', update);
    window.removeEventListener('pointerup', onUp);
    window.removeEventListener('pointercancel', onUp);
    isUserScrubbing = false;
    if (wasPlaying && state.playing) {
      const mapped = isFullVideoMode() ? timelineToSource(clip, state.currentTime) : { srcTime: state.currentTime };
      requestVideoSeek(mapped.srcTime, true);
    }
  };
  window.addEventListener('pointermove', update);
  window.addEventListener('pointerup', onUp);
  window.addEventListener('pointercancel', onUp);
}

document.getElementById('timelineRuler').addEventListener('pointerdown', startScrub);
document.getElementById('videoTrackArea').addEventListener('pointerdown', (ev) => {
  if (ev.target.closest('.seg-grab-bar')) return;
  startScrub(ev);
});
document.getElementById('audioTrackArea').addEventListener('pointerdown', (ev) => {
  if (isFullVideoMode() && !ev.target.closest('.fv-audio-block')) startScrub(ev);
});
document.getElementById('playheadDot').addEventListener('pointerdown', (ev) => {
  ev.stopPropagation();
  startScrub(ev);
});

let lastRawVideoTime = -1;
let lastRawVideoStamp = 0;

function getSmoothVideoTime(segEnd) {
  const raw = videoEl.currentTime;
  const now = performance.now();
  if (Math.abs(raw - lastRawVideoTime) > 0.0005 || videoEl.paused || videoEl.readyState < 3) {
    lastRawVideoTime = raw;
    lastRawVideoStamp = now;
    return raw;
  }
  // Interpolate smoothly at 60fps between browser decoder clock ticks (capped to +0.18s so buffering never drifts)
  const rate = Math.max(0.25, Math.min(4.0, Number(videoEl.playbackRate) || 1.0));
  const dt = Math.min(0.18, Math.max(0, (now - lastRawVideoStamp) / 1000)) * rate;
  return Math.min(segEnd, raw + dt);
}

function tick() {
  if (state.playing && !isUserScrubbing && activeClip()) {
    const clip = activeClip();
    if (isFullVideoMode()) {
      if (!videoEl.seeking && !videoSeekBusy) {
        const segs = clip.segments || [];
        const curSeg = segs[state.playingSegIdx];
        if (!curSeg) {
          stopPlaybackAtEnd();
        } else {
          const vTime = getSmoothVideoTime(curSeg.sourceEnd);
          if (videoEl.ended || videoEl.currentTime >= curSeg.sourceEnd - 0.03) {
            if (state.playingSegIdx + 1 < segs.length) {
              state.playingSegIdx += 1;
              const nextSeg = segs[state.playingSegIdx];
              const layout = computeTimelineLayout(clip);
              state.currentTime = layout.items[state.playingSegIdx].tlStart;
              const isContiguous = Math.abs(nextSeg.sourceStart - curSeg.sourceEnd) < 0.02
                && Math.abs(videoEl.currentTime - nextSeg.sourceStart) < 0.06
                && !videoEl.ended;
              applyLivePlaybackSpeed(true);
              applyLiveSegmentVolume();
              applyLiveSegmentCropPosition();
              updateCurvePlayhead();
              updateFvAudioEnvPlayhead();
              updatePlayhead();
              if (!isContiguous) {
                requestVideoSeek(nextSeg.sourceStart, true);
              } else if (videoEl.paused) {
                videoEl.play().catch(() => {});
              }
            } else {
              stopPlaybackAtEnd();
            }
          } else {
            state.currentTime = sourceToTimeline(clip, state.playingSegIdx, vTime);
            applyLivePlaybackSpeed(false);
            applyLiveSegmentVolume();
            applyLiveSegmentCropPosition();
            updateCurvePlayhead();
            updateFvAudioEnvPlayhead();
            if (videoEl.readyState < 3) {
              if (!state.modalPlaying) pauseAllFvAudioPlayers();
            } else {
              syncMusicTimeToVideo(true);
            }
            updatePlayhead();
          }
        }
      }
    } else if (!videoEl.seeking && !videoSeekBusy) {
      state.currentTime = videoEl.currentTime;
      if (videoEl.ended || state.currentTime >= clip.end - 0.04) {
        stopPlaybackAtEnd();
      } else {
        if (videoEl.readyState < 3) {
          if (!state.modalPlaying && !customAudioEl.paused) customAudioEl.pause();
        } else {
          syncMusicTimeToVideo(true);
        }
        updateSubtitleOverlay();
        updatePlayhead();
      }
    }
  }
  if (state.modalPlaying && state.draftMusic && activeClip()) {
    const m = state.draftMusic;
    const clipSpan = getModalSliceSpan();
    const sliceEnd = m.sliceStart + clipSpan;
    if (customAudioEl.currentTime >= sliceEnd) {
      customAudioEl.currentTime = m.sliceStart;
    }
    updateModalPlayhead(customAudioEl.currentTime);
  }
  requestAnimationFrame(tick);
}

let activeSliderUndoEl = null;
let pendingSliderUndoSnap = null;
let sliderUndoCommitted = false;

function initFvSliderUndoHandlers() {
  const sliderIds = [
    'fvSegVolSlider',
    'fvNormalSpeedSlider',
    'fvCropPosSlider',
    'fvAudioVolSlider',
    'fvAudioFadeInSlider',
    'fvAudioFadeOutSlider',
    'fvBrightSlider',
    'fvExposureSlider',
    'fvContrastSlider',
    'fvSatSlider',
    'fvWarmthSlider',
    'fvSharpSlider',
    'fvVignetteSlider',
  ];
  const endGesture = () => {
    activeSliderUndoEl = null;
    pendingSliderUndoSnap = null;
    sliderUndoCommitted = false;
  };
  const capturePre = (el) => {
    if (!isFullVideoMode()) return;
    const clip = activeClip();
    if (!clip) return;
    ensureFullVideoDefaults(clip);
    activeSliderUndoEl = el;
    pendingSliderUndoSnap = snapshotFvState(clip);
    sliderUndoCommitted = false;
  };
  const commitIfNeeded = (el) => {
    if (!isFullVideoMode()) return;
    if (activeSliderUndoEl === el && pendingSliderUndoSnap && !sliderUndoCommitted) {
      sliderUndoCommitted = true;
      if (!state.fvHistory.length || state.fvHistory[state.fvHistory.length - 1] !== pendingSliderUndoSnap) {
        state.fvHistory.push(pendingSliderUndoSnap);
        if (state.fvHistory.length > 40) state.fvHistory.shift();
        state.fvFuture = [];
        updateFvToolbarState();
      }
    }
  };
  sliderIds.forEach((id) => {
    const el = document.getElementById(id);
    if (!el || el.dataset.undoBound) return;
    el.dataset.undoBound = '1';
    el.addEventListener('pointerdown', () => capturePre(el));
    el.addEventListener('keydown', (ev) => {
      if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End', 'PageUp', 'PageDown'].includes(ev.key)) {
        if (activeSliderUndoEl !== el) capturePre(el);
      }
    });
    el.addEventListener('input', () => commitIfNeeded(el), true);
    el.addEventListener('change', () => {
      commitIfNeeded(el);
      endGesture();
    });
    el.addEventListener('blur', () => {
      if (activeSliderUndoEl === el) endGesture();
    });
  });
  window.addEventListener('pointerup', endGesture);
  window.addEventListener('pointercancel', endGesture);
}

function isTextEntryElement(el) {
  if (!el) return false;
  if (el.isContentEditable) return true;
  const tag = el.tagName;
  if (tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (tag === 'INPUT') {
    const t = (el.type || 'text').toLowerCase();
    return !['range', 'checkbox', 'radio', 'button', 'submit', 'color'].includes(t);
  }
  return false;
}

window.addEventListener('keydown', (e) => {
  if (reencodeConfirmResolver) {
    if (e.key === 'Escape') { e.preventDefault(); resolveReencodeConfirm(false); }
    else if (e.key === 'Enter') { e.preventDefault(); resolveReencodeConfirm(true); }
    return;
  }
  const musicModal = document.getElementById('musicPickerModal');
  if (musicModal && !musicModal.classList.contains('hidden')) {
    if (e.key === 'Escape') { e.preventDefault(); closeMusicModal(); }
    else if (e.code === 'Space' && !isTextEntryElement(e.target)) { e.preventDefault(); toggleModalMusicPlay(); }
    return;
  }
  if (e.key === 'Escape' && stageExpanded) { e.preventDefault(); toggleStageExpand(false); return; }
  const hasMod = e.ctrlKey || e.metaKey || e.altKey;
  if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === 's') {
    e.preventDefault();
    saveClip();
    return;
  }
  if (isTextEntryElement(e.target)) return;
  if (isFullVideoMode() && (e.ctrlKey || e.metaKey) && !e.altKey) {
    const k = e.key.toLowerCase();
    if (k === 'z' && !e.shiftKey) { e.preventDefault(); fvUndo(); return; }
    if (k === 'y' || (k === 'z' && e.shiftKey)) { e.preventDefault(); fvRedo(); return; }
  }
  if (hasMod) return;
  const isRangeFocused = e.target?.tagName === 'INPUT' && (e.target.type || '').toLowerCase() === 'range';
  if (e.code === 'Space') { e.preventDefault(); togglePlay(); }
  else if (!isRangeFocused && e.key === 'ArrowLeft') { e.preventDefault(); stepTime(-0.5); }
  else if (!isRangeFocused && e.key === 'ArrowRight') { e.preventDefault(); stepTime(0.5); }
  else if (e.key === 'f' || e.key === 'F') { e.preventDefault(); toggleStageExpand(); }
  else if (isFullVideoMode() && (e.key === 's' || e.key === 'S')) { e.preventDefault(); splitAtPlayhead(); }
  else if (isFullVideoMode() && (e.key === 'q' || e.key === 'Q')) { e.preventDefault(); trimClipToPlayhead('left'); }
  else if (isFullVideoMode() && (e.key === 'w' || e.key === 'W')) { e.preventDefault(); trimClipToPlayhead('right'); }
  else if (isFullVideoMode() && e.shiftKey && e.key.toLowerCase() === 'z') { e.preventDefault(); toggleFvFitTimeline(); }
  else if (isFullVideoMode() && (e.key === 'n' || e.key === 'N')) { e.preventDefault(); toggleFvSnapping(); }
  else if (isFullVideoMode() && (e.key === 'Delete' || e.key === 'Backspace')) { e.preventDefault(); deleteSelectedSegment(); }
});

let lunaTooltipActiveTarget = null;
let lunaTooltipShowTimer = null;

function positionLunaTooltip(target) {
  const tip = document.getElementById('lunaStudioTooltip');
  if (!tip || !target) return false;
  const text = (target.getAttribute('data-tooltip') || '').trim();
  if (!text) return false;
  tip.textContent = text;

  const z = (typeof window.__getLunaUiScale === 'function' ? window.__getLunaUiScale() : 1) || 1;
  const rect = target.getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) return false;

  const vw = (window.innerWidth || document.documentElement.clientWidth || 1280) / z;
  const vh = (window.innerHeight || document.documentElement.clientHeight || 720) / z;
  const rTop = rect.top / z;
  const rBottom = rect.bottom / z;
  const rCenterX = (rect.left + rect.right) / (2 * z);

  const tipW = tip.offsetWidth || 80;
  const tipH = tip.offsetHeight || 26;
  const gap = 8;
  const pad = 10;

  let placement = target.getAttribute('data-tooltip-pos') === 'bottom' ? 'bottom' : 'top';
  let top = placement === 'bottom' ? (rBottom + gap) : (rTop - tipH - gap);
  if (placement === 'top' && top < pad) {
    placement = 'bottom';
    top = rBottom + gap;
  } else if (placement === 'bottom' && top + tipH > vh - pad) {
    placement = 'top';
    top = Math.max(pad, rTop - tipH - gap);
  }

  let left = rCenterX - tipW / 2;
  left = Math.max(pad, Math.min(vw - tipW - pad, left));

  tip.dataset.placement = placement;
  tip.style.left = `${Math.round(left)}px`;
  tip.style.top = `${Math.round(top)}px`;
  return true;
}

function hideLunaTooltip() {
  clearTimeout(lunaTooltipShowTimer);
  lunaTooltipShowTimer = null;
  lunaTooltipActiveTarget = null;
  const tip = document.getElementById('lunaStudioTooltip');
  if (!tip) return;
  tip.classList.remove('is-visible');
  tip.setAttribute('aria-hidden', 'true');
}

function showLunaTooltip(target, immediate = false) {
  const tip = document.getElementById('lunaStudioTooltip');
  if (!tip || !target) return;
  const text = (target.getAttribute('data-tooltip') || '').trim();
  if (!text) { hideLunaTooltip(); return; }
  clearTimeout(lunaTooltipShowTimer);
  const wasVisible = tip.classList.contains('is-visible');
  lunaTooltipActiveTarget = target;
  const reveal = () => {
    if (lunaTooltipActiveTarget !== target || !target.isConnected) return;
    if (!positionLunaTooltip(target)) { hideLunaTooltip(); return; }
    tip.setAttribute('aria-hidden', 'false');
    tip.classList.add('is-visible');
  };
  if (immediate || wasVisible) {
    reveal();
  } else {
    lunaTooltipShowTimer = setTimeout(reveal, 60);
  }
}

function setLunaTooltip(el, text) {
  if (!el) return;
  const next = String(text || '').trim();
  if (next) {
    el.setAttribute('data-tooltip', next);
    el.removeAttribute('title');
    if (lunaTooltipActiveTarget === el) {
      positionLunaTooltip(el);
    }
  } else {
    el.removeAttribute('data-tooltip');
    el.removeAttribute('title');
    if (lunaTooltipActiveTarget === el) hideLunaTooltip();
  }
}

function initLunaStudioTooltips() {
  if (document.body.dataset.lunaTooltipBound === '1') return;
  document.body.dataset.lunaTooltipBound = '1';

  const findDisabledTooltipAt = (root, cx, cy) => {
    if (!root || typeof root.querySelectorAll !== 'function') return null;
    const btns = root.querySelectorAll('button:disabled[data-tooltip]');
    for (let i = 0; i < btns.length; i++) {
      const b = btns[i];
      const r = b.getBoundingClientRect();
      if (r.width > 0 && cx >= r.left && cx <= r.right && cy >= r.top && cy <= r.bottom) {
        return b;
      }
    }
    return null;
  };

  document.addEventListener('pointerover', (ev) => {
    if (ev.pointerType === 'touch') return;
    const target = ev.target?.closest?.('[data-tooltip]');
    if (!target) return;
    if (lunaTooltipActiveTarget === target) return;
    showLunaTooltip(target);
  });

  document.addEventListener('pointerout', (ev) => {
    if (!lunaTooltipActiveTarget || lunaTooltipActiveTarget.disabled) return;
    const related = ev.relatedTarget?.closest?.('[data-tooltip]');
    if (related && related === lunaTooltipActiveTarget) return;
    if (!related) hideLunaTooltip();
  });

  document.addEventListener('pointermove', (ev) => {
    if (ev.pointerType === 'touch') return;
    if (lunaTooltipActiveTarget && lunaTooltipActiveTarget.disabled) {
      const r = lunaTooltipActiveTarget.getBoundingClientRect();
      const stillInside = r.width > 0 && ev.clientX >= r.left && ev.clientX <= r.right && ev.clientY >= r.top && ev.clientY <= r.bottom;
      if (stillInside) return;
      const nextDisabled = findDisabledTooltipAt(ev.target, ev.clientX, ev.clientY);
      if (nextDisabled) {
        showLunaTooltip(nextDisabled, true);
      } else if (!ev.target?.closest?.('[data-tooltip]')) {
        hideLunaTooltip();
      }
      return;
    }
    if (!lunaTooltipActiveTarget && ev.target && !ev.target.closest?.('[data-tooltip]')) {
      const hit = findDisabledTooltipAt(ev.target, ev.clientX, ev.clientY);
      if (hit) showLunaTooltip(hit);
    }
  }, { passive: true });

  document.addEventListener('focusin', (ev) => {
    const target = ev.target?.closest?.('[data-tooltip]');
    if (target && target.matches(':focus-visible')) showLunaTooltip(target, true);
  });
  document.addEventListener('focusout', (ev) => {
    if (lunaTooltipActiveTarget && ev.target?.closest?.('[data-tooltip]') === lunaTooltipActiveTarget) {
      hideLunaTooltip();
    }
  });
  document.addEventListener('pointerdown', hideLunaTooltip, { passive: true });
  document.addEventListener('wheel', hideLunaTooltip, { passive: true });
  document.addEventListener('scroll', hideLunaTooltip, { capture: true, passive: true });
  document.documentElement.addEventListener('pointerleave', hideLunaTooltip);
  window.addEventListener('blur', hideLunaTooltip);
  window.addEventListener('resize', hideLunaTooltip);
}

async function init() {
  initLunaStudioTooltips();
  renderStyleCards();
  initFvSliderUndoHandlers();
  try {
    const res = await fetch(`/api/studio/${encodeURIComponent(PROJECT_ID)}`);
    if (!res.ok) throw new Error('Workspace not found');
    const data = await res.json();
    state.mode = data.mode === 'full_video' ? 'full_video' : 'ai_clip';
    document.getElementById('projectTitle').textContent = data.workspace_name || (isFullVideoMode() ? 'Full Video Studio' : 'AI Clipper Studio');
    document.title = `${data.workspace_name || 'Studio'} | Luna`;
    WORKSPACE_CLIPS = (data.clips || []).map(ensureFullVideoDefaults);

    applyStudioModeLayout();

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

    if (!isFullVideoMode()) {
      setSubStyle(state.subStyle, true);
      setSubSize(state.subSize, true);
      setSubPos(state.subPos, true);
    }
    if (WORKSPACE_CLIPS.length) {
      selectWorkspaceClip(state.activeIdx);
    } else {
      showToast('No video files found in this project');
    }
  } catch (err) {
    showToast(err.message || 'Could not load project');
  }
  if (window.lucide) lucide.createIcons();
  requestAnimationFrame(tick);
}

init();
