import os
import ssl
import time
import threading
import urllib.request
import yt_dlp
from fastapi import FastAPI, Response
from fastapi.responses import RedirectResponse
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

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# পরীক্ষিত ও দ্রুতগতির প্রক্সি নোড (বট-ব্লক ছাড়া সরাসরি MP4 প্লে করতে)
INVIDIOUS_NODES = [
    "https://inv.tux.pizza",
    "https://invidious.projectsegfau.lt",
    "https://invidious.flokinet.to",
    "https://iv.melmac.space",
    "https://yt.artemislena.eu",
    "https://invidious.drgns.space"
]

def keep_alive_ping():
    """Render স্লিপ প্রতিরোধে অটো-পিং"""
    app_url = os.environ.get("RENDER_EXTERNAL_URL", "https://live-homai.onrender.com")
    time.sleep(30)
    while True:
        try:
            req = urllib.request.Request(app_url, headers={'User-Agent': 'KeepAlive/1.0'})
            urllib.request.urlopen(req, timeout=10, context=SSL_CTX)
        except Exception:
            pass
        time.sleep(600)

threading.Thread(target=keep_alive_ping, daemon=True).start()

def get_channel_videos():
    """চ্যানেলের সব ভিডিও তালিকা সংগ্রহ"""
    opts = {'extract_flat': True, 'quiet': True, 'no_warnings': True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(CHANNEL_URL, download=False)
        entries = info.get('entries', [])
        videos = []
        for entry in entries:
            if entry and entry.get('id'):
                title = entry.get('title', 'Korean Drama').replace('"', "'").replace(",", " ")
                videos.append({
                    "id": entry['id'],
                    "title": title,
                    "thumbnail": f"https://i.ytimg.com/vi/{entry['id']}/hqdefault.jpg"
                })
        return videos

# ১. IPTV প্লেয়ারের জন্য স্ট্যান্ডার্ড M3U প্লেলিস্ট
@app.get("/playlist.m3u")
def generate_m3u_playlist():
    app_url = os.environ.get("RENDER_EXTERNAL_URL", "https://live-homai.onrender.com").rstrip('/')
    videos = get_channel_videos()
    
    m3u_lines = ["#EXTM3U\n"]
    for v in videos:
        # প্রতিটি চ্যানেল সরাসরি আমাদের স্ট্রিমিং এন্ডপয়েন্টে পয়েন্ট করবে
        stream_link = f"{app_url}/video/{v['id']}.mp4"
        m3u_lines.append(f'#EXTINF:-1 tvg-id="{v["id"]}" tvg-name="{v["title"]}" tvg-logo="{v["thumbnail"]}" group-title="{CHANNEL_NAME}",{v["title"]}\n')
        m3u_lines.append(f'{stream_link}\n')
        
    return Response(
        content="".join(m3u_lines), 
        media_type="application/x-mpegurl",
        headers={"Access-Control-Allow-Origin": "*"}
    )

# ২. ব্রাউজার ও IPTV-র জন্য সরাসরি ভিডিও স্ট্রিমিং রিডাইরেক্টর
@app.get("/video/{video_id}.mp4")
def stream_video(video_id: str):
    # .mp4 এক্সটেনশন স্ট্রিপ করা
    clean_id = video_id.replace(".mp4", "")
    
    # সচল প্রক্সি নোড খুঁজে সরাসরি স্ট্রিমে রিডাইরেক্ট করা
    for base in INVIDIOUS_NODES:
        stream_url = f"{base}/latest_version?id={clean_id}&itag=18&local=true"
        try:
            req = urllib.request.Request(
                stream_url, 
                headers={'User-Agent': 'Mozilla/5.0', 'Range': 'bytes=0-100'}
            )
            with urllib.request.urlopen(req, timeout=3, context=SSL_CTX) as resp:
                if resp.status in (200, 206):
                    # প্লেয়ারকে সরাসরি কাজ করা স্ট্রিম লিংকে রিডাইরেক্ট করবে
                    return RedirectResponse(url=stream_url, status_code=302)
        except Exception:
            continue
            
    # ব্যাকআপ হিসেবে প্রথম নোডে রিডাইরেক্ট
    fallback_url = f"{INVIDIOUS_NODES[0]}/latest_version?id={clean_id}&itag=18&local=true"
    return RedirectResponse(url=fallback_url, status_code=302)

@app.get("/")
def index():
    return {
        "status": "online",
        "iptv_playlist": "https://live-homai.onrender.com/playlist.m3u",
        "player_compatible": True
    }

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
