const $ = (id) => document.getElementById(id);

const url = $("url");
const quality = $("quality");
const analyze = $("analyze");
const download = $("download");
const downloadAudio = $("downloadAudio");
const preview = $("preview");
const thumb = $("thumb");
const title = $("title");
const meta = $("meta");
const statusBox = $("statusBox");
const statusText = $("statusText");
const percent = $("percent");
const barFill = $("barFill");
const sizeStat = $("sizeStat");
const speedStat = $("speedStat");
const etaStat = $("etaStat");
const helperText = $("helperText");
const result = $("result");
const resultTitle = $("resultTitle");
const saveBtn = $("saveBtn");
const errorBox = $("error");
const videoControls = $("videoControls");
const audioControls = $("audioControls");
const modeButtons = document.querySelectorAll(".mode");

let mode = "video";

function showError(message) {
  errorBox.textContent = message;
  errorBox.classList.remove("hidden");
}
function clearError() {
  errorBox.classList.add("hidden");
}
function setBusy(button, busy, text) {
  button.disabled = busy;
  if (busy) {
    button.dataset.old = button.textContent;
    button.textContent = text;
  } else {
    button.textContent = button.dataset.old || button.textContent;
  }
}
function formatMB(bytes) {
  if (!bytes || bytes < 0) return "—";
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
function formatSpeed(bytesPerSec) {
  if (!bytesPerSec || bytesPerSec < 1) return "—";
  const mb = bytesPerSec / 1024 / 1024;
  return mb >= 1 ? `${mb.toFixed(1)} MB/s` : `${(bytesPerSec / 1024).toFixed(0)} KB/s`;
}
function formatETA(seconds) {
  if (seconds === null || seconds === undefined || !Number.isFinite(Number(seconds))) return "ETA —";
  seconds = Math.max(0, Math.round(Number(seconds)));
  if (seconds < 60) return `ETA ${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m < 60) return `ETA ${m}m ${s}s`;
  const h = Math.floor(m / 60);
  return `ETA ${h}h ${m % 60}m`;
}
function setMode(nextMode) {
  mode = nextMode;
  modeButtons.forEach(btn => btn.classList.toggle("active", btn.dataset.mode === mode));
  videoControls.classList.toggle("hidden", mode !== "video");
  audioControls.classList.toggle("hidden", mode !== "audio");
}

modeButtons.forEach(btn => {
  btn.onclick = () => setMode(btn.dataset.mode);
});

analyze.onclick = async () => {
  clearError();
  const value = url.value.trim();
  if (!value) return showError("Paste a video URL first.");

  setBusy(analyze, true, "Reading...");
  try {
    const res = await fetch("/api/info", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({url: value})
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Could not read URL.");

    thumb.src = data.thumbnail || "";
    title.textContent = data.title || "Untitled video";
    const duration = data.duration ? formatDuration(data.duration) : "";
    meta.textContent = [data.uploader ? `By ${data.uploader}` : "Video detected", duration].filter(Boolean).join(" • ");
    preview.classList.remove("hidden");
  } catch (e) {
    showError(e.message);
  } finally {
    setBusy(analyze, false);
  }
};

function formatDuration(seconds) {
  seconds = Math.max(0, Math.round(Number(seconds)));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

async function startDownload(button, requestedMode) {
  clearError();
  result.classList.add("hidden");

  const value = url.value.trim();
  if (!value) return showError("Paste a video URL first.");

  setBusy(button, true, "Starting...");
  statusBox.classList.remove("hidden");
  statusText.textContent = "Starting...";
  percent.textContent = "0%";
  barFill.style.width = "0%";
  sizeStat.textContent = "0 MB / —";
  speedStat.textContent = "—";
  etaStat.textContent = "ETA —";
  helperText.textContent = requestedMode === "video"
    ? "The final MP4 is encoded for broad Premiere compatibility."
    : "The audio is being converted to a widely compatible MP3.";

  try {
    const res = await fetch("/api/download", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({url: value, quality: quality.value, mode: requestedMode})
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Could not start download.");

    await poll(data.job_id, requestedMode);
  } catch (e) {
    showError(e.message);
    statusBox.classList.add("hidden");
  } finally {
    setBusy(button, false);
  }
}

download.onclick = () => startDownload(download, "video");
downloadAudio.onclick = () => startDownload(downloadAudio, "audio");

async function poll(jobId, requestedMode) {
  while (true) {
    const res = await fetch(`/api/status/${jobId}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Could not read download status.");
    if (data.status === "error") throw new Error(data.error || "Download failed.");

    const p = Number(data.progress || 0);
    percent.textContent = `${Math.round(p)}%`;
    barFill.style.width = `${Math.min(100, p)}%`;

    sizeStat.textContent = data.total_bytes
      ? `${formatMB(data.downloaded_bytes)} / ${formatMB(data.total_bytes)}`
      : `${formatMB(data.downloaded_bytes)} downloaded`;
    speedStat.textContent = formatSpeed(data.speed);
    etaStat.textContent = formatETA(data.eta);

    if (data.status === "starting") statusText.textContent = data.phase || "Preparing...";
    if (data.status === "downloading") statusText.textContent = "Downloading...";
    if (data.status === "processing") statusText.textContent = data.phase || "Processing...";

    if (data.status === "complete") {
      statusText.textContent = "Complete";
      percent.textContent = "100%";
      barFill.style.width = "100%";
      etaStat.textContent = "Done";
      speedStat.textContent = "Ready";
      resultTitle.textContent = data.title || "Your file is ready.";
      saveBtn.href = data.download_url;
      saveBtn.textContent = requestedMode === "audio" ? "Save MP3" : "Save MP4";
      result.classList.remove("hidden");
      break;
    }

    await new Promise(r => setTimeout(r, 800));
  }
}
