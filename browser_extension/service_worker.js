"use strict";

const NATIVE_HOST = "com.aie.browser_bridge";
let nativePort = null;

function persistBridgeStatus(status) {
  chrome.storage.local.set({ bridgeStatus: status });
}

function isTrustedVideoSender(sender) {
  if (!sender || sender.id !== chrome.runtime.id) return false;
  const location = typeof sender.origin === "string" ? sender.origin : sender.url;
  if (typeof location !== "string") return false;
  try {
    const parsed = new URL(location);
    return parsed.protocol === "https:" || parsed.protocol === "http:";
  } catch (_) {
    return false;
  }
}

function getNativePort() {
  if (nativePort) return nativePort;

  nativePort = chrome.runtime.connectNative(NATIVE_HOST);
  nativePort.onMessage.addListener((message) => {
    if (message && message.ok === true) {
      persistBridgeStatus("connected");
    } else {
      persistBridgeStatus(
        message && message.error
          ? "rejected: " + message.error
          : "host returned an invalid response"
      );
    }
  });
  nativePort.onDisconnect.addListener(() => {
    const reason = chrome.runtime.lastError
      ? chrome.runtime.lastError.message
      : "native host disconnected";
    nativePort = null;
    persistBridgeStatus("disconnected: " + reason);
  });
  persistBridgeStatus("connecting");
  return nativePort;
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message && message.kind === "AIE_GET_STATUS") {
    chrome.storage.local.get(
      { enabled: false, bridgeStatus: "not connected yet" },
      (settings) => sendResponse(settings)
    );
    return true;
  }

  if (!message || message.kind !== "AIE_VIDEO_SNAPSHOT" || !message.payload) {
    return false;
  }
  if (!isTrustedVideoSender(sender)) {
    sendResponse({ ok: false, reason: "untrusted_sender" });
    return false;
  }

  chrome.storage.local.get({ enabled: false }, (settings) => {
    if (settings.enabled !== true) {
      sendResponse({ ok: false, reason: "monitoring_disabled" });
      return;
    }

    try {
      const port = getNativePort();
      port.postMessage(message.payload);
      sendResponse({ ok: true });
    } catch (error) {
      nativePort = null;
      const reason = error && error.message ? error.message : "native host unavailable";
      persistBridgeStatus("error: " + reason);
      sendResponse({ ok: false, reason });
    }
  });
  return true;
});
