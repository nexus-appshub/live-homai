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
LOG_FILE = os.path.join(BASE_DIR, "ffmpeg.log")
os.makedirs(HLS_DIR, exist_ok=True)

STREAM_STATUS = {
    "state": "Initializing",
    "current_video": None,
    "last_error": None,
    "ffmpeg_running": False
}

IOS_USER_AGENT = "com.google.ios.youtube/19.29.1 (iPhone14,5; U; CPU iOS 17_5_1 like Mac OS X)"

# ১. সার্ভার স্লিপ রোধে সেলফ-পিং
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

# ২. চ্যানেলের সব ভিডিও আইডি সংগ্রহ
def get_channel_video_ids():
    opts = {'quiet': True, 'extract_flat': True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(CHANNEL_URL, download=False)
        return [entry['id'] for entry in info.get('entries', []) if entry and 'id' in entry]

# ৩. YouTube iOS ক্লায়েন্ট দিয়ে সরাসরি নেটিভ HLS লিংক সংগ্রহ
def get_native_hls_url(video_id):
    opts = {
        'quiet': True,
        'no_warnings': True,
        # ফরম্যাট ফিল্টার ছাড়া রাখলে iOS সরাসরি মাস্টার m3u8 লিংক দেয়
        'extractor_args': {
            'youtube': {
                'player_client': ['ios']
            }
        }
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
        return info.get('url')

# ৪. অবিচ্ছিন্ন লাইভ HLS ব্রডকাস্ট লুপ
def start_continuous_stream():
    global STREAM_STATUS
    m3u8_path = os.path.join(HLS_DIR, 'live.m3u8')
    segment_pattern = os.path.join(HLS_DIR, 'segment_%03d.ts')
    
    while True:
        try:
            STREAM_STATUS["state"] = "Fetching video list"
            video_ids = get_channel_video_ids()
            
            if not video_ids:
                STREAM_STATUS["last_error"] = "No videos returned. Retrying in 15 seconds..."
                time.sleep(15)
                continue

            for vid in video_ids:
                try:
                    STREAM_STATUS["current_video"] = vid
                    STREAM_STATUS["state"] = f"Extracting iOS HLS for {vid}"
                    hls_stream_url = get_native_hls_url(vid)
                    
                    if not hls_stream_url:
                        STREAM_STATUS["last_error"] = f"Failed to extract stream for {vid}"
                        time.sleep(2)
                        continue

                    STREAM_STATUS["state"] = f"Streaming {vid}"
                    STREAM_STATUS["last_error"] = None
                    STREAM_STATUS["ffmpeg_running"] = True

                    # FFmpeg দিয়ে YouTube HLS সরাসরি লোকাল লাইভ m3u8 এ কপি
                    with open(LOG_FILE, "w") as log_output:
                        cmd = [
                            'ffmpeg',
                            '-user_agent', IOS_USER_AGENT,
                            '-re',
                            '-i', hls_stream_url,
                            '-c', 'copy',
                            '-f', 'hls',
                            '-hls_time', '3',
                            '-hls_list_size', '5',
                            '-hls_flags', 'delete_segments+append_list',
                            '-hls_segment_filename', segment_pattern,
                            m3u8_path
                        ]
                        process = subprocess.Popen(cmd, stdout=log_output, stderr=log_output)
                        process.wait()

                    STREAM_STATUS["ffmpeg_running"] = False

                except Exception as vid_err:
                    STREAM_STATUS["last_error"] = str(vid_err)
                    STREAM_STATUS["ffmpeg_running"] = False
                    time.sleep(2)

        except Exception as e:
            STREAM_STATUS["last_error"] = str(e)
            time.sleep(10)

# ব্যাকগ্রাউন্ড থ্রেড চালু
threading.Thread(target=keep_alive_ping, daemon=True).start()
threading.Thread(target=start_continuous_stream, daemon=True).start()

# সঠিক HLS হেডারসহ ফাইল সার্ভিং
@app.get("/hls/{filename}")
def serve_hls(filename: str):
    file_path = os.path.join(HLS_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=503, detail="Stream is preparing, please wait a few seconds and refresh...")
    
    media_type = "application/vnd.apple.mpegurl" if filename.endswith(".m3u8") else "video/MP2T"
    return FileResponse(
        file_path, 
        media_type=media_type, 
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )

@app.get("/")
def index():
    ready_files = [f for f in os.listdir(HLS_DIR) if f.endswith('.ts') or f.endswith('.m3u8')] if os.path.exists(HLS_DIR) else []
    return {
        "server": "online",
        "stream_info": STREAM_STATUS,
        "hls_files_ready": ready_files,
        "stream_url": "/hls/live.m3u8"
    }

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
