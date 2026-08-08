const state = {
  source: "file",
  file: null,
  originalUrl: null,
  resultUrl: null,
  requestController: null,
};

const form = document.querySelector("#remove-form");
const apiKeyInput = document.querySelector("#api-key");
const modelSelect = document.querySelector("#model-select");
const modelHint = document.querySelector("#model-hint");
const alphaMattingInput = document.querySelector("#alpha-matting");
const foregroundThresholdInput = document.querySelector("#alpha-matting-foreground-threshold");
const backgroundThresholdInput = document.querySelector("#alpha-matting-background-threshold");
const erodeSizeInput = document.querySelector("#alpha-matting-erode-size");
const postProcessMaskInput = document.querySelector("#post-process-mask");
const fileInput = document.querySelector("#file-input");
const fileName = document.querySelector("#file-name");
const urlInput = document.querySelector("#url-input");
const filePanel = document.querySelector("#file-panel");
const urlPanel = document.querySelector("#url-panel");
const dropZone = document.querySelector("#drop-zone");
const removeButton = document.querySelector("#remove-button");
const buttonLabel = removeButton.querySelector(".button-label");
const statusMessage = document.querySelector("#status-message");
const originalPreview = document.querySelector("#original-preview");
const originalPreviewTrigger = document.querySelector("#original-preview-trigger");
const originalEmpty = document.querySelector("#original-empty");
const resultPanel = document.querySelector("#result-panel");
const resultEmpty = document.querySelector("#result-empty");
const resultPreview = document.querySelector("#result-preview");
const resultPreviewTrigger = document.querySelector("#result-preview-trigger");
const downloadButton = document.querySelector("#download-button");
const imageDialog = document.querySelector("#image-dialog");
const imageDialogBackdrop = document.querySelector("#image-dialog-backdrop");
const dialogClose = document.querySelector("#dialog-close");
const dialogImage = document.querySelector("#dialog-image");
const dialogError = document.querySelector("#dialog-error");
let previewOpener = null;
let dialogUrl = null;
const fallbackModels = [
  { name: "birefnet-general", description: "通用场景", is_default: true },
];

function renderModels(payload) {
  modelSelect.replaceChildren();
  payload.models.forEach((model) => {
    const option = document.createElement("option");
    option.value = model.name;
    option.textContent = `${model.name} · ${model.description}`;
    modelSelect.append(option);
  });
  modelSelect.value = payload.default_model;
  const selected = payload.models.find((model) => model.name === modelSelect.value) || payload.models[0];
  if (selected) {
    modelHint.textContent = selected.description;
  }
}

async function loadModels() {
  try {
    const response = await fetch("/v1/models");
    if (!response.ok) throw new Error("模型列表加载失败");
    renderModels(await response.json());
  } catch (_) {
    renderModels({ default_model: "birefnet-general", models: fallbackModels });
    setStatus("模型列表加载失败，已使用默认模型。", "error");
  }
}

function setStatus(message, kind = "idle") {
  statusMessage.textContent = message;
  statusMessage.className = `status-message${kind === "idle" ? "" : ` is-${kind}`}`;
}

function clearObjectUrl(key) {
  if (state[key]) {
    if (dialogUrl === state[key]) closePreview();
    URL.revokeObjectURL(state[key]);
    state[key] = null;
  }
}

function setOriginalPreview(blobOrFile) {
  closePreview();
  clearObjectUrl("originalUrl");
  state.originalUrl = URL.createObjectURL(blobOrFile);
  originalPreview.src = state.originalUrl;
  originalPreviewTrigger.hidden = false;
  originalEmpty.hidden = true;
}

function clearDialogError() {
  dialogError.textContent = "";
  dialogError.hidden = true;
}

function getDialogFocusables() {
  return Array.from(imageDialog.querySelectorAll('button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'));
}

function openPreview(url, altText, opener = document.activeElement) {
  if (!url) return;
  previewOpener = opener;
  dialogUrl = url;
  clearDialogError();
  dialogImage.hidden = false;
  dialogImage.src = url;
  dialogImage.alt = altText;
  imageDialog.hidden = false;
  document.body.classList.add("dialog-open");
  dialogClose.focus();
}

function closePreview() {
  const opener = previewOpener;
  previewOpener = null;
  dialogUrl = null;
  imageDialog.hidden = true;
  document.body.classList.remove("dialog-open");
  dialogImage.removeAttribute("src");
  dialogImage.alt = "";
  clearDialogError();
  if (opener && opener.isConnected) opener.focus();
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

function getRemovalOptions() {
  const numericInputs = [
    foregroundThresholdInput,
    backgroundThresholdInput,
    erodeSizeInput,
  ];
  if (numericInputs.some((input) => input.value.trim() === "")) {
    return null;
  }
  return {
    alpha_matting: alphaMattingInput.checked,
    alpha_matting_foreground_threshold: Number(foregroundThresholdInput.value),
    alpha_matting_background_threshold: Number(backgroundThresholdInput.value),
    alpha_matting_erode_size: Number(erodeSizeInput.value),
    post_process_mask: postProcessMaskInput.checked,
  };
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
  resultPreviewTrigger.hidden = true;
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
  modelSelect.disabled = isBusy;
  removeButton.classList.toggle("is-loading", isBusy);
  removeButton.classList.toggle("is-cancel", isBusy);
  buttonLabel.textContent = isBusy ? "取消抠图" : "开始抠图";
  removeButton.setAttribute("aria-label", isBusy ? "取消抠图" : "开始抠图");
  document.querySelectorAll("#remove-form input").forEach((input) => {
    input.disabled = isBusy || (input.id === "file-input" && state.source !== "file") || (input.id === "url-input" && state.source !== "url");
  });
}

async function removeBackground(event) {
  event.preventDefault();
  if (state.requestController) {
    state.requestController.abort();
    state.requestController = null;
    setStatus("已取消本次抠图。", "idle");
    setBusy(false);
    return;
  }

  const apiKey = apiKeyInput.value.trim();
  if (!apiKey) {
    setStatus("请先填写 API Key。", "error");
    apiKeyInput.focus();
    return;
  }
  const removalOptions = getRemovalOptions();
  if (!removalOptions) {
    setStatus("高级参数不能为空。", "error");
    return;
  }

  let controller;
  let request;
  if (state.source === "file") {
    if (!state.file) {
      setStatus("请先选择一张图片。", "error");
      return;
    }
    const body = new FormData();
    body.append("file", state.file);
    body.append("model", modelSelect.value);
    body.append("alpha_matting", String(removalOptions.alpha_matting));
    body.append("alpha_matting_foreground_threshold", String(removalOptions.alpha_matting_foreground_threshold));
    body.append("alpha_matting_background_threshold", String(removalOptions.alpha_matting_background_threshold));
    body.append("alpha_matting_erode_size", String(removalOptions.alpha_matting_erode_size));
    body.append("post_process_mask", String(removalOptions.post_process_mask));
    controller = new AbortController();
    state.requestController = controller;
    request = fetch("/v1/remove-background", { method: "POST", headers: { "X-API-Key": apiKey }, body, signal: controller.signal });
  } else {
    const imageUrl = urlInput.value.trim();
    if (!imageUrl) {
      setStatus("请输入图片 URL。", "error");
      urlInput.focus();
      return;
    }
    controller = new AbortController();
    state.requestController = controller;
    request = fetch("/v1/remove-background/url", { method: "POST", headers: { "X-API-Key": apiKey, "Content-Type": "application/json" }, body: JSON.stringify({ image_url: imageUrl, model: modelSelect.value, ...removalOptions }), signal: controller.signal });
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
    resultPreviewTrigger.hidden = false;
    resultPanel.hidden = false;
    resultEmpty.hidden = true;
    setStatus("处理完成，可以下载透明 PNG。", "success");
  } catch (error) {
    if (error.name === "AbortError") {
      setStatus("已取消本次抠图。", "idle");
    } else {
      setStatus(error.message || "网络连接失败，请稍后重试。", "error");
    }
  } finally {
    if (state.requestController === controller) {
      state.requestController = null;
      setBusy(false);
    }
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
originalPreviewTrigger.addEventListener("click", () => openPreview(state.originalUrl, originalPreview.alt, originalPreviewTrigger));
resultPreviewTrigger.addEventListener("click", () => openPreview(state.resultUrl, resultPreview.alt, resultPreviewTrigger));
dialogClose.addEventListener("click", closePreview);
imageDialogBackdrop.addEventListener("click", closePreview);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !imageDialog.hidden) closePreview();
  if (event.key !== "Tab" || imageDialog.hidden) return;

  const focusables = getDialogFocusables();
  if (focusables.length === 0) return;
  const firstFocusable = focusables[0];
  const lastFocusable = focusables.at(-1);
  const outsideDialog = !imageDialog.contains(document.activeElement);
  if (event.shiftKey && (outsideDialog || document.activeElement === firstFocusable)) {
    event.preventDefault();
    lastFocusable.focus();
  } else if (!event.shiftKey && (outsideDialog || document.activeElement === lastFocusable)) {
    event.preventDefault();
    firstFocusable.focus();
  }
});
dialogImage.addEventListener("error", () => {
  if (imageDialog.hidden) return;
  dialogImage.hidden = true;
  dialogError.textContent = "图片预览加载失败，请关闭后重试。";
  dialogError.hidden = false;
});
form.addEventListener("submit", removeBackground);
modelSelect.addEventListener("change", () => {
  const selected = modelSelect.options[modelSelect.selectedIndex];
  modelHint.textContent = selected ? selected.textContent.split(" · ").slice(1).join(" · ") : "";
});
loadModels();
window.addEventListener("beforeunload", () => {
  closePreview();
  clearObjectUrl("originalUrl");
  clearObjectUrl("resultUrl");
});
