#!/usr/bin/env python3
"""
Vimeo Private Video Downloader — Desktop App
Built with ❤ by DETOX
"""

import os
import re
import json
import subprocess
import threading
import tempfile
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import customtkinter as ctk
except ImportError:
    print("Installing customtkinter...")
    subprocess.check_call(["pip", "install", "customtkinter"])
    import customtkinter as ctk

try:
    import requests
except ImportError:
    print("Installing requests...")
    subprocess.check_call(["pip", "install", "requests"])
    import requests

try:
    from PIL import Image
except ImportError:
    print("Installing Pillow...")
    subprocess.check_call(["pip", "install", "Pillow"])
    from PIL import Image

# ── Theme ──────────────────────────────────────────────
BG_DARK = "#0f1012"
BG_CARD = "#18191d"
BG_INPUT = "#1e2025"
BORDER = "#2a2b30"
PRIMARY = "#00bfff"
ACCENT = "#0066ff"
TEXT = "#f2f2f2"
TEXT_MUTED = "#8a8d9b"
DESTRUCTIVE = "#e04040"
SUCCESS = "#22c55e"
FONT_FAMILY = "Segoe UI"


class VimeoDownloader(ctk.CTk):
    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self.title("Vimeo Downloader — DETOX")
        self.geometry("720x680")
        self.minsize(600, 580)
        self.configure(fg_color=BG_DARK)

        self._build_ui()

    # ── UI ──────────────────────────────────────────────
    def _build_ui(self):
        # Header
        header = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=0, height=56)
        header.pack(fill="x")
        header.pack_propagate(False)

        logo_frame = ctk.CTkFrame(header, fg_color=PRIMARY, corner_radius=8, width=32, height=32)
        logo_frame.place(x=16, rely=0.5, anchor="w")
        ctk.CTkLabel(logo_frame, text="⬇", font=(FONT_FAMILY, 14), text_color=BG_DARK).place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(header, text="Vimeo Downloader", font=(FONT_FAMILY, 16, "bold"), text_color=TEXT).place(x=58, rely=0.5, anchor="w")
        ctk.CTkLabel(header, text="Built with ❤ by DETOX", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED).place(relx=0.95, rely=0.5, anchor="e")

        # Main container
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=24, pady=20)

        # URL Section
        ctk.CTkLabel(container, text="PASTE VIMEO URL", font=(FONT_FAMILY, 11, "bold"), text_color=TEXT_MUTED).pack(anchor="w")

        url_row = ctk.CTkFrame(container, fg_color="transparent")
        url_row.pack(fill="x", pady=(6, 0))

        self.url_entry = ctk.CTkEntry(
            url_row, placeholder_text="https://vimeo.com/...",
            height=44, corner_radius=10,
            fg_color=BG_INPUT, border_color=BORDER, text_color=TEXT,
            placeholder_text_color=TEXT_MUTED, font=(FONT_FAMILY, 13)
        )
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.url_entry.bind("<Return>", lambda e: self._on_analyze())

        self.analyze_btn = ctk.CTkButton(
            url_row, text="🔍  Analyze", width=120, height=44,
            corner_radius=10, font=(FONT_FAMILY, 13, "bold"),
            fg_color=PRIMARY, hover_color=ACCENT, text_color=BG_DARK,
            command=self._on_analyze
        )
        self.analyze_btn.pack(side="right")

        # Status bar
        self.status_label = ctk.CTkLabel(container, text="", font=(FONT_FAMILY, 12), text_color=TEXT_MUTED)
        self.status_label.pack(anchor="w", pady=(12, 0))

        # Video info card (hidden initially)
        self.info_card = ctk.CTkFrame(container, fg_color=BG_CARD, corner_radius=14, border_width=1, border_color=BORDER)

        self.thumb_label = ctk.CTkLabel(self.info_card, text="", width=200, height=112)
        self.thumb_label.pack(side="left", padx=14, pady=14)

        info_text = ctk.CTkFrame(self.info_card, fg_color="transparent")
        info_text.pack(side="left", fill="both", expand=True, padx=(0, 14), pady=14)

        self.title_label = ctk.CTkLabel(info_text, text="", font=(FONT_FAMILY, 15, "bold"), text_color=TEXT, wraplength=350, anchor="w", justify="left")
        self.title_label.pack(anchor="w")

        self.duration_label = ctk.CTkLabel(info_text, text="", font=(FONT_FAMILY, 12), text_color=TEXT_MUTED)
        self.duration_label.pack(anchor="w", pady=(4, 0))

        # Quality selector (hidden initially)
        self.quality_frame = ctk.CTkFrame(container, fg_color="transparent")
        self.quality_label = ctk.CTkLabel(self.quality_frame, text="SELECT QUALITY", font=(FONT_FAMILY, 11, "bold"), text_color=TEXT_MUTED)
        self.quality_label.pack(anchor="w", pady=(0, 8))

        self.quality_buttons_frame = ctk.CTkFrame(self.quality_frame, fg_color="transparent")
        self.quality_buttons_frame.pack(fill="x")

        # Download button (hidden initially)
        self.download_btn = ctk.CTkButton(
            container, text="⬇️  Download Video", height=48,
            corner_radius=12, font=(FONT_FAMILY, 14, "bold"),
            fg_color=PRIMARY, hover_color=ACCENT, text_color=BG_DARK,
            command=self._on_download
        )

        # Progress bar (hidden initially)
        self.progress_frame = ctk.CTkFrame(container, fg_color="transparent")
        self.progress_bar = ctk.CTkProgressBar(self.progress_frame, height=8, corner_radius=4, fg_color=BG_INPUT, progress_color=PRIMARY)
        self.progress_bar.pack(fill="x")
        self.progress_bar.set(0)
        self.progress_label = ctk.CTkLabel(self.progress_frame, text="0%", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED)
        self.progress_label.pack(pady=(4, 0))

        # Empty state
        self.empty_state = ctk.CTkFrame(container, fg_color="transparent")
        self.empty_state.pack(fill="both", expand=True, pady=30)

        icon_box = ctk.CTkFrame(self.empty_state, fg_color=BG_CARD, corner_radius=16, width=80, height=80)
        icon_box.pack()
        icon_box.pack_propagate(False)
        ctk.CTkLabel(icon_box, text="🎬", font=(FONT_FAMILY, 32)).place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(self.empty_state, text="Enter a Vimeo URL to get started", font=(FONT_FAMILY, 14, "bold"), text_color=TEXT).pack(pady=(14, 4))
        ctk.CTkLabel(self.empty_state, text="Paste any Vimeo video link above to analyze and download.", font=(FONT_FAMILY, 12), text_color=TEXT_MUTED).pack()

        # State
        self.metadata = None
        self.selected_quality = None
        self.quality_btn_refs = []

    # ── Helpers ─────────────────────────────────────────
    def _set_status(self, msg, color=TEXT_MUTED):
        self.status_label.configure(text=msg, text_color=color)

    def _set_progress(self, value, label=""):
        self.progress_bar.set(value)
        self.progress_label.configure(text=label or f"{int(value * 100)}%")

    # ── Analyze ─────────────────────────────────────────
    def _on_analyze(self):
        url = self.url_entry.get().strip()
        if not url:
            return
        self.analyze_btn.configure(state="disabled", text="⏳ Analyzing...")
        self._set_status("Analyzing video...", PRIMARY)
        self.empty_state.pack_forget()
        self.info_card.pack_forget()
        self.quality_frame.pack_forget()
        self.download_btn.pack_forget()
        self.progress_frame.pack_forget()
        threading.Thread(target=self._analyze_thread, args=(url,), daemon=True).start()

    def _analyze_thread(self, url):
        try:
            vid, h = self._extract_id(url)
            meta = self._fetch_metadata(vid, h)
            self.metadata = meta
            self.after(0, self._show_results, meta)
        except Exception as e:
            self.after(0, self._set_status, f"❌ {e}", DESTRUCTIVE)
        finally:
            self.after(0, lambda: self.analyze_btn.configure(state="normal", text="🔍  Analyze"))

    def _extract_id(self, url):
        m = re.search(r"vimeo\.com/(?:video/)?(\d+)(?:/([a-f0-9]+))?", url)
        if not m:
            m = re.search(r"player\.vimeo\.com/video/(\d+)(?:\?.*?h=([a-f0-9]+))?", url)
        if not m:
            raise ValueError("Invalid Vimeo URL")
        return m.group(1), m.group(2)

    def _fetch_metadata(self, vid, h=None):
        config_url = f"https://player.vimeo.com/video/{vid}/config"
        if h:
            config_url += f"?h={h}"
        r = requests.get(config_url, headers={"Referer": "https://vimeo.com/"})
        r.raise_for_status()
        cfg = r.json()
        title = cfg.get("video", {}).get("title", "Untitled")
        duration = cfg.get("video", {}).get("duration", 0)
        thumb = cfg.get("video", {}).get("thumbs", {}).get("640", "")

        dash_url = None
        dash_default = cfg.get("request", {}).get("files", {}).get("dash", {})
        dash_url = dash_default.get("cdns", {})
        cdn = dash_default.get("default_cdn", "")
        if cdn and cdn in dash_url:
            dash_url = dash_url[cdn].get("avc_url") or dash_url[cdn].get("url", "")
        else:
            for v in (dash_default.get("cdns") or {}).values():
                dash_url = v.get("avc_url") or v.get("url", "")
                break

        if not dash_url:
            raise ValueError("Could not find video streams")

        mr = requests.get(dash_url, headers={"Referer": "https://vimeo.com/"})
        mr.raise_for_status()
        manifest = mr.json()
        base_url = dash_url.rsplit("/", 1)[0] + "/"

        qualities = []
        for v in manifest.get("video", []):
            qualities.append({
                "label": f'{v.get("height", "?")}p',
                "width": v.get("width", 0),
                "height": v.get("height", 0),
                "bitrate": v.get("bitrate", 0),
                "base_url": v.get("base_url", ""),
                "segments": v.get("segments", []),
                "init_segment": v.get("init_segment", ""),
            })
        qualities.sort(key=lambda q: q["height"], reverse=True)

        audio = None
        audio_list = manifest.get("audio", [])
        if audio_list:
            a = max(audio_list, key=lambda x: x.get("bitrate", 0))
            audio = {
                "base_url": a.get("base_url", ""),
                "segments": a.get("segments", []),
                "init_segment": a.get("init_segment", ""),
            }

        return {
            "title": title,
            "duration": duration,
            "thumbnail": thumb,
            "base_url": base_url,
            "qualities": qualities,
            "audio": audio,
        }

    # ── Show Results ────────────────────────────────────
    def _show_results(self, meta):
        self._set_status("✅ Video found!", SUCCESS)

        # Thumbnail
        try:
            r = requests.get(meta["thumbnail"], timeout=5)
            img = Image.open(BytesIO(r.content))
            img = img.resize((200, 112), Image.LANCZOS)
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(200, 112))
            self.thumb_label.configure(image=ctk_img, text="")
            self.thumb_label._ctk_image = ctk_img
        except:
            self.thumb_label.configure(text="🎬", font=(FONT_FAMILY, 40))

        self.title_label.configure(text=meta["title"])
        mins, secs = divmod(meta["duration"], 60)
        self.duration_label.configure(text=f"⏱ {int(mins)}:{int(secs):02d}")
        self.info_card.pack(fill="x", pady=(12, 0))

        # Quality buttons
        for w in self.quality_buttons_frame.winfo_children():
            w.destroy()
        self.quality_btn_refs = []
        self.selected_quality = None

        for i, q in enumerate(meta["qualities"]):
            btn = ctk.CTkButton(
                self.quality_buttons_frame, text=q["label"],
                width=80, height=36, corner_radius=8,
                font=(FONT_FAMILY, 12, "bold"),
                fg_color=BG_INPUT, hover_color=BORDER,
                border_width=1, border_color=BORDER, text_color=TEXT,
                command=lambda idx=i: self._select_quality(idx)
            )
            btn.pack(side="left", padx=(0, 8))
            self.quality_btn_refs.append(btn)

        if meta["qualities"]:
            self._select_quality(0)

        self.quality_frame.pack(fill="x", pady=(16, 0))
        self.download_btn.pack(fill="x", pady=(16, 0))

    def _select_quality(self, idx):
        self.selected_quality = idx
        for i, btn in enumerate(self.quality_btn_refs):
            if i == idx:
                btn.configure(fg_color=f"{PRIMARY}22", border_color=PRIMARY, text_color=PRIMARY)
            else:
                btn.configure(fg_color=BG_INPUT, border_color=BORDER, text_color=TEXT)

    # ── Download ────────────────────────────────────────
    def _on_download(self):
        if self.metadata is None or self.selected_quality is None:
            return
        self.download_btn.configure(state="disabled", text="⏳ Downloading...")
        self.progress_frame.pack(fill="x", pady=(12, 0))
        self._set_progress(0)
        threading.Thread(target=self._download_thread, daemon=True).start()

    def _download_thread(self):
        try:
            meta = self.metadata
            q = meta["qualities"][self.selected_quality]
            base = meta["base_url"]
            safe_title = re.sub(r'[^\w\s._-]', '', meta["title"]).replace(" ", "_")

            self.after(0, self._set_status, "Downloading video...", PRIMARY)
            video_data = self._download_segments(base, q, progress_offset=0, progress_scale=0.6)

            if meta["audio"]:
                self.after(0, self._set_status, "Downloading audio...", PRIMARY)
                audio_data = self._download_segments(base, meta["audio"], progress_offset=0.6, progress_scale=0.2)

                self.after(0, self._set_status, "Merging with FFmpeg...", PRIMARY)
                self.after(0, self._set_progress, 0.85, "Merging...")

                tmp = tempfile.gettempdir()
                v_path = os.path.join(tmp, "v_temp.mp4")
                a_path = os.path.join(tmp, "a_temp.m4a")
                out_path = os.path.join(os.path.expanduser("~"), "Downloads", f"{safe_title}_{q['label']}.mp4")
                os.makedirs(os.path.dirname(out_path), exist_ok=True)

                with open(v_path, "wb") as f: f.write(video_data)
                with open(a_path, "wb") as f: f.write(audio_data)

                subprocess.run([
                    "ffmpeg", "-y", "-i", v_path, "-i", a_path,
                    "-c:v", "copy", "-c:a", "copy", out_path
                ], capture_output=True, check=True)

                os.remove(v_path)
                os.remove(a_path)
            else:
                out_path = os.path.join(os.path.expanduser("~"), "Downloads", f"{safe_title}_{q['label']}.mp4")
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                with open(out_path, "wb") as f:
                    f.write(video_data)

            self.after(0, self._set_progress, 1.0, "100%")
            self.after(0, self._set_status, f"✅ Saved to {out_path}", SUCCESS)

        except Exception as e:
            self.after(0, self._set_status, f"❌ {e}", DESTRUCTIVE)
        finally:
            self.after(0, lambda: self.download_btn.configure(state="normal", text="⬇️  Download Video"))

    def _download_segments(self, base_url, track, progress_offset=0, progress_scale=1.0):
        import base64
        buf = bytearray()
        if track.get("init_segment"):
            buf.extend(base64.b64decode(track["init_segment"]))

        segments = track.get("segments", [])
        seg_base = base_url + track.get("base_url", "")
        total = len(segments)

        def fetch(i, seg):
            url = seg_base + seg["url"]
            r = requests.get(url, headers={"Referer": "https://vimeo.com/"}, timeout=30)
            r.raise_for_status()
            return i, r.content

        results = {}
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(fetch, i, s) for i, s in enumerate(segments)]
            for done_count, f in enumerate(as_completed(futures), 1):
                idx, data = f.result()
                results[idx] = data
                p = progress_offset + (done_count / total) * progress_scale
                self.after(0, self._set_progress, p)

        for i in range(total):
            buf.extend(results[i])
        return bytes(buf)


if __name__ == "__main__":
    app = VimeoDownloader()
    app.mainloop()
