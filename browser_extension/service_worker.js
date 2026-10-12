"use strict";

const NATIVE_HOST = "com.aie.browser_bridge";
const HANDSHAKE_TIMEOUT_MS = 5000;
let nativePort = null;
let pendingHandshake = null;

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

function settleHandshake(result) {
  if (!pendingHandshake) return;
  const pending = pendingHandshake;
  pendingHandshake = null;
  clearTimeout(pending.timeout);
  if (result && result.bridgeStatus) persistBridgeStatus(result.bridgeStatus);
  pending.respond(result);
}

function getNativePort() {
  if (nativePort) return nativePort;

  const port = chrome.runtime.connectNative(NATIVE_HOST);
  nativePort = port;

  port.onMessage.addListener((message) => {
    if (message && message.kind === "bridge_pong" && message.ok === true) {
      persistBridgeStatus("connected");
      settleHandshake({ ok: true, bridgeStatus: "connected" });
      return;
    }

    if (message && message.ok === true) {
      persistBridgeStatus("connected");
    } else {
      const reason = message && message.error
        ? "rejected: " + message.error
        : "host returned an invalid response";
      persistBridgeStatus(reason);
      if (pendingHandshake) settleHandshake({ ok: false, bridgeStatus: reason });
    }
  });

  port.onDisconnect.addListener(() => {
    const reason = chrome.runtime.lastError
      ? chrome.runtime.lastError.message
      : "native host disconnected";
    nativePort = null;
    persistBridgeStatus("disconnected: " + reason);
    if (pendingHandshake) {
      settleHandshake({ ok: false, bridgeStatus: "disconnected: " + reason });
    }
  });

  persistBridgeStatus("connecting");
  return port;
}

function testNativeConnection(sendResponse) {
  if (pendingHandshake) {
    settleHandshake({ ok: false, bridgeStatus: "connection test superseded" });
  }

  let port;
  try {
    port = getNativePort();
    const timeout = setTimeout(() => {
      settleHandshake({ ok: false, bridgeStatus: "connection timed out" });
    }, HANDSHAKE_TIMEOUT_MS);
    pendingHandshake = {
      timeout,
      respond: sendResponse,
    };
    port.postMessage({ kind: "bridge_ping" });
  } catch (error) {
    nativePort = null;
    const reason = error && error.message ? error.message : "native host unavailable";
    const status = "disconnected: " + reason;
    persistBridgeStatus(status);
    sendResponse({ ok: false, bridgeStatus: status });
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message && message.kind === "AIE_GET_STATUS") {
    chrome.storage.local.get(
      { enabled: false, bridgeStatus: "not connected yet" },
      (settings) => sendResponse(settings)
    );
    return true;
  }

  if (message && message.kind === "AIE_CONNECT_TEST") {
    testNativeConnection(sendResponse);
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
      persistBridgeStatus("disconnected: " + reason);
      sendResponse({ ok: false, reason });
    }
  });
  return true;
});
