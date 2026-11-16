# Copyright (C) 2026 Miqdad
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of Luna. See LICENSE and NOTICE at the repository root.

"""Multi-connection HTTP/2 range downloader for yt-dlp streams.

YouTube serves high-bitrate adaptive streams (e.g. 1080p ``f137``) over plain
``https`` rather than segmented DASH/HLS. Stock ``yt-dlp`` opens a single
HTTP/1.1 connection for those streams, which YouTube routinely throttles.
This module routes eligible ``http``/``https`` downloads through a 4-connection
work-stealing ``Range`` pool over HTTP/2 (via ``curl_cffi`` Chrome TLS
impersonation, with a ``requests`` fallback) and falls back cleanly to stock
``HttpFD`` whenever the origin does not support byte ranges.
"""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import os
import queue
import re
import threading
import time
from typing import Any, Deque, Dict, List, Optional, Tuple
import weakref

import requests

try:
    from curl_cffi import requests as _cf_requests  # type: ignore
except ImportError:
    _cf_requests = None

DEFAULT_PARALLEL_CONNECTIONS = 4
MIN_PARALLEL_BYTES = 2 * 1024 * 1024
MIN_CHUNK_BYTES = 1 * 1024 * 1024
MAX_CHUNK_BYTES = 3 * 1024 * 1024
STREAM_BLOCK_BYTES = 64 * 1024
SPEED_WINDOW_SEC = 2.5
PROGRESS_INTERVAL_SEC = 0.25

_CONTENT_RANGE_RE = re.compile(r"^bytes\s+(\d+)-(\d+)/(\d+)$", re.IGNORECASE)
_YDL_CLASS_CACHE: "weakref.WeakKeyDictionary[Any, type]" = weakref.WeakKeyDictionary()
_YDL_CACHE_LOCK = threading.Lock()


def _strip_header_case_insensitive(headers: Dict[str, str], name: str) -> None:
    target = name.lower()
    for key in [k for k in headers if k.lower() == target]:
        del headers[key]


def _build_request_headers(
    info_dict: Dict[str, Any],
    url: str,
    cookiejar: Any = None,
) -> Dict[str, str]:
    headers = {str(k): str(v) for k, v in (info_dict.get("http_headers") or {}).items()}
    _strip_header_case_insensitive(headers, "accept-encoding")
    headers["Accept-Encoding"] = "identity"

    if cookiejar is not None and hasattr(cookiejar, "get_cookie_header"):
        has_cookie = any(k.lower() == "cookie" for k in headers)
        if not has_cookie:
            cookie_header = cookiejar.get_cookie_header(url)
            if cookie_header:
                headers["Cookie"] = cookie_header
    return headers


def _create_http_session(proxy: Optional[str], workers: int) -> Tuple[Any, bool]:
    """Return ``(session, uses_curl_cffi)`` configured for optional HTTP proxy."""
    proxies = {"http": proxy, "https": proxy} if proxy else None
    if _cf_requests is not None:
        kwargs: Dict[str, Any] = {"impersonate": "chrome"}
        if proxies:
            kwargs["proxies"] = proxies
        return _cf_requests.Session(**kwargs), True

    sess = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=workers, pool_maxsize=workers)
    sess.mount("http://", adapter)
    sess.mount("https://", adapter)
    if proxies:
        sess.proxies.update(proxies)
    return sess, False


def _session_get(
    sess: Any,
    uses_curl: bool,
    url: str,
    headers: Dict[str, str],
    timeout: Tuple[float, float],
):
    if uses_curl:
        return sess.get(
            url,
            headers=headers,
            stream=True,
            timeout=timeout,
            accept_encoding="identity",
        )
    return sess.get(url, headers=headers, stream=True, timeout=timeout)


def _probe_range_support(
    url: str,
    headers: Dict[str, str],
    cookiejar: Any,
    proxy: Optional[str],
    timeout: Tuple[float, float],
) -> Optional[Tuple[str, int]]:
    """Verify byte-range support and return ``(resolved_url, total_size)`` or ``None``."""
    probe_headers = {**headers, "Range": "bytes=0-0"}
    for attempt in range(2):
        sess, uses_curl = _create_http_session(proxy, workers=1)
        resp = None
        try:
            resp = _session_get(sess, uses_curl, url, probe_headers, timeout)
            if getattr(resp, "status_code", None) != 206:
                return None

            resp_headers = getattr(resp, "headers", {}) or {}
            content_range = ""
            for k, v in resp_headers.items():
                if str(k).lower() == "content-range":
                    content_range = str(v)
                    break
            match = _CONTENT_RANGE_RE.match(content_range.strip())
            if not match:
                return None

            total_size = int(match.group(3))
            if total_size < MIN_PARALLEL_BYTES:
                return None

            final_url = str(getattr(resp, "url", "") or url)
            # Recompute Cookie header if CDN redirect switched hostnames
            if final_url != url and cookiejar is not None and hasattr(cookiejar, "get_cookie_header"):
                refreshed = cookiejar.get_cookie_header(final_url)
                if refreshed:
                    headers["Cookie"] = refreshed
            return final_url, total_size
        except Exception:
            if attempt == 1:
                return None
            time.sleep(0.25)
        finally:
            if resp is not None:
                try:
                    resp.close()
                except Exception:
                    pass
            try:
                sess.close()
            except Exception:
                pass
    return None


def _build_chunk_plan(total_size: int, workers: int) -> List[Tuple[int, int]]:
    target = total_size // max(1, workers * 4)
    chunk_size = max(MIN_CHUNK_BYTES, min(MAX_CHUNK_BYTES, target))
    ranges: List[Tuple[int, int]] = []
    start = 0
    while start < total_size:
        end = min(total_size - 1, start + chunk_size - 1)
        ranges.append((start, end))
        start = end + 1
    return ranges


def _moving_speed(samples: Deque[Tuple[float, int]], now: float) -> Optional[float]:
    cutoff = now - SPEED_WINDOW_SEC
    while samples and samples[0][0] < cutoff:
        samples.popleft()
    if not samples:
        return None
    total_bytes = sum(delta for _, delta in samples)
    span = max(0.2, now - samples[0][0])
    return total_bytes / span


def build_fast_http_fd(ytdlp_mod: Any):
    """Build an ``HttpFD`` subclass bound to the provided ``yt_dlp`` module."""
    HttpFD = ytdlp_mod.downloader.http.HttpFD

    class FastHttpFD(HttpFD):
        def real_download(self, filename, info_dict):
            if (
                filename == "-"
                or self.params.get("test", False)
                or info_dict.get("request_data") is not None
                or info_dict.get("is_live")
                or info_dict.get("impersonate") is not None
            ):
                return super().real_download(filename, info_dict)

            url = info_dict["url"]
            proxy = self.params.get("proxy")
            if proxy and not str(proxy).startswith(("http://", "https://")):
                return super().real_download(filename, info_dict)

            headers = info_dict.get("http_headers") or {}
            if "Range" in headers or "range" in headers:
                return super().real_download(filename, info_dict)

            req_headers = _build_request_headers(
                info_dict,
                url,
                cookiejar=getattr(self.ydl, "cookiejar", None),
            )
            sock_timeout = float(self.params.get("socket_timeout") or 15)
            req_timeout = (min(10.0, sock_timeout), max(15.0, sock_timeout))

            probe = _probe_range_support(
                url,
                req_headers,
                cookiejar=getattr(self.ydl, "cookiejar", None),
                proxy=proxy,
                timeout=req_timeout,
            )
            if probe is None:
                return super().real_download(filename, info_dict)

            resolved_url, total_size = probe
            tmpfilename = self.temp_name(filename)
            parent = os.path.dirname(os.path.abspath(tmpfilename))
            if parent:
                os.makedirs(parent, exist_ok=True)

            self.report_destination(filename)
            # Pre-allocate the target length so each worker can write its byte
            # range straight to offset without buffering chunks in RAM.
            try:
                with open(tmpfilename, "wb") as fp:
                    fp.seek(total_size - 1)
                    fp.write(b"\0")
            except OSError:
                return super().real_download(filename, info_dict)

            workers = int(self.params.get("fast_http_connections") or DEFAULT_PARALLEL_CONNECTIONS)
            workers = max(1, min(8, workers))
            max_retries = int(self.params.get("retries") or 5)
            chunks = _build_chunk_plan(total_size, workers)

            chunk_queue: "queue.Queue[Tuple[int, int]]" = queue.Queue()
            for item in chunks:
                chunk_queue.put(item)

            start_time = time.time()
            state_lock = threading.Lock()
            hook_lock = threading.Lock()
            abort_event = threading.Event()
            samples: Deque[Tuple[float, int]] = deque()
            state: Dict[str, Any] = {
                "downloaded": 0,
                "last_hook": 0.0,
                "error": None,
            }

            def emit_progress(force: bool = False) -> None:
                now = time.time()
                with hook_lock:
                    if not force and (now - state["last_hook"]) < PROGRESS_INTERVAL_SEC:
                        return
                    with state_lock:
                        downloaded = state["downloaded"]
                        speed = _moving_speed(samples, now)
                        if speed is None and now > start_time and downloaded > 0:
                            speed = downloaded / max(0.1, now - start_time)
                    state["last_hook"] = now
                    eta = (
                        (total_size - downloaded) / speed
                        if speed and speed > 0 and downloaded < total_size
                        else None
                    )
                    try:
                        self._hook_progress(
                            {
                                "status": "downloading",
                                "downloaded_bytes": downloaded,
                                "total_bytes": total_size,
                                "tmpfilename": tmpfilename,
                                "filename": filename,
                                "eta": eta,
                                "speed": speed,
                                "elapsed": now - start_time,
                                "ctx_id": info_dict.get("ctx_id"),
                            },
                            info_dict,
                        )
                    except Exception as hook_err:
                        with state_lock:
                            if state["error"] is None:
                                state["error"] = hook_err
                        abort_event.set()
                        raise

            fh = open(tmpfilename, "r+b")
            try:
                def worker() -> None:
                    sess, uses_curl = _create_http_session(proxy, workers=1)
                    try:
                        while not abort_event.is_set():
                            try:
                                c_start, c_end = chunk_queue.get_nowait()
                            except queue.Empty:
                                return

                            pos = c_start
                            for attempt in range(max_retries + 1):
                                if abort_event.is_set():
                                    return
                                resp = None
                                try:
                                    chunk_headers = {**req_headers, "Range": f"bytes={pos}-{c_end}"}
                                    resp = _session_get(sess, uses_curl, resolved_url, chunk_headers, req_timeout)
                                    code = getattr(resp, "status_code", None)
                                    if code != 206:
                                        raise RuntimeError(f"Unexpected range HTTP {code}")

                                    blocks = (
                                        resp.iter_content()
                                        if uses_curl
                                        else resp.iter_content(chunk_size=STREAM_BLOCK_BYTES)
                                    )
                                    for block in blocks:
                                        if abort_event.is_set():
                                            return
                                        if not block:
                                            continue
                                        remaining = c_end - pos + 1
                                        if remaining <= 0:
                                            break
                                        if len(block) > remaining:
                                            block = block[:remaining]

                                        now = time.time()
                                        with state_lock:
                                            fh.seek(pos)
                                            fh.write(block)
                                            written = len(block)
                                            pos += written
                                            state["downloaded"] += written
                                            samples.append((now, written))
                                        emit_progress(force=False)
                                        if pos > c_end:
                                            break

                                    if pos > c_end:
                                        break
                                    raise EOFError(f"Short chunk read ({pos}/{c_end + 1})")
                                except Exception as exc:
                                    if abort_event.is_set():
                                        return
                                    if attempt >= max_retries:
                                        with state_lock:
                                            if state["error"] is None:
                                                state["error"] = exc
                                        abort_event.set()
                                        return
                                    time.sleep(min(2.0, 0.25 * (attempt + 1)))
                                finally:
                                    if resp is not None:
                                        try:
                                            resp.close()
                                        except Exception:
                                            pass
                    finally:
                        try:
                            sess.close()
                        except Exception:
                            pass

                try:
                    emit_progress(force=True)
                    with ThreadPoolExecutor(max_workers=workers) as pool:
                        futures = [pool.submit(worker) for _ in range(workers)]
                        for fut in futures:
                            fut.result()
                    fh.flush()
                except Exception:
                    fh.close()
                    self.try_remove(tmpfilename)
                    raise
            finally:
                if not fh.closed:
                    fh.close()

            if state["error"] is not None:
                self.try_remove(tmpfilename)
                if "CANCELLED_BY_USER" in str(state["error"]):
                    raise state["error"]
                self.to_screen(f"[download] FastHttpFD fallback after error: {state['error']}")
                return super().real_download(filename, info_dict)

            if state["downloaded"] != total_size or os.path.getsize(tmpfilename) != total_size:
                self.try_remove(tmpfilename)
                return super().real_download(filename, info_dict)

            self.try_rename(tmpfilename, filename)
            self._hook_progress(
                {
                    "downloaded_bytes": total_size,
                    "total_bytes": total_size,
                    "filename": filename,
                    "status": "finished",
                    "elapsed": time.time() - start_time,
                    "ctx_id": info_dict.get("ctx_id"),
                },
                info_dict,
            )
            return True

    return FastHttpFD


def _get_fast_ydl_class(ytdlp_mod: Any) -> type:
    with _YDL_CACHE_LOCK:
        cached = _YDL_CLASS_CACHE.get(ytdlp_mod)
        if cached is not None:
            return cached

        ydl_cls = ytdlp_mod.YoutubeDL
        FastHttpFD = build_fast_http_fd(ytdlp_mod)
        determine_protocol = ytdlp_mod.utils.determine_protocol

        class FastYoutubeDL(ydl_cls):
            def dl(self, name, info, subtitle=False, test=False):
                if (
                    not test
                    and not subtitle
                    and name != "-"
                    and info.get("url")
                    and not info.get("section_start")
                    and not info.get("section_end")
                    and not info.get("is_live")
                    and not info.get("request_data")
                    and info.get("impersonate") is None
                ):
                    proto = info.get("protocol") or determine_protocol(info)
                    if proto in ("http", "https"):
                        fd = FastHttpFD(self, self.params)
                        for ph in self._progress_hooks:
                            fd.add_progress_hook(ph)
                        new_info = self._copy_infodict(info)
                        if new_info.get("http_headers") is None:
                            new_info["http_headers"] = self._calc_headers(new_info)
                        new_info["protocol"] = proto
                        return fd.download(name, new_info, subtitle)
                return super().dl(name, info, subtitle=subtitle, test=test)

        _YDL_CLASS_CACHE[ytdlp_mod] = FastYoutubeDL
        return FastYoutubeDL


def create_youtube_dl(ydl_opts: Dict[str, Any], ytdlp_mod: Any = None):
    """Instantiate ``YoutubeDL`` enhanced with parallel HTTP/2 range downloads.

    When ``ytdlp_mod`` is a mocked module in unit tests (not a real class), this
    calls ``ytdlp_mod.YoutubeDL(ydl_opts)`` directly so test doubles inspect the
    exact options dict without requiring a full ``YoutubeDL`` base class.
    """
    if ytdlp_mod is None:
        import yt_dlp as ytdlp_mod  # type: ignore

    ydl_cls = getattr(ytdlp_mod, "YoutubeDL", None)
    if not isinstance(ydl_cls, type):
        return ytdlp_mod.YoutubeDL(ydl_opts)

    fast_cls = _get_fast_ydl_class(ytdlp_mod)
    return fast_cls(ydl_opts)
