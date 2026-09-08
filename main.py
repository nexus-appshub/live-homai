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
os.makedirs(HLS_DIR, exist_ok=True)

STREAM_STATUS = {"state": "Initializing", "current_video": None, "last_error": None}
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

# SSL সার্টিফিকেট এরর এড়াতে কনটেক্সট
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# দ্রুতগতির Piped ও Invidious স্ট্রিমিং API তালিকা
RESOLVER_ENDPOINTS = [
    {"type": "piped", "url": "https://api.piped.private.coffee/streams/{id}"},
    {"type": "piped", "url": "https://pipedapi.kavin.rocks/streams/{id}"},
    {"type": "piped", "url": "https://piped-api.garudalinux.org/streams/{id}"},
    {"type": "piped", "url": "https://pipedapi.leptons.xyz/streams/{id}"},
    {"type": "invidious", "url": "https://inv.nadeko.net/api/v1/videos/{id}"},
    {"type": "invidious", "url": "https://invidious.nerdvpn.de/api/v1/videos/{id}"},
    {"type": "invidious", "url": "https://yewtu.be/api/v1/videos/{id}"}
]

def keep_alive_ping():
    """Render ফ্রি টায়ার স্লিপ রোধে সেলফ-পিং"""
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
    """চ্যানেলের সব ভিডিওর আইডি সংগ্রহ"""
    opts = {'quiet': True, 'extract_flat': True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(CHANNEL_URL, download=False)
        return [entry['id'] for entry in info.get('entries', []) if entry and 'id' in entry]

def get_stream_url(video_id):
    """Piped এবং Invidious API দিয়ে বট-ব্লক ছাড়া সরাসরি স্ট্রিম লিংক আনা"""
    for endpoint in RESOLVER_ENDPOINTS:
        api_url = endpoint["url"].format(id=video_id)
        try:
            req = urllib.request.Request(api_url, headers={'User-Agent': USER_AGENT})
            with urllib.request.urlopen(req, timeout=6, context=SSL_CTX) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                # ১. Piped API ফরম্যাট পার্সিং (ভিডিও + অডিও মার্জড)
                if endpoint["type"] == "piped":
                    streams = data.get("videoStreams", [])
                    # অডিও সহ পূর্ণ MP4 খোঁজা
                    for s in streams:
                        if not s.get("videoOnly", True) and s.get("url"):
                            return s["url"]
                    # বিকল্প: প্রথম ভিডিও স্ট্রিম
                    if streams and streams[0].get("url"):
                        return streams[0]["url"]

                # ২. Invidious API ফরম্যাট পার্সিং
                elif endpoint["type"] == "invidious":
                    formats = data.get("formatStreams", [])
                    if formats and formats[-1].get("url"):
                        return formats[-1]["url"]
                    for fmt in data.get("adaptiveFormats", []):
                        if fmt.get("type", "").startswith("video") and fmt.get("url"):
                            return fmt["url"]

        except Exception:
            continue
            
    return None

def start_continuous_stream():
    """লাইভ ব্রডকাস্ট লুপ"""
    global STREAM_STATUS
    m3u8_path = os.path.join(HLS_DIR, 'live.m3u8')
    
    while True:
        try:
            STREAM_STATUS["state"] = "Fetching videos"
            video_ids = get_channel_video_ids()
            
            if not video_ids:
                STREAM_STATUS["last_error"] = "No videos found. Retrying in 15s..."
                time.sleep(15)
                continue

            for vid in video_ids:
                try:
                    STREAM_STATUS["current_video"] = vid
                    STREAM_STATUS["state"] = f"Resolving stream URL for {vid}"
                    stream_url = get_stream_url(vid)
                    
                    if not stream_url:
                        STREAM_STATUS["last_error"] = f"Resolvers failed for {vid}, skipping..."
                        time.sleep(2)
                        continue

                    STREAM_STATUS["state"] = f"Streaming {vid}"
                    STREAM_STATUS["last_error"] = None

                    # FFmpeg রেম্যাক্সিং (CPU ও RAM ব্যবহার সর্বনিম্ন থাকবে)
                    cmd = [
                        'ffmpeg',
                        '-user_agent', USER_AGENT,
                        '-re',
                        '-i', stream_url,
                        '-c:v', 'copy',
                        '-c:a', 'aac',
                        '-b:a', '128k',
                        '-f', 'hls',
                        '-hls_time', '4',
                        '-hls_list_size', '6',
                        '-hls_flags', 'delete_segments+append_list',
                        m3u8_path
                    ]
                    
                    process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
        raise HTTPException(status_code=503, detail="Stream is preparing, please wait a moment...")
    return FileResponse(file_path)

@app.get("/")
def index():
    return {
        "server": "online",
        "stream_info": STREAM_STATUS,
        "stream_url": "/hls/live.m3u8"
    }

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
