import os
import time
import threading
import urllib.request
import yt_dlp
from fastapi import FastAPI, Response
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
CHANNEL_NAME = "Only Kdrama Bangla"

# স্লিপ মোড প্রতিরোধে সেলফ-পিং
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

threading.Thread(target=keep_alive_ping, daemon=True).start()

def get_channel_videos():
    """চ্যানেলের সব ভিডিওর আইডি ও টাইটেল দ্রুত সংগ্রহ করে (ব্লক ছাড়া)"""
    opts = {
        'extract_flat': True,
        'quiet': True,
        'no_warnings': True
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(CHANNEL_URL, download=False)
        entries = info.get('entries', [])
        videos = []
        for entry in entries:
            if entry and entry.get('id'):
                videos.append({
                    "id": entry['id'],
                    "title": entry.get('title', 'Korean Drama Episode'),
                    "thumbnail": f"https://i.ytimg.com/vi/{entry['id']}/hqdefault.jpg"
                })
        return videos

@app.get("/playlist.m3u")
def generate_m3u_playlist():
    """IPTV ও VLC-এর জন্য স্ট্যান্ডার্ড M3U প্লেলিস্ট তৈরি করে"""
    videos = get_channel_videos()
    
    # M3U হেডার
    m3u_lines = ["#EXTM3U\n"]
    
    for v in videos:
        title = v['title'].replace(",", " ")
        video_url = f"https://www.youtube.com/watch?v={v['id']}"
        # IPTV মেটাডাটা (লোগো, গ্রুপ এবং টাইটেল)
        m3u_lines.append(f'#EXTINF:-1 tvg-name="{title}" tvg-logo="{v["thumbnail"]}" group-title="{CHANNEL_NAME}",{title}\n')
        m3u_lines.append(f'{video_url}\n')
        
    content = "".join(m3u_lines)
    return Response(content=content, media_type="application/x-mpegurl")

@app.get("/")
def index():
    return {
        "status": "online",
        "m3u_playlist_url": "https://live-homai.onrender.com/playlist.m3u",
        "supported_players": ["VLC Media Player", "TiviMate", "OTT Navigator", "IPTV Smarters"]
    }

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
