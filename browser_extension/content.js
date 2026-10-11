(() => {
  "use strict";

  const STORAGE_KEY = "enabled";
  const SAMPLE_INTERVAL_MS = 5000;
  const OBSERVATION_WINDOW_SECONDS = 60;
  const watchedVideos = new Map();

  let enabled = false;
  let mutationObserver = null;
  let sampleTimer = null;

  function sendSnapshot(payload) {
    try {
      const result = chrome.runtime.sendMessage({
        kind: "AIE_VIDEO_SNAPSHOT",
        payload
      });
      if (result && typeof result.catch === "function") {
        result.catch(() => {});
      }
    } catch (_) {
      // The observer must never interfere with page playback.
    }
  }

  function bufferedAheadSeconds(video) {
    try {
      const position = video.currentTime;
      for (let index = 0; index < video.buffered.length; index += 1) {
        const start = video.buffered.start(index);
        const end = video.buffered.end(index);
        if (position >= start && position <= end) {
          return Math.max(0, end - position);
        }
      }
    } catch (_) {
      // MediaSource implementations can mutate ranges while being inspected.
    }
    return null;
  }

  function playbackState(video, state) {
    if (video.ended) return "ended";
    if (video.paused) return "paused";
    if (state.isStalled || video.readyState < 3) return "waiting";
    return "playing";
  }

  function report(video, state) {
    if (!enabled || !video.isConnected) return;

    const now = Date.now();
    state.stallTimes = state.stallTimes.filter(
      (timestamp) => now - timestamp <= OBSERVATION_WINDOW_SECONDS * 1000
    );

    let droppedFramesPct = null;
    try {
      if (typeof video.getVideoPlaybackQuality === "function") {
        const quality = video.getVideoPlaybackQuality();
        const total = Number(quality.totalVideoFrames);
        const dropped = Number(quality.droppedVideoFrames);
        if (
          Number.isFinite(total) &&
          Number.isFinite(dropped) &&
          state.lastQuality &&
          total >= state.lastQuality.total &&
          dropped >= state.lastQuality.dropped
        ) {
          const decodedDelta = total - state.lastQuality.total;
          const droppedDelta = dropped - state.lastQuality.dropped;
          const frameDelta = decodedDelta + droppedDelta;
          if (frameDelta > 0) {
            droppedFramesPct = Math.min(100, (droppedDelta / frameDelta) * 100);
          }
        }
        if (Number.isFinite(total) && Number.isFinite(dropped)) {
          state.lastQuality = { total, dropped };
        }
      }
    } catch (_) {
      // Quality counters are optional browser telemetry.
    }

    let progressDelta = null;
    try {
      if (Number.isFinite(video.currentTime) && state.lastPosition !== null) {
        progressDelta = Math.max(0, video.currentTime - state.lastPosition);
      }
      if (Number.isFinite(video.currentTime)) {
        state.lastPosition = video.currentTime;
      }
    } catch (_) {
      // currentTime can be unavailable during source transitions.
    }

    const payload = {
      kind: "video_snapshot",
      media_session_id: state.mediaSessionId,
      playback_state: playbackState(video, state),
      stall_count: state.stallTimes.length,
      observation_window_seconds: OBSERVATION_WINDOW_SECONDS
    };

    const buffered = bufferedAheadSeconds(video);
    if (buffered !== null && Number.isFinite(buffered)) {
      payload.buffered_ahead_seconds = buffered;
    }
    if (progressDelta !== null && Number.isFinite(progressDelta)) {
      payload.playback_progress_delta_seconds = progressDelta;
    }
    if (droppedFramesPct !== null && Number.isFinite(droppedFramesPct)) {
      payload.dropped_frames_pct = droppedFramesPct;
    }

    sendSnapshot(payload);
  }

  function attach(video) {
    if (!(video instanceof HTMLVideoElement) || watchedVideos.has(video)) return;

    const state = {
      mediaSessionId: crypto.randomUUID(),
      stallTimes: [],
      isStalled: false,
      lastPosition: null,
      lastQuality: null,
      listeners: []
    };

    const listen = (eventName, handler) => {
      video.addEventListener(eventName, handler, { passive: true });
      state.listeners.push([eventName, handler]);
    };

    const markStalled = () => {
      if (!state.isStalled) {
        state.isStalled = true;
        state.stallTimes.push(Date.now());
      }
      report(video, state);
    };

    const markPlaying = () => {
      state.isStalled = false;
      report(video, state);
    };

    listen("waiting", markStalled);
    listen("stalled", markStalled);
    listen("playing", markPlaying);
    listen("pause", () => report(video, state));
    listen("ended", () => report(video, state));
    listen("loadeddata", () => report(video, state));

    watchedVideos.set(video, state);
  }

  function scan(root) {
    if (!enabled || !root) return;
    if (root instanceof HTMLVideoElement) attach(root);
    if (typeof root.querySelectorAll === "function") {
      root.querySelectorAll("video").forEach(attach);
    }
  }

  function startMonitoring() {
    if (enabled) return;
    enabled = true;
    scan(document);

    mutationObserver = new MutationObserver((records) => {
      for (const record of records) {
        record.addedNodes.forEach(scan);
      }
    });

    if (document.documentElement) {
      mutationObserver.observe(document.documentElement, {
        childList: true,
        subtree: true
      });
    }

    sampleTimer = window.setInterval(() => {
      for (const [video, state] of watchedVideos.entries()) {
        if (!video.paused && !video.ended) report(video, state);
      }
    }, SAMPLE_INTERVAL_MS);
  }

  function stopMonitoring() {
    enabled = false;
    if (mutationObserver) mutationObserver.disconnect();
    mutationObserver = null;
    if (sampleTimer !== null) window.clearInterval(sampleTimer);
    sampleTimer = null;

    for (const [video, state] of watchedVideos.entries()) {
      for (const [eventName, handler] of state.listeners) {
        video.removeEventListener(eventName, handler);
      }
    }
    watchedVideos.clear();
  }

  chrome.storage.local.get({ [STORAGE_KEY]: false }, (settings) => {
    if (settings[STORAGE_KEY] === true) startMonitoring();
  });

  chrome.storage.onChanged.addListener((changes, areaName) => {
    if (areaName !== "local" || !changes[STORAGE_KEY]) return;
    if (changes[STORAGE_KEY].newValue === true) startMonitoring();
    else stopMonitoring();
  });
})();
