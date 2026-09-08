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

# টার্গেট চ্যানেলের ভিডিও ট্যাব URL
CHANNEL_URL = "https://www.youtube.com/@only_kdrama_bangla_explanation/videos"

# ডিরেক্টরি সেটআপ (Render পারমিশন এরর এড়াতে প্রজেক্টের ভেতরে পাথ)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HLS_DIR = os.path.join(BASE_DIR, "hls")
os.makedirs(HLS_DIR, exist_ok=True)

def get_channel_video_ids():
    """চ্যানেল থেকে সব আপলোড করা ভিডিওর আইডি সংগ্রহ করে"""
    ydl_opts = {
        'extract_flat': True,
        'quiet': True,
        'cookiefile': 'cookies.txt'
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(CHANNEL_URL, download=False)
        entries = info.get('entries', [])
        video_ids = [entry['id'] for entry in entries if entry and 'id' in entry]
        return video_ids

def get_single_stream_url(video_id):
    """একটি ভিডিওর জন্য ফ্রেশ স্ট্রিম লিংক বের করে"""
    ydl_opts = {
        'format': 'best[ext=mp4]/best',
        'quiet': True,
        'cookiefile': 'cookies.txt'
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
        return info.get('url')

def start_continuous_stream():
    """লুপ করে একটির পর একটি ভিডিও লাইভ m3u8 এ কনভার্ট করতে থাকবে"""
    while True:
        try:
            print("Fetching video list from channel...")
            video_ids = get_channel_video_ids()
            
            if not video_ids:
                print("No videos found or rate limited. Retrying in 15 seconds...")
                time.sleep(15)
                continue

            print(f"Total {len(video_ids)} videos found. Starting broadcast...")

            for vid in video_ids:
                try:
                    stream_url = get_single_stream_url(vid)
                    if not stream_url:
                        continue

                    # FFmpeg রেম্যাক্সিং (CPU ব্যবহার ১-২% এর নিচে থাকবে)
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
                        os.path.join(HLS_DIR, 'live.m3u8')
                    ]
                    process = subprocess.Popen(cmd)
                    process.wait()

                except Exception as video_err:
                    print(f"Error playing video {vid}: {video_err}")
                    time.sleep(2)

        except Exception as e:
            print(f"Error in continuous stream loop: {e}")
            time.sleep(10)

# ব্যাকগ্রাউন্ডে স্ট্রিম চালু রাখা
threading.Thread(target=start_continuous_stream, daemon=True).start()

# m3u8 এবং .ts ফাইল সার্ভ করার এন্ডপয়েন্ট
app.mount("/hls", StaticFiles(directory=HLS_DIR), name="hls")

@app.get("/")
def health_check():
    return {"status": "running", "stream_url": "/hls/live.m3u8"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
