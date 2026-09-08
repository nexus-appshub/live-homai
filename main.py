import os
import time
import threading
import subprocess
import urllib.request
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

CHANNEL_URL = "https://www.youtube.com/@only_kdrama_bangla_explanation/videos"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HLS_DIR = os.path.join(BASE_DIR, "hls")
os.makedirs(HLS_DIR, exist_ok=True)

# 403 Forbidden ও n-challenge এড়াতে অ্যান্ড্রয়েড ক্লায়েন্ট অপশন
YDL_BASE_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'ios']
        }
    }
}

# --- ১. স্বয়ংক্রিয় সেলফ-পিং ফাংশন (Render Sleep রোধ করতে) ---
def keep_alive_ping():
    """প্রতি ১০ মিনিট পর পর রেন্ডার ইউআরএলে পিং পাঠিয়ে সার্ভার লাইভ রাখবে"""
    # Render নিজে থেকেই RENDER_EXTERNAL_URL ভেরিয়েবল প্রদান করে
    app_url = os.environ.get("RENDER_EXTERNAL_URL", "https://live-homai.onrender.com")
    
    # সার্ভার পুরোপুরি বুট হওয়ার জন্য শুরুতে ৩০ সেকেন্ড অপেক্ষা
    time.sleep(30)
    print(f"[Keep-Alive] Self-pinger activated for: {app_url}")
    
    while True:
        try:
            req = urllib.request.Request(
                app_url,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) KeepAlive/1.0'}
            )
            with urllib.request.urlopen(req, timeout=15) as response:
                print(f"[Keep-Alive] Ping successful! Status: {response.status}")
        except Exception as e:
            print(f"[Keep-Alive] Ping error: {e}")
            
        # প্রতি ১০ মিনিট (৬০০ সেকেন্ড) পর পর পিং করবে
        time.sleep(600)

# --- ২. ইউটিউব ভিডিও হ্যান্ডলার ---
def get_channel_video_ids():
    opts = YDL_BASE_OPTS.copy()
    opts['extract_flat'] = True
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(CHANNEL_URL, download=False)
        entries = info.get('entries', [])
        return [entry['id'] for entry in entries if entry and 'id' in entry]

def get_single_stream_url(video_id):
    opts = YDL_BASE_OPTS.copy()
    opts['format'] = 'best[ext=mp4]/best'
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
        return info.get('url')

def start_continuous_stream():
    """ধারাবাহিক লাইভ ব্রডকাস্ট লুপ"""
    while True:
        try:
            print("Fetching video list from channel...")
            video_ids = get_channel_video_ids()
            
            if not video_ids:
                print("No videos found. Retrying in 15 seconds...")
                time.sleep(15)
                continue

            print(f"Total {len(video_ids)} videos found. Starting broadcast...")

            for vid in video_ids:
                try:
                    stream_url = get_single_stream_url(vid)
                    if not stream_url:
                        continue

                    # FFmpeg রেম্যাক্সিং কমান্ড
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
            print(f"Stream Loop Error: {e}")
            time.sleep(10)

# ব্যাকগ্রাউন্ড থ্রেডগুলো শুরু করা
threading.Thread(target=keep_alive_ping, daemon=True).start()
threading.Thread(target=start_continuous_stream, daemon=True).start()

# m3u8 মাউন্ট ও হেলথ চেক রুট
app.mount("/hls", StaticFiles(directory=HLS_DIR), name="hls")

@app.get("/")
def health_check():
    return {"status": "running", "stream_url": "/hls/live.m3u8"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
