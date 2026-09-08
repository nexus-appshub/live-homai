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

# আপনার টার্গেট প্লেলিস্ট বা চ্যানেল লিংক
PLAYLIST_URL = "https://www.youtube.com/playlist?list=YOUR_PLAYLIST_ID"
HLS_DIR = "/app/hls"

def get_playlist_stream_urls():
    """প্লেলিস্ট থেকে সব ভিডিওর ডিরেক্ট স্ট্রিমিং লিংক বের করে আনে"""
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
    """ব্যাকগ্রাউন্ডে একটার পর একটা ভিডিও HLS ফরম্যাটে রেন্ডার করতে থাকবে"""
    os.makedirs(HLS_DIR, exist_ok=True)
    
    while True:
        try:
            stream_urls = get_playlist_stream_urls()
            if not stream_urls:
                time.sleep(10)
                continue

            for url in stream_urls:
                # FFmpeg দিয়ে রেন্ডার না করে রেম্যাক্স (copy) করা হচ্ছে, CPU ব্যবহার ১-৫% এর নিচে থাকবে
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
                    f'{HLS_DIR}/live.m3u8'
                ]
                process = subprocess.Popen(cmd)
                process.wait()

        except Exception as e:
            print(f"Error in stream: {e}")
            time.sleep(5)

# ব্যাকগ্রাউন্ডে স্ট্রিম চালু করা
threading.Thread(target=start_continuous_stream, daemon=True).start()

# m3u8 এবং .ts ফাইলগুলো সার্ভ করার পাথ
app.mount("/hls", StaticFiles(directory=HLS_DIR), name="hls")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
