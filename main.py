import os
import ssl
import time
import json
import threading
import subprocess
import urllib.request
import yt_dlp
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

import static_ffmpeg
static_ffmpeg.add_paths()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

CHANNEL_URL = "https://www.youtube.com/@only_kdrama_bangla_explanation/videos"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HLS_DIR = os.path.join(BASE_DIR, "hls")
LOG_FILE = os.path.join(BASE_DIR, "ffmpeg.log")
os.makedirs(HLS_DIR, exist_ok=True)

STREAM_STATUS = {"state": "Initializing", "current_video": None, "last_error": None, "active_segments": 0}
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

RESOLVER_APIS = [
    {"type": "piped", "url": "https://api.piped.private.coffee/streams/{id}"},
    {"type": "piped", "url": "https://piped-api.garudalinux.org/streams/{id}"},
    {"type": "piped", "url": "https://pipedapi.kavin.rocks/streams/{id}"},
    {"type": "invidious", "url": "https://inv.nadeko.net/api/v1/videos/{id}"},
    {"type": "invidious", "url": "https://invidious.nerdvpn.de/api/v1/videos/{id}"},
    {"type": "invidious", "url": "https://yewtu.be/api/v1/videos/{id}"}
]

def keep_alive_ping():
    """Render স্লিপ প্রতিরোধে সেলফ-পিং"""
    app_url = os.environ.get("RENDER_EXTERNAL_URL", "https://live-homai.onrender.com")
    time.sleep(30)
    while True:
        try:
            req = urllib.request.Request(app_url, headers={'User-Agent': 'KeepAlive/1.0'})
            urllib.request.urlopen(req, timeout=10, context=SSL_CTX)
        except Exception:
            pass
        time.sleep(600)

def get_channel_video_ids():
    opts = {'quiet': True, 'extract_flat': True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(CHANNEL_URL, download=False)
        return [entry['id'] for entry in info.get('entries', []) if entry and 'id' in entry]

def verify_and_get_video_url(url_candidate):
    """লিংকটি আসলেই আসল MP4 ভিডিও ফাইল কি না তা প্রথম কয়েক বাইট পড়ে যাচাই করে"""
    try:
        req = urllib.request.Request(
            url_candidate,
            headers={'User-Agent': USER_AGENT, 'Range': 'bytes=0-1024'}
        )
        with urllib.request.urlopen(req, timeout=5, context=SSL_CTX) as resp:
            content_type = resp.headers.get("Content-Type", "").lower()
            if "html" in content_type or "text" in content_type:
                return False
            data = resp.read(1024)
            # MP4/WebM ভিডিও হেডারের উপস্থিতি যাচাই
            if b'ftyp' in data[:64] or data[:4] == b'\x1a\x45\xdf\xa3':
                return True
    except Exception:
        pass
    return False

def get_stream_url(video_id):
    """Piped এবং Invidious API থেকে নিশ্চিত সচল ভিডিও লিংক আনা"""
    for endpoint in RESOLVER_APIS:
        api_url = endpoint["url"].format(id=video_id)
        try:
            req = urllib.request.Request(api_url, headers={'User-Agent': USER_AGENT})
            with urllib.request.urlopen(req, timeout=5, context=SSL_CTX) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                candidates = []
                if endpoint["type"] == "piped":
                    for s in data.get("videoStreams", []):
                        if not s.get("videoOnly", False) and s.get("url"):
                            candidates.append(s["url"])
                    for s in data.get("videoStreams", []):
                        if s.get("url"):
                            candidates.append(s["url"])

                elif endpoint["type"] == "invidious":
                    for s in data.get("formatStreams", []):
                        if s.get("url"):
                            candidates.append(s["url"])
                
                for cand in candidates:
                    if verify_and_get_video_url(cand):
                        return cand
        except Exception:
            continue
    return None

def start_continuous_stream():
    global STREAM_STATUS
    m3u8_path = os.path.join(HLS_DIR, 'live.m3u8')
    segment_pattern = os.path.join(HLS_DIR, 'segment_%03d.ts')
    
    while True:
        try:
            STREAM_STATUS["state"] = "Fetching videos"
            video_ids = get_channel_video_ids()
            
            if not video_ids:
                STREAM_STATUS["last_error"] = "No videos found. Retrying..."
                time.sleep(15)
                continue

            for vid in video_ids:
                try:
                    STREAM_STATUS["current_video"] = vid
                    STREAM_STATUS["state"] = f"Resolving stream URL for {vid}"
                    stream_url = get_stream_url(vid)
                    
                    if not stream_url:
                        STREAM_STATUS["last_error"] = f"No playable stream for {vid}, skipping..."
                        time.sleep(2)
                        continue

                    STREAM_STATUS["state"] = f"Streaming {vid}"
                    STREAM_STATUS["last_error"] = None

                    # মেমোরি ডেডলক এড়াতে লগ ফাইলে রিডাইরেক্ট
                    with open(LOG_FILE, "w") as log_output:
                        cmd = [
                            'ffmpeg',
                            '-user_agent', USER_AGENT,
                            '-reconnect', '1',
                            '-reconnect_streamed', '1',
                            '-reconnect_delay_max', '5',
                            '-re',
                            '-i', stream_url,
                            '-c:v', 'copy',
                            '-c:a', 'aac',
                            '-b:a', '128k',
                            '-f', 'hls',
                            '-hls_time', '2',
                            '-hls_list_size', '5',
                            '-hls_flags', 'delete_segments+append_list',
                            '-hls_segment_filename', segment_pattern,
                            m3u8_path
                        ]
                        process = subprocess.Popen(cmd, stdout=log_output, stderr=log_output)
                        process.wait()

                except Exception as err:
                    STREAM_STATUS["last_error"] = str(err)
                    time.sleep(2)

        except Exception as e:
            STREAM_STATUS["last_error"] = str(e)
            time.sleep(10)

threading.Thread(target=keep_alive_ping, daemon=True).start()
threading.Thread(target=start_continuous_stream, daemon=True).start()

@app.get("/hls/{filename}")
def serve_hls(filename: str):
    file_path = os.path.join(HLS_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=503, detail="Stream is preparing, please wait a few seconds and refresh...")
    return FileResponse(file_path)

@app.get("/")
def index():
    # ডিরেক্টরিতে কয়টি ফাইল তৈরি হয়েছে তা দেখা
    files = [f for f in os.listdir(HLS_DIR) if f.endswith('.ts') or f.endswith('.m3u8')] if os.path.exists(HLS_DIR) else []
    return {
        "server": "online",
        "stream_info": STREAM_STATUS,
        "hls_files_ready": files,
        "stream_url": "/hls/live.m3u8"
    }

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
