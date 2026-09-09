import os
import ssl
import time
import json
import threading
import urllib.request
import yt_dlp
from fastapi import FastAPI, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CHANNEL_URL = "https://www.youtube.com/@only_kdrama_bangla_explanation/videos"
CHANNEL_NAME = "Only Kdrama Bangla"

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

PIPED_INSTANCES = [
    "https://pipedapi.tokhmi.xyz",
    "https://api.piped.privacydev.net",
    "https://piped-api.lunar.icu",
    "https://pipedapi.drgns.space",
    "https://api.piped.private.coffee"
]

def keep_alive_ping():
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

def get_video_hls_manifest(video_id: str):
    clean_id = video_id.replace(".m3u8", "")
    for base in PIPED_INSTANCES:
        api_url = f"{base}/streams/{clean_id}"
        try:
            req = urllib.request.Request(api_url, headers={'User-Agent': USER_AGENT})
            with urllib.request.urlopen(req, timeout=4, context=SSL_CTX) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                hls_url = data.get("hls")
                if hls_url:
                    m_req = urllib.request.Request(hls_url, headers={'User-Agent': USER_AGENT})
                    with urllib.request.urlopen(m_req, timeout=4, context=SSL_CTX) as m_resp:
                        return m_resp.read().decode('utf-8')
        except Exception:
            continue
    return None

@app.get("/playlist.m3u")
def get_m3u_playlist():
    app_url = os.environ.get("RENDER_EXTERNAL_URL", "https://live-homai.onrender.com").rstrip('/')
    videos = get_channel_videos()
    
    m3u = ["#EXTM3U\n"]
    for v in videos:
        stream_url = f"{app_url}/stream/{v['id']}.m3u8"
        m3u.append(f'#EXTINF:-1 tvg-id="{v["id"]}" tvg-name="{v["title"]}" tvg-logo="{v["thumbnail"]}" group-title="{CHANNEL_NAME}",{v["title"]}\n')
        m3u.append(f'{stream_url}\n')
        
    return Response(
        content="".join(m3u),
        media_type="application/vnd.apple.mpegurl",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "no-cache"
        }
    )

@app.get("/stream/{video_id}.m3u8")
def serve_stream(video_id: str):
    manifest = get_video_hls_manifest(video_id)
    if not manifest:
        raise HTTPException(status_code=502, detail="Stream extracting failed")
    
    return Response(
        content=manifest,
        media_type="application/vnd.apple.mpegurl",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Cache-Control": "no-cache, no-store, must-revalidate"
        }
    )

@app.get("/live.m3u8")
def live_continuous():
    videos = get_channel_videos()
    if not videos:
        raise HTTPException(status_code=404, detail="No videos found")
    return serve_stream(videos[0]['id'])

@app.get("/")
def index():
    return {
        "status": "online",
        "home_air_tv_playlist": "https://live-homai.onrender.com/playlist.m3u",
        "single_live_channel": "https://live-homai.onrender.com/live.m3u8"
    }

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
