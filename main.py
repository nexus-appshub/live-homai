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

# স্বয়ংক্রিয়ভাবে Render-এ FFmpeg লোড করা
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

# 403 ব্লক বাইপাস করার জন্য অ্যান্ড্রয়েড ক্লায়েন্ট কনফিগারেশন
YDL_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'format': 'best[ext=mp4]/best/b',
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'ios']
        }
    }
}

if os.path.exists(os.path.join(BASE_DIR, "cookies.txt")):
    YDL_OPTS['cookiefile'] = os.path.join(BASE_DIR, "cookies.txt")

# ১. সার্ভার স্লিপ রোধ করতে সেলফ-পিং
def keep_alive_ping():
    app_url = os.environ.get("RENDER_EXTERNAL_URL", "https://live-homai.onrender.com")
    time.sleep(30)
    while True:
        try:
            req = urllib.request.Request(app_url, headers={'User-Agent': 'KeepAlive/1.0'})
            urllib.request.urlopen(req, timeout=10)
        except Exception:
            pass
        time.sleep(600)  # প্রতি ১০ মিনিটে পিং

# ২. ভিডিও আইডি ও স্ট্রিম লিংক সংগ্রহ
def get_channel_video_ids():
    opts = YDL_OPTS.copy()
    opts['extract_flat'] = True
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(CHANNEL_URL, download=False)
        return [entry['id'] for entry in info.get('entries', []) if entry and 'id' in entry]

def get_single_stream_url(video_id):
    with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
        return info.get('url')

# ৩. একটানা লাইভ HLS স্ট্রিম তৈরি
def start_continuous_stream():
    m3u8_path = os.path.join(HLS_DIR, 'live.m3u8')
    while True:
        try:
            print("[Stream] Fetching videos from channel...")
            video_ids = get_channel_video_ids()
            if not video_ids:
                time.sleep(15)
                continue

            print(f"[Stream] Found {len(video_ids)} videos. Starting stream...")
            for vid in video_ids:
                try:
                    stream_url = get_single_stream_url(vid)
                    if not stream_url:
                        continue

                    # FFmpeg দিয়ে রেম্যাক্স করে HLS তৈরি
                    cmd = [
                        'ffmpeg',
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
                    process = subprocess.Popen(cmd)
                    process.wait()

                except Exception as err:
                    print(f"[Stream Error] Video {vid}: {err}")
                    time.sleep(2)

        except Exception as e:
            print(f"[Loop Error]: {e}")
            time.sleep(10)

# থ্রেড চালু
threading.Thread(target=keep_alive_ping, daemon=True).start()
threading.Thread(target=start_continuous_stream, daemon=True).start()

# ৪. নিরাপদ HLS ফাইল সার্ভিং এন্ডপয়েন্ট
@app.get("/hls/{filename}")
def serve_hls(filename: str):
    file_path = os.path.join(HLS_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=503, detail="Stream is preparing, please wait a few seconds and refresh...")
    return FileResponse(file_path)

@app.get("/")
def index():
    return {
        "status": "online",
        "stream_url": "/hls/live.m3u8"
    }

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
