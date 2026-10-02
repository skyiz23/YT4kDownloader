from flask import Flask, render_template, request, jsonify, send_file
import os
import re
import subprocess
import threading
import time
import uuid

import yt_dlp

app = Flask(__name__)
DOWNLOAD_DIR = os.path.abspath("downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

FILE_TTL_SECONDS = int(os.getenv("FILE_TTL_SECONDS", "1800"))
jobs = {}

QUALITY_MAP = {
    "360": "bestvideo[height<=360]+bestaudio/best[height<=360]",
    "720": "bestvideo[height<=720]+bestaudio/best[height<=720]",
    "1080": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
    "1440": "bestvideo[height<=1440]+bestaudio/best[height<=1440]",
    "2160": "bestvideo[height<=2160]+bestaudio/best[height<=2160]",
}


# YouTube extraction currently requires yt-dlp's external JS challenge solver.
# Deno is installed by the Dockerfile and enabled explicitly here.
YT_DLP_COMMON = {
    "js_runtimes": {"deno": {}},
    "remote_components": {"ejs": ["npm"]},
    # BgUtils supplies YouTube Proof-of-Origin tokens on Render/cloud IPs.
    "extractor_args": {
        "youtubepot-bgutilhttp": {
            "base_url": [os.getenv("YTDL_POT_PROVIDER_URL", "http://127.0.0.1:4416")]
        }
    },
    "retries": 5,
    "fragment_retries": 5,
    "socket_timeout": 30,
}


def make_yt_options(**extra):
    options = dict(YT_DLP_COMMON)
    options.update(extra)
    return options


def cleanup_old_files():
    now = time.time()
    for name in os.listdir(DOWNLOAD_DIR):
        path = os.path.join(DOWNLOAD_DIR, name)
        try:
            if os.path.isfile(path) and now - os.path.getmtime(path) > FILE_TTL_SECONDS:
                os.remove(path)
        except OSError:
            pass


def safe_filename(name, fallback="download"):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name or "")
    name = re.sub(r"\s+", " ", name).strip(" .")
    return (name[:150] or fallback)


def base_job():
    return {
        "status": "starting",
        "phase": "Preparing",
        "progress": 0,
        "downloaded_bytes": 0,
        "total_bytes": 0,
        "speed": 0,
        "eta": None,
        "processed_bytes": 0,
        "total_processed_bytes": 0,
        "filename": None,
        "error": None,
        "title": None,
        "mode": "video",
    }


def update_job(job_id, **values):
    jobs[job_id].update(values)


def run_ffmpeg(job_id, source, output, mode, duration=None):
    """Encode to a Premiere-friendly format and report progress."""
    if mode == "audio":
        command = [
            "ffmpeg", "-y", "-i", source,
            "-vn", "-c:a", "libmp3lame", "-b:a", "192k",
            "-progress", "pipe:1", "-nostats", output,
        ]
    else:
        # H.264 + AAC in MP4 is broadly compatible with Premiere and other editors.
        command = [
            "ffmpeg", "-y", "-i", source,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            "-progress", "pipe:1", "-nostats", output,
        ]

    update_job(job_id, status="processing", phase="Optimizing for Premiere" if mode == "video" else "Converting audio", progress=70)

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    out_time_us = 0
    speed_value = 0
    for line in process.stdout:
        line = line.strip()
        if line.startswith("out_time_us="):
            try:
                out_time_us = max(0, int(line.split("=", 1)[1]))
            except ValueError:
                pass
        elif line.startswith("speed="):
            raw = line.split("=", 1)[1].strip().rstrip("x")
            try:
                speed_value = float(raw)
            except ValueError:
                speed_value = 0

        if duration and duration > 0:
            ratio = min(1.0, out_time_us / 1_000_000 / duration)
            overall = 70 + ratio * 30
            remaining = max(0, duration - out_time_us / 1_000_000)
            eta = int(remaining / speed_value) if speed_value > 0 else None
            update_job(job_id, progress=round(overall, 1), eta=eta, speed=speed_value)

    return_code = process.wait()
    if return_code != 0:
        raise RuntimeError("FFmpeg could not convert the file into a compatible format.")

    update_job(job_id, progress=100, eta=0)


def download_job(job_id, url, quality, mode):
    cleanup_old_files()
    update_job(job_id, status="starting", phase="Reading video information")

    source = None
    try:
        if mode == "audio":
            format_selector = "bestaudio/best"
        else:
            format_selector = QUALITY_MAP.get(quality, QUALITY_MAP["1080"])

        def hook(d):
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                current = d.get("downloaded_bytes", 0)
                speed = d.get("speed") or 0
                eta = d.get("eta")
                pct = (current / total * 70) if total else 0
                update_job(
                    job_id,
                    status="downloading",
                    phase="Downloading",
                    progress=round(min(70, pct), 1),
                    downloaded_bytes=current,
                    total_bytes=total,
                    speed=speed,
                    eta=eta,
                )
            elif d["status"] == "finished":
                update_job(
                    job_id,
                    progress=70,
                    downloaded_bytes=d.get("downloaded_bytes", 0),
                    total_bytes=d.get("total_bytes") or d.get("total_bytes_estimate") or 0,
                    status="processing",
                    phase="Preparing conversion",
                    eta=None,
                )

        source_template = os.path.join(DOWNLOAD_DIR, f"{job_id}.%(ext)s")
        options = make_yt_options(
            format=format_selector,
            outtmpl=source_template,
            noplaylist=True,
            progress_hooks=[hook],
            quiet=True,
            no_warnings=True,
            restrictfilenames=True,
            merge_output_format="mp4" if mode == "video" else None,
        )
        options = {k: v for k, v in options.items() if v is not None}

        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "download")
            duration = info.get("duration") or 0

        candidates = [
            os.path.join(DOWNLOAD_DIR, x)
            for x in os.listdir(DOWNLOAD_DIR)
            if x.startswith(job_id + ".") and os.path.isfile(os.path.join(DOWNLOAD_DIR, x))
        ]
        # Never treat the final file as the source if a retry happens.
        candidates = [p for p in candidates if not p.endswith(".final.mp4") and not p.endswith(".final.mp3")]
        if not candidates:
            raise RuntimeError("The downloaded source file could not be found.")
        source = max(candidates, key=os.path.getsize)

        final_ext = "mp3" if mode == "audio" else "mp4"
        final_path = os.path.join(DOWNLOAD_DIR, f"{job_id}.final.{final_ext}")
        run_ffmpeg(job_id, source, final_path, mode, duration=duration)

        try:
            os.remove(source)
        except OSError:
            pass

        update_job(
            job_id,
            status="complete",
            phase="Complete",
            progress=100,
            filename=final_path,
            title=title,
            eta=0,
        )
    except Exception as exc:
        if source and os.path.exists(source):
            try:
                os.remove(source)
            except OSError:
                pass
        update_job(job_id, status="error", phase="Failed", error=str(exc))


@app.route("/")
def index():
    return render_template("index.html")


@app.post("/api/info")
def info():
    data = request.get_json(silent=True) or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "Please enter a video URL."}), 400

    try:
        opts = make_yt_options(
            quiet=True,
            no_warnings=True,
            noplaylist=True,
            skip_download=True,
        )
        with yt_dlp.YoutubeDL(opts) as ydl:
            result = ydl.extract_info(url, download=False)
        return jsonify({
            "title": result.get("title"),
            "thumbnail": result.get("thumbnail"),
            "duration": result.get("duration"),
            "uploader": result.get("uploader"),
        })
    except Exception:
        return jsonify({"error": "Could not read this URL. Check the link and try again."}), 400


@app.post("/api/download")
def start_download():
    data = request.get_json(silent=True) or {}
    url = data.get("url", "").strip()
    quality = str(data.get("quality", "1080"))
    mode = str(data.get("mode", "video"))

    if not url:
        return jsonify({"error": "Please enter a video URL."}), 400
    if mode not in {"video", "audio"}:
        return jsonify({"error": "Unsupported download type."}), 400
    if mode == "video" and quality not in QUALITY_MAP:
        return jsonify({"error": "Unsupported video quality."}), 400

    job_id = uuid.uuid4().hex
    jobs[job_id] = base_job()
    jobs[job_id]["mode"] = mode

    threading.Thread(
        target=download_job,
        args=(job_id, url, quality, mode),
        daemon=True,
    ).start()

    return jsonify({"job_id": job_id})


@app.get("/api/status/<job_id>")
def status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found."}), 404

    response = dict(job)
    if response.get("filename"):
        response["download_url"] = f"/api/file/{job_id}"
        response.pop("filename", None)
    return jsonify(response)


@app.get("/api/file/<job_id>")
def get_file(job_id):
    job = jobs.get(job_id)
    path = job.get("filename") if job else None
    if not path or not os.path.exists(path):
        return jsonify({"error": "File is not ready."}), 404

    ext = "mp3" if job.get("mode") == "audio" else "mp4"
    return send_file(
        path,
        as_attachment=True,
        download_name=f'{safe_filename(job.get("title", "download"))}.{ext}',
    )


if __name__ == "__main__":
    app.run(
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
    )
