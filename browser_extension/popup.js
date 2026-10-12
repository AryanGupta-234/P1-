"use strict";

const enabled = document.getElementById("enabled");
const status = document.getElementById("status");

function renderStatus(bridgeStatus) {
  status.textContent = "Bridge status: " + (bridgeStatus || "not connected yet");
}

function refreshStatus() {
  chrome.runtime.sendMessage({ kind: "AIE_GET_STATUS" }, (result) => {
    if (chrome.runtime.lastError) {
      renderStatus(chrome.runtime.lastError.message);
      return;
    }
    if (!result) return;
    enabled.checked = result.enabled === true;
    renderStatus(result.bridgeStatus);
  });
}

function testConnection() {
  renderStatus("checking native host...");
  chrome.runtime.sendMessage({ kind: "AIE_CONNECT_TEST" }, (result) => {
    if (chrome.runtime.lastError) {
      renderStatus("connection test failed: " + chrome.runtime.lastError.message);
      return;
    }
    if (result) renderStatus(result.bridgeStatus);
    else refreshStatus();
  });
}

enabled.addEventListener("change", () => {
  chrome.storage.local.set({ enabled: enabled.checked }, () => {
    if (enabled.checked) testConnection();
    else refreshStatus();
  });
});

refreshStatus();
testConnection();
