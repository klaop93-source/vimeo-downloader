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
    """Extracts the hidden JSON manifest URL directly from a Vimeo link."""
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
                        # THE FIX: min() ensures the value never exceeds exactly 1.0
                        percent_float = min(downloaded_size / total_size, 1.0)
                        
                        # Throttle UI updates so the web browser doesn't freeze
                        if downloaded_size % (8192 * 50) == 0 or percent_float >= 1.0:
                            progress_bar.progress(percent_float)
                            status_text.text(f"⬇️ Downloading {stream_name}: {int(percent_float * 100)}%")
    except Exception as e:
        status_text.error(f"Error: {e}")
        return False
    return True
def merge_files(video_path, audio_path, output_path):
    # Because we use packages.txt in GitHub, 'ffmpeg' is natively installed on the server!
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

if st.button("Fetch and Process Video"):
    if not url_input:
        st.warning("Please enter a URL.")
        st.stop()

    status_text = st.empty()
    progress_bar = st.progress(0.0)
    
    status_text.info("Analyzing URL...")
    
    try:
        json_url = url_input.strip()
        
        # Check if it's a standard Vimeo link and extract the manifest
        if "vimeo.com" in json_url and "master.json" not in json_url:
            json_url = get_vimeo_manifest_url(json_url)
            if not json_url:
                st.error("Invalid URL or could not extract the hidden video files. Check the link.")
                st.stop()

        # Fetch the JSON data
        data = session.get(json_url).json()
        title = sanitize_filename(data.get("title", f"video_{datetime.datetime.now().strftime('%H%M%S')}"))
        base = urljoin(json_url, data.get("base_url", ""))
        
        # Automatically grab the highest quality video and audio tracks
        v_track = sorted(data["video"], key=lambda x: x["bitrate"])[-1]
        a_track = sorted(data["audio"], key=lambda x: x["bitrate"])[-1]

        # Use the server's local working directory for temp files
        temp_v = "temp_v.mp4"
        temp_a = "temp_a.mp4"
        final_out = f"{title}.mp4"

        # Start the download process
        if download_stream(base, v_track, temp_v, "video", progress_bar, status_text):
            progress_bar.progress(0.0)
            if download_stream(base, a_track, temp_a, "audio", progress_bar, status_text):
                status_text.info("🔄 Merging video and audio on server...")
                progress_bar.empty() 
                
                # Merge using the server's FFmpeg
                if merge_files(temp_v, temp_a, final_out):
                    status_text.success("✅ Video successfully processed!")
                    
                    # Provide a download button to send the file from the server to your device
                    with open(final_out, "rb") as file:
                        st.download_button(
                            label="⬇️ Download MP4 to Device",
                            data=file,
                            file_name=final_out,
                            mime="video/mp4"
                        )
                        
                    # Cleanup server storage immediately after creating the button
                    os.remove(temp_v)
                    os.remove(temp_a)
                else:
                    st.error("❌ FFmpeg Merge Failed on server.")
            else:
                st.error("❌ Audio Download Failed.")
        else:
            st.error("❌ Video Download Failed.")

    except Exception as ex:
        st.error(f"❌ An error occurred: {ex}")
