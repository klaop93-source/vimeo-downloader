import streamlit as st
import os
import requests
import base64
import subprocess
import re
from urllib.parse import urljoin
import datetime

# --- 1. Page Configuration & Custom CSS ---
st.set_page_config(page_title="Vimeo Downloader | DETOX", page_icon="🎥", layout="centered")

# Beautiful Custom CSS for UI/UX
st.markdown("""
<style>
    /* Hide Streamlit clutter */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    /* Add breathing room */
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    
    /* --- Beautiful Gradient Primary Buttons --- */
    div.stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #00C6FF 0%, #0072FF 100%);
        color: white;
        border: none;
        border-radius: 8px;
        font-weight: bold;
        transition: all 0.3s ease;
        box-shadow: 0 4px 15px rgba(0, 114, 255, 0.3);
    }
    div.stButton > button[kind="primary"]:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(0, 114, 255, 0.5);
    }

    /* --- Sleek Dark DETOX Banner --- */
    .detox-banner {
        background: linear-gradient(145deg, #18181b, #27272a);
        border: 1px solid #3f3f46;
        border-radius: 16px;
        padding: 30px;
        text-align: center;
        box-shadow: 0 10px 30px rgba(0,0,0,0.5);
        margin-top: 60px;
        position: relative;
        overflow: hidden;
    }
    
    /* Neon Top Accent Line */
    .detox-banner::before {
        content: "";
        position: absolute;
        top: 0; left: 0; right: 0; height: 3px;
        background: linear-gradient(90deg, #00C6FF, #25D366, #00C6FF);
    }

    .detox-text {
        color: #a1a1aa;
        font-size: 13px;
        letter-spacing: 2px;
        margin-bottom: 18px;
        font-weight: 600;
        text-transform: uppercase;
    }
    
    /* Gradient Text for the brand name */
    .detox-brand {
        background: linear-gradient(90deg, #00C6FF, #0072FF);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 900;
        font-size: 20px;
        letter-spacing: 1px;
    }

    /* --- Floating WhatsApp Button --- */
    .wa-btn {
        text-decoration: none !important; 
        display: inline-flex; 
        align-items: center; 
        justify-content: center;
        gap: 10px;
        background: linear-gradient(90deg, #25D366, #128C7E);
        color: white !important; 
        padding: 12px 32px; 
        border-radius: 50px; /* Pill shape */
        font-weight: bold;
        font-size: 16px;
        transition: all 0.3s ease;
        box-shadow: 0 4px 15px rgba(37, 211, 102, 0.3);
    }
    .wa-btn:hover {
        transform: translateY(-3px);
        box-shadow: 0 8px 25px rgba(37, 211, 102, 0.6);
        background: linear-gradient(90deg, #128C7E, #25D366);
    }
</style>
""", unsafe_allow_html=True)

# --- 2. Backend Logic ---
session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})

def sanitize_filename(title):
    sanitized = "".join(c for c in title if c.isalnum() or c in (' ', '.', '_', '-')).rstrip()
    return sanitized.replace(' ', '_')

def get_vimeo_manifest_url(vimeo_url):
    match = re.search(r'vimeo\.com/(?:video/)?(\d+)(?:/([a-zA-Z0-9]+)|\?h=([a-zA-Z0-9]+))?', vimeo_url)
    if not match: return None
    
    video_id = match.group(1)
    video_hash = match.group(2) or match.group(3)
    
    config_url = f"https://player.vimeo.com/video/{video_id}/config"
    if video_hash: config_url += f"?h={video_hash}"
        
    try:
        headers = {"Referer": vimeo_url}
        resp = session.get(config_url, headers=headers, timeout=15)
        resp.raise_for_status()
        dash_files = resp.json().get("request", {}).get("files", {}).get("dash", {})
        cdns = dash_files.get("cdns", {})
        default_cdn = dash_files.get("default_cdn")
        
        if default_cdn and default_cdn in cdns:
            return cdns[default_cdn].get("url")
        elif cdns:
            return cdns[list(cdns.keys())[0]].get("url")
    except Exception:
        pass
    return None

@st.cache_data(show_spinner=False)
def fetch_video_data(url_input):
    json_url = url_input.strip()
    if "vimeo.com" in json_url and "master.json" not in json_url:
        json_url = get_vimeo_manifest_url(json_url)
        if not json_url:
            return None, "Invalid URL or could not extract the hidden video files."
            
    try:
        data = session.get(json_url).json()
        return data, json_url
    except Exception as e:
        return None, str(e)

def download_stream(base_url, track, output_filepath, stream_name, progress_bar, status_text):
    segments = track.get("segments", [])
    if not segments: return False
    total_size = sum(seg.get("size", 0) for seg in segments)
    downloaded_size = 0

    try:
        with open(output_filepath, "wb") as f:
            if "init_segment" in track:
                f.write(base64.b64decode(track["init_segment"]))
            for seg in segments:
                if not seg.get("url"): continue
                seg_url = urljoin(base_url, seg.get("url"))
                resp = session.get(seg_url, stream=True, timeout=30)
                resp.raise_for_status()
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    if total_size > 0:
                        percent_float = min(downloaded_size / total_size, 1.0)
                        if downloaded_size % (8192 * 50) == 0 or percent_float >= 1.0:
                            progress_bar.progress(percent_float)
                            status_text.text(f"⬇️ Downloading {stream_name}: {int(percent_float * 100)}%")
    except Exception as e:
        status_text.error(f"Error: {e}")
        return False
    return True

def merge_files(video_path, audio_path, output_path):
    cmd = ['ffmpeg', '-i', video_path, '-i', audio_path, '-c:v', 'copy', '-c:a', 'copy', '-y', output_path]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
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
        data, json_url = fetch_video_data(url_input)
        
    if not data:
        st.error(f"❌ {json_url}")
        st.stop()
        
    video_title_raw = data.get("title", "Unknown Video")
    st.success(f"📄 **Video Found:** {video_title_raw}")
        
    video_tracks = data.get("video", [])
    video_tracks.sort(key=lambda x: x.get("bitrate", 0), reverse=True)
    
    track_mapping = {}
    for t in video_tracks:
        height = t.get("height")
        label = f"{height}p" if height else f"{int(t.get('bitrate', 0)/1000)} kbps"
        if label not in track_mapping:
            track_mapping[label] = t

    with st.container():
        st.write("### Download Settings")
        selected_resolution = st.selectbox("📺 Select Video Quality:", list(track_mapping.keys()))
        
        # Added type="primary" to trigger the custom blue gradient CSS!
        if st.button("🚀 Process & Download Video", use_container_width=True, type="primary"):
            st.write("---")
            status_text = st.empty()
            progress_bar = st.progress(0.0)
            
            v_track = track_mapping[selected_resolution]
            a_track = sorted(data.get("audio", []), key=lambda x: x.get("bitrate", 0))[-1]

            title = sanitize_filename(data.get("title", f"video_{datetime.datetime.now().strftime('%H%M%S')}"))
            base = urljoin(json_url, data.get("base_url", ""))
            
            temp_v, temp_a = "temp_v.mp4", "temp_a.mp4"
            final_out = f"{title}_{selected_resolution}.mp4"

            if download_stream(base, v_track, temp_v, "Video Stream", progress_bar, status_text):
                progress_bar.progress(0.0)
                if download_stream(base, a_track, temp_a, "Audio Stream", progress_bar, status_text):
                    status_text.info("🔄 Merging video and audio natively on server...")
                    progress_bar.empty() 
                    
                    if merge_files(temp_v, temp_a, final_out):
                        status_text.success("✅ Success! Your video is ready.")
                        
                        # Added type="primary" to the download button too!
                        with open(final_out, "rb") as file:
                            st.download_button(
                                label=f"⬇️ Save {selected_resolution} MP4 to Device",
                                data=file,
                                file_name=final_out,
                                mime="video/mp4",
                                use_container_width=True,
                                type="primary"
                            )
                            
                        os.remove(temp_v)
                        os.remove(temp_a)
                    else:
                        st.error("❌ FFmpeg Merge Failed on server.")
                else:
                    st.error("❌ Audio Download Failed.")
            else:
                st.error("❌ Video Download Failed.")

# --- 4. Beautiful DETOX Banner & WhatsApp Link ---
st.markdown("""
<div class="detox-banner">
    <div class="detox-text">
        DEVELOPED BY <span class="detox-brand">DETOX</span>
    </div>
    <a href="https://whatsapp.com/channel/0029Va7tilcI1rcjV0GC0e2L" target="_blank" class="wa-btn">
        <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" fill="currentColor" viewBox="0 0 16 16">
          <path d="M13.601 2.326A7.854 7.854 0 0 0 7.994 0C3.627 0 .068 3.558.064 7.926c0 1.399.366 2.76 1.057 3.965L0 16l4.204-1.102a7.933 7.933 0 0 0 3.79.965h.004c4.368 0 7.926-3.558 7.93-7.93A7.898 7.898 0 0 0 13.6 2.326zM7.994 14.521a6.573 6.573 0 0 1-3.356-.92l-.24-.144-2.494.654.666-2.433-.156-.251a6.56 6.56 0 0 1-1.007-3.505c0-3.626 2.957-6.584 6.591-6.584a6.56 6.56 0 0 1 4.66 1.931 6.557 6.557 0 0 1 1.928 4.66c-.004 3.639-2.961 6.592-6.592 6.592zm3.615-4.934c-.197-.099-1.17-.578-1.353-.646-.182-.065-.315-.099-.445.099-.133.197-.513.646-.627.775-.114.133-.232.148-.43.05-.197-.1-.836-.308-1.592-.985-.59-.525-.985-1.175-1.103-1.372-.114-.198-.011-.304.088-.403.087-.088.197-.232.296-.346.1-.114.133-.198.198-.33.065-.134.034-.248-.015-.347-.05-.099-.445-1.076-.612-1.47-.16-.389-.323-.335-.445-.34-.114-.007-.247-.007-.38-.007a.729.729 0 0 0-.529.247c-.182.198-.691.677-.691 1.654 0 .977.71 1.916.81 2.049.098.133 1.394 2.132 3.383 2.992.47.205.84.326 1.129.418.475.152.904.129 1.246.08.38-.058 1.171-.48 1.338-.943.164-.464.164-.86.114-.943-.049-.084-.182-.133-.38-.232z"/>
        </svg>
        Join Now
    </a>
</div>
""", unsafe_allow_html=True)
