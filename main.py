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
    """Locates the injected FFmpeg binary with strict Android fallback paths."""
    # 1. Check standard environment path
    lib_dirs = os.environ.get("LD_LIBRARY_PATH", "").split(":")
    for lib_dir in lib_dirs:
        possible_path = os.path.join(lib_dir, "libffmpeg.so")
        if os.path.exists(possible_path):
            return possible_path
            
    # 2. Hard-fallback: Check the app's internal Android data folder directly
    try:
        app_home = os.environ.get("HOME", "")
        if app_home:
            base_dir = os.path.dirname(app_home)
            possible_path = os.path.join(base_dir, "lib", "libffmpeg.so")
            if os.path.exists(possible_path):
                return possible_path
    except Exception:
        pass

    return "ffmpeg" # Fallback for testing on PC

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

def download_stream(base_url, track, output_filepath, stream_name, page, progress_bar, status_text):
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
                        if progress_bar.value is None or percent_float - progress_bar.value > 0.01:
                            progress_bar.value = percent_float
                            status_text.value = f"⬇️ {stream_name.capitalize()}: {int(percent_float * 100)}%"
                            page.update()
    except Exception as e:
        status_text.value = f"❌ Error: {e}"
        return False
    return True

def merge_files(video_path, audio_path, output_path):
    ffmpeg_path = get_android_ffmpeg()
    cmd = [ffmpeg_path, '-i', video_path, '-i', audio_path, '-c:v', 'copy', '-c:a', 'copy', '-y', output_path]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except Exception:
        return False

def main(page: ft.Page):
    page.title = "Vimeo App"
    page.theme_mode = ft.ThemeMode.DARK
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.scroll = "adaptive"

    url_input = ft.TextField(label="Vimeo URL", width=320)
    status_text = ft.Text("", text_align=ft.TextAlign.CENTER)
    progress_bar = ft.ProgressBar(width=320, value=0, visible=False)

    def on_download(e):
        if not url_input.value: return
        download_btn.disabled = True
        progress_bar.visible = True
        progress_bar.value = None
        status_text.value = "Analyzing..."
        page.update()

        try:
            url = url_input.value.strip()
            manifest_url = get_vimeo_manifest_url(url) if "vimeo.com" in url else url
            if not manifest_url: raise ValueError("Invalid URL")

            data = session.get(manifest_url).json()
            title = sanitize_filename(data.get("title", "video"))
            base = urljoin(manifest_url, data.get("base_url", ""))
            v_track = sorted(data["video"], key=lambda x: x["bitrate"])[-1]
            a_track = sorted(data["audio"], key=lambda x: x["bitrate"])[-1]

            path = "/storage/emulated/0/Download"
            if not os.path.exists(path): path = os.getcwd()
            
            temp_v, temp_a = os.path.join(path, "v.mp4"), os.path.join(path, "a.mp4")
            final = os.path.join(path, f"{title}.mp4")

            progress_bar.value = 0
            if download_stream(base, v_track, temp_v, "video", page, progress_bar, status_text):
                progress_bar.value = 0
                if download_stream(base, a_track, temp_a, "audio", page, progress_bar, status_text):
                    status_text.value = "Merging natively..."
                    progress_bar.value = None
                    page.update()
                    if merge_files(temp_v, temp_a, final):
                        status_text.value = f"✅ Saved: {title}.mp4"
                        status_text.color = ft.colors.GREEN_400
                        try:
                            os.remove(temp_v); os.remove(temp_a)
                        except OSError:
                            pass
                    else: 
                        status_text.value = "❌ Merge failed"
                        status_text.color = ft.colors.RED_400
        except Exception as ex: 
            status_text.value = f"❌ {ex}"
            status_text.color = ft.colors.RED_400
        finally:
            download_btn.disabled = False
            page.update()

    download_btn = ft.ElevatedButton("Download", on_click=on_download)
    page.add(ft.Text("🎥 Vimeo Downloader", size=25), url_input, download_btn, progress_bar, status_text)

if __name__ == "__main__":
    ft.app(target=main)
