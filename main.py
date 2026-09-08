import os
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
USER_AGENT = "Mozilla/5.0 (SMART-TV; Linux; Tizen 5.0) AppleWebKit/538.1 (KHTML, like Gecko) Version/5.0 TV Safari/538.1"

# কুকি ফাইল পাথ চেক
COOKIE_FILE = None
for path in ["cookies.txt", os.path.join(BASE_DIR, "cookies.txt"), "/etc/secrets/cookies.txt"]:
    if os.path.exists(path):
        COOKIE_FILE = path
        break

def get_ydl_options():
    """Smart TV ক্লায়েন্ট কনফিগারেশন যা ক্লাউড সার্ভারের বট ব্লক বাইপাস করে"""
    opts = {
        'quiet': True,
        'no_warnings': True,
        'format': 'best',
        'extractor_args': {
            'youtube': {
                'player_client': ['tv_embedded', 'tv']
            }
        }
    }
    if COOKIE_FILE:
        opts['cookiefile'] = COOKIE_FILE
    return opts

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

def get_channel_video_ids():
    opts = get_ydl_options()
    opts['extract_flat'] = True
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(CHANNEL_URL, download=False)
        return [entry['id'] for entry in info.get('entries', []) if entry and 'id' in entry]

def get_single_stream_url(video_id):
    opts = get_ydl_options()
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
        return info.get('url')

def start_continuous_stream():
    global STREAM_STATUS
    m3u8_path = os.path.join(HLS_DIR, 'live.m3u8')
    
    while True:
        try:
            STREAM_STATUS["state"] = "Fetching videos"
            video_ids = get_channel_video_ids()
            if not video_ids:
                STREAM_STATUS["last_error"] = "No videos returned. Retrying in 15 seconds..."
                time.sleep(15)
                continue

            for vid in video_ids:
                try:
                    STREAM_STATUS["current_video"] = vid
                    STREAM_STATUS["state"] = f"Extracting stream URL for {vid}"
                    stream_url = get_single_stream_url(vid)
                    
                    if not stream_url:
                        continue

                    STREAM_STATUS["state"] = f"Streaming {vid}"
                    STREAM_STATUS["last_error"] = None

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
                    
                    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    _, stderr = process.communicate()
                    
                    if process.returncode != 0:
                        STREAM_STATUS["last_error"] = stderr.decode('utf-8', errors='ignore')[-300:]

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
        "cookie_loaded": COOKIE_FILE is not None,
        "stream_info": STREAM_STATUS,
        "stream_url": "/hls/live.m3u8"
    }

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
