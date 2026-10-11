"use strict";

const enabled = document.getElementById("enabled");
const status = document.getElementById("status");

function refreshStatus() {
  chrome.runtime.sendMessage({ kind: "AIE_GET_STATUS" }, (result) => {
    if (chrome.runtime.lastError) {
      status.textContent = "Bridge status: " + chrome.runtime.lastError.message;
      return;
    }
    if (!result) return;
    enabled.checked = result.enabled === true;
    status.textContent = "Bridge status: " + (result.bridgeStatus || "not connected yet");
  });
}

enabled.addEventListener("change", () => {
  chrome.storage.local.set({ enabled: enabled.checked }, refreshStatus);
});

refreshStatus();
