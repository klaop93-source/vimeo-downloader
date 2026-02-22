
import flet as ft
import os
import requests
import json
import base64
import subprocess
import re
from urllib.parse import urljoin
import datetime

# --- Configuration ---
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
})

def get_android_ffmpeg():
    """Locates the FFmpeg binary injected by the OS package manager."""
    lib_dirs = os.environ.get("LD_LIBRARY_PATH", "").split(":")
    for lib_dir in lib_dirs:
        possible_path = os.path.join(lib_dir, "libffmpeg.so")
        if os.path.exists(possible_path):
            return possible_path
    return "ffmpeg" # Fallback for PC testing

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

def download_stream(base_url, track, output_filepath, stream_name, page, progress_bar, status_text):
    """Downloads segments and updates the UI."""
    segments = track.get("segments", [])
    if not segments: return False

    total_size = sum(seg.get("size", 0) for seg in segments)
    downloaded_size = 0
    os.makedirs(os.path.dirname(output_filepath), exist_ok=True)

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
                        percent_float = downloaded_size / total_size
                        current_val = progress_bar.value if progress_bar.value is not None else 0.0
                        if percent_float - current_val > 0.01 or percent_float >= 1.0:
                            progress_bar.value = percent_float
                            status_text.value = f"⬇️ Downloading {stream_name.capitalize()}: {int(percent_float * 100)}%"
                            page.update()
    except Exception as e:
        status_text.value = f"❌ Error downloading {stream_name}: {e}"
        return False
    return True

def merge_files(video_path, audio_path, output_path):
    """Merges files using the injected Android FFmpeg binary."""
    ffmpeg_path = get_android_ffmpeg()
    cmd = [ffmpeg_path, '-i', video_path, '-i', audio_path, '-c:v', 'copy', '-c:a', 'copy', '-y', output_path]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        return True
    except Exception:
        return False

# --- App UI ---
def main(page: ft.Page):
    page.title = "Vimeo Downloader"
    page.theme_mode = ft.ThemeMode.DARK
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.scroll = "adaptive"

    title_text = ft.Text("🎥 Vimeo Downloader", size=28, weight=ft.FontWeight.BOLD)
    url_input = ft.TextField(label="Paste Vimeo URL here", width=320)
    status_text = ft.Text("", color=ft.colors.BLUE_400, text_align=ft.TextAlign.CENTER)
    progress_bar = ft.ProgressBar(width=320, value=0, visible=False)

    def on_download_click(e):
        if not url_input.value:
            status_text.value = "❌ Please enter a URL."
            page.update()
            return

        download_btn.disabled = True
        progress_bar.visible = True
        progress_bar.value = None
        status_text.value = "🔍 Analyzing video data..."
        status_text.color = ft.colors.BLUE_400
        page.update()

        try:
            json_url = url_input.value.strip()
            if "vimeo.com" in json_url and "master.json" not in json_url:
                json_url = get_vimeo_manifest_url(json_url)
                if not json_url:
                    raise ValueError("Could not extract manifest. Ensure it is a valid Vimeo link.")

            data = session.get(json_url, timeout=30).json()
            title = sanitize_filename(data.get("title", f"video_{datetime.datetime.now().strftime('%H%M%S')}"))
            base_url = urljoin(json_url, data.get("base_url", ""))
            
            v_track = sorted(data.get("video", []), key=lambda t: t.get("bitrate", 0), reverse=True)[0]
            a_track = sorted(data.get("audio", []), key=lambda t: t.get("bitrate", 0), reverse=True)[0]

            # Set download paths (Internal storage fallback for strict Android 11+ rules)
            download_dir = "/storage/emulated/0/Download"
            if not os.path.exists(download_dir): download_dir = os.getenv("HOME", "/tmp")
            
            temp_v = os.path.join(download_dir, "temp_v.mp4")
            temp_a = os.path.join(download_dir, "temp_a.mp4")
            final_out = os.path.join(download_dir, f"{title}.mp4")

            progress_bar.value = 0.0
            page.update()

            if download_stream(base_url, v_track, temp_v, "video", page, progress_bar, status_text):
                progress_bar.value = 0.0
                if download_stream(base_url, a_track, temp_a, "audio", page, progress_bar, status_text):
                    progress_bar.value = None
                    status_text.value = "🔄 Merging video and audio natively..."
                    page.update()
                    
                    if merge_files(temp_v, temp_a, final_out):
                        status_text.value = f"✅ Saved to Downloads:\n{title}.mp4"
                        status_text.color = ft.colors.GREEN_400
                        progress_bar.value = 1.0
                        try: os.remove(temp_v); os.remove(temp_a)
                        except: pass
                    else:
                        status_text.value = "❌ FFmpeg Merge Failed."
                        status_text.color = ft.colors.RED_400
                else:
                    status_text.value = "❌ Audio Download Failed."
                    status_text.color = ft.colors.RED_400
            else:
                status_text.value = "❌ Video Download Failed."
                status_text.color = ft.colors.RED_400

        except Exception as ex:
            status_text.value = f"❌ Error: {ex}"
            status_text.color = ft.colors.RED_400
        finally:
            download_btn.disabled = False
            page.update()

    download_btn = ft.ElevatedButton("Download", on_click=on_download_click, width=200)

    page.add(
        ft.Container(height=20), title_text, ft.Container(height=10),
        url_input, download_btn, ft.Container(height=10),
        progress_bar, status_text
    )

if __name__ == "__main__":
    ft.app(target=main)
