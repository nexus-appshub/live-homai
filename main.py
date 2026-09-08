import os
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

# পাবলিক Invidious প্রক্সি সার্ভার লিস্ট (বট ব্লকিং বাইপাস করার জন্য)
INVIDIOUS_INSTANCES = [
    "https://inv.nadeko.net",
    "https://invidious.nerdvpn.de",
    "https://yewtu.be",
    "https://invidious.private.coffee",
    "https://vid.puffyan.us"
]

# ১. সার্ভার ঘুমিয়ে পড়া রোধ করতে সেলফ-পিং
def keep_alive_ping():
    app_url = os.environ.get("RENDER_EXTERNAL_URL", "https://live-homai.onrender.com")
    time.sleep(30)
    while True:
        try:
            req = urllib.request.Request(app_url, headers={'User-Agent': 'KeepAlive/1.0'})
            urllib.request.urlopen(req, timeout=10)
        except Exception:
            pass
        time.sleep(600)

# ২. চ্যানেল থেকে ভিডিও লিস্ট সংগ্রহ (ফ্ল্যাট এক্সট্রাকশন ব্লক হয় না)
def get_channel_video_ids():
    opts = {'quiet': True, 'extract_flat': True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(CHANNEL_URL, download=False)
        return [entry['id'] for entry in info.get('entries', []) if entry and 'id' in entry]

# ৩. Invidious API দিয়ে বট-ব্লক ছাড়া সরাসরি স্ট্রিম লিংক আনা
def get_stream_url(video_id):
    for instance in INVIDIOUS_INSTANCES:
        try:
            api_url = f"{instance}/api/v1/videos/{video_id}"
            req = urllib.request.Request(api_url, headers={'User-Agent': USER_AGENT})
            with urllib.request.urlopen(req, timeout=7) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                # অডিও ও ভিডিও মার্জ করা আছে এমন MP4 স্ট্রিম খোঁজা
                formats = data.get("formatStreams", [])
                if formats:
                    return formats[-1].get("url")
                
                # বিকল্প ফরম্যাট
                for fmt in data.get("adaptiveFormats", []):
                    if fmt.get("type", "").startswith("video") and "url" in fmt:
                        return fmt["url"]
        except Exception:
            continue
            
    # ব্যাকআপ হিসেবে yt-dlp ট্রাই করবে
    try:
        opts = {'quiet': True, 'format': 'best'}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            return info.get('url')
    except Exception as e:
        STREAM_STATUS["last_error"] = str(e)
        return None

# ৪. একটানা লাইভ HLS ব্রডকাস্ট লুপ
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
                    STREAM_STATUS["state"] = f"Resolving stream URL for {vid}"
                    stream_url = get_stream_url(vid)
                    
                    if not stream_url:
                        continue

                    STREAM_STATUS["state"] = f"Streaming {vid}"
                    STREAM_STATUS["last_error"] = None

                    # FFmpeg রেম্যাক্সিং (ল্যাগ ছাড়া দ্রুত লাইভ স্ট্রিম তৈরি)
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

# থ্রেড চালু
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
