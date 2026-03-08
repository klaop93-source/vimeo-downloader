import streamlit as st
import os
import requests
import base64
import subprocess
import re
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime

# --- 1. Page Configuration & Custom CSS ---
st.set_page_config(page_title="Vimeo Downloader | DETOX", page_icon="🎥", layout="centered")

st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .block-container { padding-top: 2rem; padding-bottom: 2rem; }
    
    div.stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #00C6FF 0%, #0072FF 100%);
        color: white; border: none; border-radius: 8px; font-weight: bold;
        transition: all 0.3s ease; box-shadow: 0 4px 15px rgba(0, 114, 255, 0.3);
    }
    div.stButton > button[kind="primary"]:hover {
        transform: translateY(-2px); box-shadow: 0 6px 20px rgba(0, 114, 255, 0.5);
    }

    .detox-banner {
        background: linear-gradient(145deg, #18181b, #27272a);
        border: 1px solid #3f3f46; border-radius: 16px; padding: 30px;
        text-align: center; box-shadow: 0 10px 30px rgba(0,0,0,0.5);
        margin-top: 60px; position: relative; overflow: hidden;
    }
    .detox-banner::before {
        content: ""; position: absolute; top: 0; left: 0; right: 0; height: 3px;
        background: linear-gradient(90deg, #00C6FF, #25D366, #00C6FF);
    }
    .detox-text {
        color: #a1a1aa; font-size: 13px; letter-spacing: 2px;
        margin-bottom: 18px; font-weight: 600; text-transform: uppercase;
    }
    .detox-brand {
        background: linear-gradient(90deg, #00C6FF, #0072FF);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        font-weight: 900; font-size: 20px; letter-spacing: 1px;
    }
    .wa-btn {
        text-decoration: none !important; display: inline-flex; align-items: center; 
        justify-content: center; gap: 10px; background: linear-gradient(90deg, #25D366, #128C7E);
        color: white !important; padding: 12px 32px; border-radius: 50px; 
        font-weight: bold; font-size: 16px; transition: all 0.3s ease;
        box-shadow: 0 4px 15px rgba(37, 211, 102, 0.3);
    }
    .wa-btn:hover {
        transform: translateY(-3px); box-shadow: 0 8px 25px rgba(37, 211, 102, 0.6);
        background: linear-gradient(90deg, #128C7E, #25D366);
    }
</style>
""", unsafe_allow_html=True)

# --- 2. Backend Logic (Fast Concurrent Downloader) ---
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

def extract_vimeo_id(url):
    match = re.search(r'vimeo\.com/(?:video/)?(\d+)(?:/([a-zA-Z0-9]+)|\?h=([a-zA-Z0-9]+))?', url)
    if not match: return None, None
    return match.group(1), match.group(2) or match.group(3)

@st.cache_data(show_spinner=False)
def fetch_metadata(url):
    video_id, video_hash = extract_vimeo_id(url)
    if not video_id: return None, "Invalid Vimeo URL"

    config_url = f"https://player.vimeo.com/video/{video_id}/config"
    if video_hash: config_url += f"?h={video_hash}"

    try:
        resp = requests.get(config_url, headers={**HEADERS, "Referer": url}, timeout=15)
        resp.raise_for_status()
        config = resp.json()

        dash = config.get("request", {}).get("files", {}).get("dash", {})
        cdns = dash.get("cdns", {})
        default_cdn = dash.get("default_cdn")

        manifest_url = None
        if default_cdn and default_cdn in cdns: manifest_url = cdns[default_cdn]["url"]
        elif cdns: manifest_url = list(cdns.values())[0]["url"]

        if not manifest_url: return None, "Could not find video manifest"

        manifest_resp = requests.get(manifest_url, headers=HEADERS, timeout=15)
        manifest_resp.raise_for_status()
        manifest = manifest_resp.json()

        title = config.get("video", {}).get("title", "Unknown")
        video_tracks = sorted(manifest.get("video", []), key=lambda t: t.get("bitrate", 0), reverse=True)
        audio_tracks = sorted(manifest.get("audio", []), key=lambda t: t.get("bitrate", 0), reverse=True)

        base_url_raw = manifest.get("base_url", "")
        base_url = base_url_raw if base_url_raw.startswith("http") else urljoin(manifest_url, base_url_raw)

        qualities = {}
        for track in video_tracks:
            h = track.get("height", 0)
            label = f"{h}p" if h else f"{round(track.get('bitrate', 0) / 1000)} kbps"
            if label not in qualities:
                qualities[label] = track

        best_audio = audio_tracks[0] if audio_tracks else None

        return {
            "title": title,
            "qualities": qualities,
            "audio": best_audio,
            "base_url": base_url,
        }, None
    except Exception as e:
        return None, str(e)

def download_segments(base_url, track, label, progress_bar, status_text):
    segments = [s for s in track.get("segments", []) if s.get("url")]
    total = len(segments)
    chunks = []

    if not segments: return None

    init_seg = track.get("init_segment")
    if init_seg: chunks.append(base64.b64decode(init_seg))

    def fetch_seg(i_seg):
        i, seg = i_seg
        seg_url = urljoin(base_url, seg["url"])
        resp = requests.get(seg_url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return i, resp.content

    results = [None] * total
    done = 0

    try:
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(fetch_seg, (i, seg)): i for i, seg in enumerate(segments)}
            for future in as_completed(futures):
                i, data = future.result()
                results[i] = data
                done += 1
                percent_float = min(done / total, 1.0)
                progress_bar.progress(percent_float)
                status_text.text(f"⚡ Downloading {label}: {int(percent_float * 100)}%")
                
    except Exception as e:
        status_text.error(f"Error downloading segment: {e}")
        return None

    for r in results:
        if r is not None: chunks.append(r)
    return b"".join(chunks)

def merge_video_audio(video_path, audio_path, output_path):
    cmd = ["ffmpeg", "-y", "-i", video_path, "-i", audio_path, "-c:v", "copy", "-c:a", "copy", output_path]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False

# --- 3. Main App UI ---
st.title("🎥 Vimeo Downloader")
st.markdown("Easily extract and download high-quality videos and audio from Vimeo links.")
st.write("---")

url_input = st.text_input("🔗 Paste Vimeo URL here:", placeholder="https://vimeo.com/...")

if url_input:
    with st.spinner("🔍 Analyzing URL..."):
        meta, error_msg = fetch_metadata(url_input)
        
    if not meta:
        st.error(f"❌ {error_msg}")
        st.stop()
        
    st.success(f"📄 **Video Found:** {meta['title']}")

    qualities = meta["qualities"]
    labels = list(qualities.keys())

    with st.container():
        st.write("### Download Settings")
        selected_resolution = st.selectbox("📺 Select Video Quality:", labels)
        
        if st.button("🚀 Process & Download Video", use_container_width=True, type="primary"):
            st.write("---")
            status_text = st.empty()
            progress_bar = st.progress(0.0)
            
            selected_track = qualities[selected_resolution]
            base_url = meta["base_url"]
            safe_title = re.sub(r'[^\w\s._-]', '', meta["title"]).replace(" ", "_")
            if not safe_title: safe_title = f"video_{datetime.datetime.now().strftime('%H%M%S')}"
            
            temp_v, temp_a = "temp_v.mp4", "temp_a.mp4"
            final_out = f"{safe_title}_{selected_resolution}.mp4"

            # Download Video
            video_data = download_segments(base_url, selected_track, "Video Stream", progress_bar, status_text)
            if video_data:
                with open(temp_v, "wb") as f: f.write(video_data)
                
                progress_bar.progress(0.0)
                
                # Download Audio
                if meta["audio"]:
                    audio_data = download_segments(base_url, meta["audio"], "Audio Stream", progress_bar, status_text)
                    if audio_data:
                        with open(temp_a, "wb") as f: f.write(audio_data)
                        
                        status_text.info("🔄 Merging natively on server...")
                        progress_bar.empty() 
                        
                        if merge_video_audio(temp_v, temp_a, final_out):
                            status_text.success("✅ Success! Your video is ready.")
                            
                            with open(final_out, "rb") as file:
                                st.download_button(
                                    label=f"⬇️ Save {selected_resolution} MP4 to Device",
                                    data=file, file_name=final_out, mime="video/mp4",
                                    use_container_width=True, type="primary"
                                )
                                
                            os.remove(temp_v)
                            os.remove(temp_a)
                        else:
                            st.error("❌ Merge Failed.")
                    else:
                        st.error("❌ Audio Download Failed.")
                else:
                    os.rename(temp_v, final_out)
                    status_text.success("✅ Success! Video (No Audio) is ready.")
                    with open(final_out, "rb") as file:
                        st.download_button(
                            label=f"⬇️ Save {selected_resolution} MP4",
                            data=file, file_name=final_out, mime="video/mp4",
                            use_container_width=True, type="primary"
                        )
            else:
                st.error("❌ Video Download Failed.")

# --- 4. Beautiful DETOX Banner & WhatsApp Link ---
st.markdown("""
<div class="detox-banner">
    <div class="detox-text">DEVELOPED BY <span class="detox-brand">DETOX</span></div>
    <a href="https://whatsapp.com/channel/0029Va7tilcI1rcjV0GC0e2L" target="_blank" class="wa-btn">
        <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" fill="currentColor" viewBox="0 0 16 16">
          <path d="M13.601 2.326A7.854 7.854 0 0 0 7.994 0C3.627 0 .068 3.558.064 7.926c0 1.399.366 2.76 1.057 3.965L0 16l4.204-1.102a7.933 7.933 0 0 0 3.79.965h.004c4.368 0 7.926-3.558 7.93-7.93A7.898 7.898 0 0 0 13.6 2.326zM7.994 14.521a6.573 6.573 0 0 1-3.356-.92l-.24-.144-2.494.654.666-2.433-.156-.251a6.56 6.56 0 0 1-1.007-3.505c0-3.626 2.957-6.584 6.591-6.584a6.56 6.56 0 0 1 4.66 1.931 6.557 6.557 0 0 1 1.928 4.66c-.004 3.639-2.961 6.592-6.592 6.592zm3.615-4.934c-.197-.099-1.17-.578-1.353-.646-.182-.065-.315-.099-.445.099-.133.197-.513.646-.627.775-.114.133-.232.148-.43.05-.197-.1-.836-.308-1.592-.985-.59-.525-.985-1.175-1.103-1.372-.114-.198-.011-.304.088-.403.087-.088.197-.232.296-.346.1-.114.133-.198.198-.33.065-.134.034-.248-.015-.347-.05-.099-.445-1.076-.612-1.47-.16-.389-.323-.335-.445-.34-.114-.007-.247-.007-.38-.007a.729.729 0 0 0-.529.247c-.182.198-.691.677-.691 1.654 0 .977.71 1.916.81 2.049.098.133 1.394 2.132 3.383 2.992.47.205.84.326 1.129.418.475.152.904.129 1.246.08.38-.058 1.171-.48 1.338-.943.164-.464.164-.86.114-.943-.049-.084-.182-.133-.38-.232z"/>
        </svg>
        Join Now
    </a>
</div>
""", unsafe_allow_html=True)
