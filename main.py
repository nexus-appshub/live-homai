import os
import time
import threading
import subprocess
import yt_dlp
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

PLAYLIST_URL = "https://www.youtube.com/playlist?list=YOUR_PLAYLIST_ID"

# রুট /app এর বদলে বর্তমান প্রজেক্ট ডিরেক্টরির ভেতরে ফোল্ডার পাথ
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HLS_DIR = os.path.join(BASE_DIR, "hls")

# সার্ভার স্টার্ট হওয়ার আগেই ফোল্ডারটি নিশ্চিতভাবে তৈরি করা হচ্ছে
os.makedirs(HLS_DIR, exist_ok=True)

def get_playlist_stream_urls():
    ydl_opts = {
        'format': 'best[ext=mp4]/best',
        'quiet': True,
        'cookiefile': 'cookies.txt',
        'extract_flat': False
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(PLAYLIST_URL, download=False)
        urls = []
        for entry in info.get('entries', []):
            if entry and 'url' in entry:
                urls.append(entry['url'])
        return urls

def start_continuous_stream():
    while True:
        try:
            stream_urls = get_playlist_stream_urls()
            if not stream_urls:
                time.sleep(10)
                continue

            for url in stream_urls:
                cmd = [
                    'ffmpeg',
                    '-re',
                    '-i', url,
                    '-c:v', 'copy',
                    '-c:a', 'aac',
                    '-b:a', '128k',
                    '-f', 'hls',
                    '-hls_time', '4',
                    '-hls_list_size', '5',
                    '-hls_flags', 'delete_segments+append_list',
                    os.path.join(HLS_DIR, 'live.m3u8')
                ]
                process = subprocess.Popen(cmd)
                process.wait()

        except Exception as e:
            print(f"Error in stream: {e}")
            time.sleep(5)

# ব্যাকগ্রাউন্ড থ্রেড
threading.Thread(target=start_continuous_stream, daemon=True).start()

# m3u8 মাউন্ট
app.mount("/hls", StaticFiles(directory=HLS_DIR), name="hls")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
