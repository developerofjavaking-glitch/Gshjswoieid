"""
Aryan Media Downloader — Backend API
Adapts the original CLI script's yt-dlp logic into a small Flask API
that the index.html frontend calls.

Run:
    pip install flask flask-cors yt-dlp
    python main.py
Then open http://localhost:5000 in your browser.
"""

import os
import re
import shutil
import tempfile
import uuid

from flask import Flask, request, jsonify, send_file, after_this_request
from flask_cors import CORS
import yt_dlp

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)

DOWNLOAD_ROOT = os.path.join(tempfile.gettempdir(), "aryan_downloads")
os.makedirs(DOWNLOAD_ROOT, exist_ok=True)


def get_ffmpeg_binary():
    path = shutil.which("ffmpeg")
    if path:
        return path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


FFMPEG_PATH = get_ffmpeg_binary()


def safe_filename(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    return name[:120] if len(name) > 120 else name


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/api/info", methods=["POST"])
def api_info():
    data = request.get_json(force=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    if FFMPEG_PATH:
        ydl_opts["ffmpeg_location"] = FFMPEG_PATH

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        return jsonify({"error": str(e)}), 422

    return jsonify({
        "title": info.get("title", "Unknown Title"),
        "uploader": info.get("uploader") or info.get("channel") or "Unknown Creator",
        "duration_string": info.get("duration_string", "N/A"),
        "view_count": info.get("view_count"),
        "thumbnail": info.get("thumbnail"),
    })


@app.route("/api/download", methods=["POST"])
def api_download():
    data = request.get_json(force=True) or {}
    url = (data.get("url") or "").strip()
    mode = data.get("mode", "video")
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    job_id = str(uuid.uuid4())
    out_dir = os.path.join(DOWNLOAD_ROOT, job_id)
    os.makedirs(out_dir, exist_ok=True)

    ydl_opts = {
        "outtmpl": os.path.join(out_dir, "%(title)s.%(ext)s"),
        "windowsfilenames": True,
        "quiet": True,
        "no_warnings": True,
    }

    if FFMPEG_PATH:
        ydl_opts["ffmpeg_location"] = FFMPEG_PATH
        if mode == "audio":
            ydl_opts.update({
                "format": "bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "320",
                }],
            })
        else:
            ydl_opts["format"] = (
                "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/"
                "best[ext=mp4]/best/bestvideo/bestaudio"
            )
    else:
        ydl_opts["format"] = "bestaudio/best" if mode == "audio" else "best/bestvideo/bestaudio"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        shutil.rmtree(out_dir, ignore_errors=True)
        return jsonify({"error": str(e)}), 500

    files = os.listdir(out_dir)
    if not files:
        shutil.rmtree(out_dir, ignore_errors=True)
        return jsonify({"error": "No file was produced"}), 500

    file_path = os.path.join(out_dir, files[0])

    @after_this_request
    def cleanup(response):
        shutil.rmtree(out_dir, ignore_errors=True)
        return response

    return send_file(file_path, as_attachment=True, download_name=safe_filename(files[0]))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
