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

CHANNEL_URL = "https://www.youtube.com/@only_kdrama_bangla_explanation/videos"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HLS_DIR = os.path.join(BASE_DIR, "hls")
os.makedirs(HLS_DIR, exist_ok=True)

# অ্যান্ড্রয়েড ক্লায়েন্ট কনফিগারেশন (403 ব্লক ও n-challenge এড়াতে)
YDL_BASE_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'ios']
        }
    }
}

def get_channel_video_ids():
    """চ্যানেল থেকে সব ভিডিওর আইডি সংগ্রহ করা"""
    opts = YDL_BASE_OPTS.copy()
    opts['extract_flat'] = True
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(CHANNEL_URL, download=False)
        entries = info.get('entries', [])
        return [entry['id'] for entry in entries if entry and 'id' in entry]

def get_single_stream_url(video_id):
    """অ্যান্ড্রয়েড ক্লায়েন্ট ব্যবহার করে ফ্রেশ স্ট্রিম লিঙ্ক বের করা"""
    opts = YDL_BASE_OPTS.copy()
    opts['format'] = 'best[ext=mp4]/best'
    
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
        return info.get('url')

def start_continuous_stream():
    """ধারাবাহিক লাইভ m3u8 ব্রডকাস্ট লুপ"""
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

                    # FFmpeg রেম্যাক্স করে HLS স্ট্রিম তৈরি
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
            print(f"Loop error: {e}")
            time.sleep(10)

threading.Thread(target=start_continuous_stream, daemon=True).start()

app.mount("/hls", StaticFiles(directory=HLS_DIR), name="hls")

@app.get("/")
def health_check():
    return {"status": "running", "stream_url": "/hls/live.m3u8"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
