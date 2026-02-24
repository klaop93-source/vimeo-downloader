import streamlit as st
import os
import requests
import base64
import subprocess
import re
from urllib.parse import urljoin
import datetime

# --- Configuration ---
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

# Cache the data so the website doesn't reload when changing the dropdown menu
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
                        # The Math Fix!
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

# --- Web App UI ---
st.set_page_config(page_title="Vimeo Downloader", page_icon="🎥")
st.title("🎥 Web Vimeo Downloader")

url_input = st.text_input("Paste Vimeo URL here:")

# If the user has pasted a link, automatically fetch the info
if url_input:
    with st.spinner("Analyzing URL..."):
        data, json_url = fetch_video_data(url_input)
        
    if not data:
        st.error(f"❌ {json_url}") # This prints the error message from the fetch function
        st.stop()
        
    # --- Create the Resolution Dropdown ---
    video_tracks = data.get("video", [])
    # Sort tracks from highest quality to lowest
    video_tracks.sort(key=lambda x: x.get("bitrate", 0), reverse=True)
    
    track_mapping = {}
    for t in video_tracks:
        # Check if the video has a height attribute (like 1080, 720, etc.)
        height = t.get("height")
        if height:
            label = f"{height}p"
        else:
            # Fallback if height is missing
            label = f"{int(t.get('bitrate', 0)/1000)} kbps"
            
        # Add to dictionary if it's not a duplicate
        if label not in track_mapping:
            track_mapping[label] = t

    # Show the Dropdown UI
    selected_resolution = st.selectbox("Select Video Quality:", list(track_mapping.keys()))
    
    # --- Download Button ---
    if st.button("Download Video"):
        status_text = st.empty()
        progress_bar = st.progress(0.0)
        
        # Get the specific video track the user selected
        v_track = track_mapping[selected_resolution]
        
        # Automatically grab the absolute best audio track available
        a_track = sorted(data.get("audio", []), key=lambda x: x.get("bitrate", 0))[-1]

        title = sanitize_filename(data.get("title", f"video_{datetime.datetime.now().strftime('%H%M%S')}"))
        base = urljoin(json_url, data.get("base_url", ""))
        
        temp_v = "temp_v.mp4"
        temp_a = "temp_a.mp4"
        # Include the resolution in the final file name!
        final_out = f"{title}_{selected_resolution}.mp4"

        if download_stream(base, v_track, temp_v, "video", progress_bar, status_text):
            progress_bar.progress(0.0)
            if download_stream(base, a_track, temp_a, "audio", progress_bar, status_text):
                status_text.info("🔄 Merging video and audio on server...")
                progress_bar.empty() 
                
                if merge_files(temp_v, temp_a, final_out):
                    status_text.success("✅ Video successfully processed!")
                    
                    with open(final_out, "rb") as file:
                        st.download_button(
                            label=f"⬇️ Download {selected_resolution} MP4 to Device",
                            data=file,
                            file_name=final_out,
                            mime="video/mp4"
                        )
                        
                    os.remove(temp_v)
                    os.remove(temp_a)
                else:
                    st.error("❌ FFmpeg Merge Failed on server.")
            else:
                st.error("❌ Audio Download Failed.")
        else:
            st.error("❌ Video Download Failed.")
