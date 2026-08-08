const state = {
  source: "file",
  file: null,
  originalUrl: null,
  resultUrl: null,
};

const form = document.querySelector("#remove-form");
const apiKeyInput = document.querySelector("#api-key");
const fileInput = document.querySelector("#file-input");
const fileName = document.querySelector("#file-name");
const urlInput = document.querySelector("#url-input");
const filePanel = document.querySelector("#file-panel");
const urlPanel = document.querySelector("#url-panel");
const dropZone = document.querySelector("#drop-zone");
const removeButton = document.querySelector("#remove-button");
const statusMessage = document.querySelector("#status-message");
const originalPreview = document.querySelector("#original-preview");
const originalEmpty = document.querySelector("#original-empty");
const resultPanel = document.querySelector("#result-panel");
const resultEmpty = document.querySelector("#result-empty");
const resultPreview = document.querySelector("#result-preview");
const downloadButton = document.querySelector("#download-button");

function setStatus(message, kind = "idle") {
  statusMessage.textContent = message;
  statusMessage.className = `status-message${kind === "idle" ? "" : ` is-${kind}`}`;
}

function clearObjectUrl(key) {
  if (state[key]) {
    URL.revokeObjectURL(state[key]);
    state[key] = null;
  }
}

function setOriginalPreview(blobOrFile) {
  clearObjectUrl("originalUrl");
  state.originalUrl = URL.createObjectURL(blobOrFile);
  originalPreview.src = state.originalUrl;
  originalPreview.hidden = false;
  originalEmpty.hidden = true;
}

function setSource(source) {
  state.source = source;
  const isFile = source === "file";
  filePanel.classList.toggle("is-hidden", !isFile);
  urlPanel.classList.toggle("is-hidden", isFile);
  fileInput.disabled = !isFile;
  urlInput.disabled = isFile;
  setStatus(isFile ? "选择本地图片后开始。" : "输入图片 URL 后开始。");
}

function setSelectedFile(file) {
  if (!file || !file.type.startsWith("image/")) {
    state.file = null;
    fileName.textContent = "请选择图片文件";
    setStatus("文件格式不支持，请选择图片。", "error");
    return;
  }
  state.file = file;
  fileName.textContent = file.name;
  setOriginalPreview(file);
  resultPanel.hidden = true;
  resultEmpty.hidden = false;
  clearObjectUrl("resultUrl");
  setStatus("图片已准备好，可以开始抠图。", "success");
}

async function parseError(response) {
  try {
    const payload = await response.json();
    if (payload.detail) return payload.detail;
  } catch (_) {
    // Fall through to a status-based message for non-JSON responses.
  }
  return `请求失败（HTTP ${response.status}）`;
}

function setBusy(isBusy) {
  removeButton.disabled = isBusy;
  removeButton.classList.toggle("is-loading", isBusy);
  document.querySelectorAll("#remove-form input").forEach((input) => {
    input.disabled = isBusy || (input.id === "file-input" && state.source !== "file") || (input.id === "url-input" && state.source !== "url");
  });
}

async function removeBackground(event) {
  event.preventDefault();
  const apiKey = apiKeyInput.value.trim();
  if (!apiKey) {
    setStatus("请先填写 API Key。", "error");
    apiKeyInput.focus();
    return;
  }

  let request;
  if (state.source === "file") {
    if (!state.file) {
      setStatus("请先选择一张图片。", "error");
      return;
    }
    const body = new FormData();
    body.append("file", state.file);
    request = fetch("/v1/remove-background", { method: "POST", headers: { "X-API-Key": apiKey }, body });
  } else {
    const imageUrl = urlInput.value.trim();
    if (!imageUrl) {
      setStatus("请输入图片 URL。", "error");
      urlInput.focus();
      return;
    }
    request = fetch("/v1/remove-background/url", { method: "POST", headers: { "X-API-Key": apiKey, "Content-Type": "application/json" }, body: JSON.stringify({ image_url: imageUrl }) });
  }

  setBusy(true);
  setStatus("正在使用 GPU 处理，请稍候……", "idle");
  try {
    const response = await request;
    if (!response.ok) throw new Error(await parseError(response));
    const resultBlob = await response.blob();
    clearObjectUrl("resultUrl");
    state.resultUrl = URL.createObjectURL(resultBlob);
    resultPreview.src = state.resultUrl;
    downloadButton.href = state.resultUrl;
    resultPanel.hidden = false;
    resultEmpty.hidden = true;
    setStatus("处理完成，可以下载透明 PNG。", "success");
  } catch (error) {
    setStatus(error.message || "网络连接失败，请稍后重试。", "error");
  } finally {
    setBusy(false);
  }
}

document.querySelectorAll('input[name="source"]').forEach((input) => input.addEventListener("change", (event) => setSource(event.target.value)));
fileInput.addEventListener("change", () => setSelectedFile(fileInput.files[0]));
dropZone.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    fileInput.click();
  }
});
["dragenter", "dragover"].forEach((eventName) => dropZone.addEventListener(eventName, (event) => {
  event.preventDefault();
  dropZone.classList.add("is-dragging");
}));
["dragleave", "drop"].forEach((eventName) => dropZone.addEventListener(eventName, (event) => {
  event.preventDefault();
  dropZone.classList.remove("is-dragging");
}));
dropZone.addEventListener("drop", (event) => setSelectedFile(event.dataTransfer.files[0]));
form.addEventListener("submit", removeBackground);
window.addEventListener("beforeunload", () => {
  clearObjectUrl("originalUrl");
  clearObjectUrl("resultUrl");
});
