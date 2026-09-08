import os
import ssl
import time
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

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# বর্তমানে সচল ও নির্ভরযোগ্য প্রক্সি নোড তালিকা
LIVE_PROXY_INSTANCES = [
    "https://iv.melmac.space",
    "https://invidious.drgns.space",
    "https://invidious.flokinet.to",
    "https://invidious.projectsegfau.lt",
    "https://invidious.privacydev.net",
    "https://yt.artemislena.eu",
    "https://inv.tux.pizza"
]

def keep_alive_ping():
    """Render ফ্রি টায়ার স্লিপ মোড প্রতিরোধ"""
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

def get_working_stream_url(video_id):
    """সচল প্রক্সি থেকে ভিডিও স্ট্রিম যাচাই করে নিশ্চিত লিংক বের করা"""
    # itag 22 (720p) অথবা itag 18 (360p)
    for itag in [22, 18]:
        for base in LIVE_PROXY_INSTANCES:
            # local=true ইউটিউব ডেটাসেন্টার IP ব্লক সম্পূর্ণরূপে বাইপাস করে
            test_url = f"{base}/latest_version?id={video_id}&itag={itag}&local=true"
            try:
                req = urllib.request.Request(
                    test_url,
                    headers={'User-Agent': USER_AGENT, 'Range': 'bytes=0-2048'}
                )
                with urllib.request.urlopen(req, timeout=4, context=SSL_CTX) as resp:
                    if resp.status in (200, 206):
                        return test_url
            except Exception:
                continue
    return None

def start_continuous_stream():
    global STREAM_STATUS
    m3u8_path = os.path.join(HLS_DIR, 'live.m3u8')
    
    while True:
        try:
            STREAM_STATUS["state"] = "Fetching videos"
            video_ids = get_channel_video_ids()
            
            if not video_ids:
                STREAM_STATUS["last_error"] = "No videos found. Retrying in 15 seconds..."
                time.sleep(15)
                continue

            for vid in video_ids:
                try:
                    STREAM_STATUS["current_video"] = vid
                    STREAM_STATUS["state"] = f"Connecting stream for {vid}"
                    stream_url = get_working_stream_url(vid)
                    
                    if not stream_url:
                        STREAM_STATUS["last_error"] = f"No proxy nodes available for {vid}, trying next..."
                        time.sleep(2)
                        continue

                    STREAM_STATUS["state"] = f"Streaming {vid}"
                    STREAM_STATUS["last_error"] = None

                    # FFmpeg HLS জেনারেটর (অটো-রিকানেক্ট ও লো-রিসোর্স কনফিগ)
                    cmd = [
                        'ffmpeg',
                        '-user_agent', USER_AGENT,
                        '-reconnect', '1',
                        '-reconnect_at_eof', '1',
                        '-reconnect_streamed', '1',
                        '-reconnect_delay_max', '5',
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
