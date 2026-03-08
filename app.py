# app.py — Vimeo Private Video Downloader
# Requirements: pip install requests ffmpeg-python
# Also needs ffmpeg installed on your system
import streamlit as st
import re
import os
import sys
import base64
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
}

def extract_vimeo_id(url):
    match = re.search(r'vimeo\.com/(?:video/)?(\d+)(?:/([a-zA-Z0-9]+)|\?h=([a-zA-Z0-9]+))?', url)
    if not match:
        raise ValueError("Invalid Vimeo URL")
    video_id = match.group(1)
    video_hash = match.group(2) or match.group(3)
    return video_id, video_hash

def fetch_metadata(url):
    video_id, video_hash = extract_vimeo_id(url)
    config_url = f"https://player.vimeo.com/video/{video_id}/config"
    if video_hash:
        config_url += f"?h={video_hash}"

    resp = requests.get(config_url, headers={**HEADERS, "Referer": url})
    resp.raise_for_status()
    config = resp.json()

    dash = config.get("request", {}).get("files", {}).get("dash", {})
    cdns = dash.get("cdns", {})
    default_cdn = dash.get("default_cdn")

    manifest_url = None
    if default_cdn and default_cdn in cdns:
        manifest_url = cdns[default_cdn]["url"]
    elif cdns:
        manifest_url = list(cdns.values())[0]["url"]

    if not manifest_url:
        raise Exception("Could not find video manifest")

    manifest_resp = requests.get(manifest_url, headers=HEADERS)
    manifest_resp.raise_for_status()
    manifest = manifest_resp.json()

    title = config.get("video", {}).get("title", "Unknown")
    duration = config.get("video", {}).get("duration", 0)

    video_tracks = sorted(manifest.get("video", []), key=lambda t: t.get("bitrate", 0), reverse=True)
    audio_tracks = sorted(manifest.get("audio", []), key=lambda t: t.get("bitrate", 0), reverse=True)

    base_url_raw = manifest.get("base_url", "")
    if base_url_raw.startswith("http"):
        base_url = base_url_raw
    else:
        from urllib.parse import urljoin
        base_url = urljoin(manifest_url, base_url_raw)

    qualities = {}
    for track in video_tracks:
        h = track.get("height", 0)
        label = f"{h}p" if h else f"{round(track.get('bitrate', 0) / 1000)} kbps"
        if label not in qualities:
            qualities[label] = track

    best_audio = audio_tracks[0] if audio_tracks else None

    return {
        "title": title,
        "duration": duration,
        "qualities": qualities,
        "audio": best_audio,
        "base_url": base_url,
    }

def download_segments(base_url, track, label="stream"):
    from urllib.parse import urljoin
    segments = [s for s in track.get("segments", []) if s.get("url")]
    total = len(segments)
    chunks = []

    # Init segment
    init_seg = track.get("init_segment")
    if init_seg:
        chunks.append(base64.b64decode(init_seg))

    def fetch_seg(i_seg):
        i, seg = i_seg
        seg_url = urljoin(base_url, seg["url"])
        resp = requests.get(seg_url, headers=HEADERS)
        resp.raise_for_status()
        return i, resp.content

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(fetch_seg, (i, seg)): i for i, seg in enumerate(segments)}
        results = [None] * total
        done = 0
        for future in as_completed(futures):
            i, data = future.result()
            results[i] = data
            done += 1
            pct = int(done / total * 100)
            print(f"\r  [{label}] {pct}%", end="", flush=True)

    chunks.extend(results)
    print()
    return b"".join(chunks)

def merge_video_audio(video_path, audio_path, output_path):
    import subprocess
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy", "-c:a", "copy",
        output_path
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def main():
    url = input("Enter Vimeo URL: ").strip()
    if not url:
        print("No URL provided.")
        return

    print("Fetching metadata...")
    meta = fetch_metadata(url)
    print(f"\nTitle: {meta['title']}")
    print(f"Duration: {meta['duration']}s")

    qualities = meta["qualities"]
    labels = list(qualities.keys())
    print("\nAvailable qualities:")
    for i, label in enumerate(labels):
        q = qualities[label]
        print(f"  [{i}] {label} ({q.get('width', '?')}x{q.get('height', '?')}, {round(q.get('bitrate', 0) / 1000)} kbps)")

    choice = int(input(f"\nSelect quality [0-{len(labels)-1}]: ").strip())
    selected = qualities[labels[choice]]

    safe_title = re.sub(r'[^\w\s._-]', '', meta["title"]).replace(" ", "_")
    base_url = meta["base_url"]

    print("\nDownloading video...")
    video_data = download_segments(base_url, selected, "video")
    video_path = f"{safe_title}_video.mp4"
    with open(video_path, "wb") as f:
        f.write(video_data)

    if meta["audio"]:
        print("Downloading audio...")
        audio_data = download_segments(base_url, meta["audio"], "audio")
        audio_path = f"{safe_title}_audio.mp4"
        with open(audio_path, "wb") as f:
            f.write(audio_data)

        output_path = f"{safe_title}_{labels[choice]}.mp4"
        print("Merging video & audio...")
        merge_video_audio(video_path, audio_path, output_path)

        os.remove(video_path)
        os.remove(audio_path)
        print(f"\n✅ Saved: {output_path}")
    else:
        final = f"{safe_title}_{labels[choice]}.mp4"
        os.rename(video_path, final)
        print(f"\n✅ Saved: {final}")

if __name__ == "__main__":
    main()
