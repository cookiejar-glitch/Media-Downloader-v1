#!/usr/bin/env python3
r"""
Media Converter - two simple tools in one window:

  * Video -> MP4 tab : turns any video into an MP4 that plays everywhere.
  * Audio tab        : turns any audio (or the sound from a video) into an OGG or
                       MP3 file (your choice) with the same name (song.wav -> song.ogg).
  * YouTube tab      : paste a video link and save it as an MP4 (or just the sound as MP3).

Pick a quality and see the final file size BEFORE converting:
  * Audio sizes are measured exactly (the file is really encoded in the background).
  * Video sizes are estimated from samples first (shown with "≈"), then the quality
    you picked is encoded for real in the background so its size becomes exact.
    Short videos (10 minutes or less) get exact sizes for every quality.
  * When you press Convert, a file that was already measured is simply moved into
    place - so the size you were shown is exactly the size you get.

Just double-click this file. The first time, it sets itself up automatically
(needs an internet connection once). Then drag files in and press Convert.

Requires Python 3.9+ (python.org). Uses PySide6 (the window) and FFmpeg
(the converting) - both are installed for you on first run.
To make a single .exe you can give to anyone, run build_exe.bat.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

APP_NAME = "Media Converter"
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
BELOW_NORMAL_PRIORITY = 0x00004000 if os.name == "nt" else 0

VIDEO_EXTS = {
    ".3g2", ".3gp", ".amv", ".asf", ".avi", ".divx", ".dv", ".f4v", ".flv", ".gif", ".h264",
    ".h265", ".hevc", ".m1v", ".m2t", ".m2ts", ".m2v", ".m4v", ".mjpeg", ".mkv", ".mod", ".mov",
    ".mp4", ".mpe", ".mpeg", ".mpg", ".mpv", ".mts", ".mxf", ".nsv", ".nut", ".ogm", ".ogv",
    ".qt", ".rm", ".rmvb", ".roq", ".tod", ".ts", ".vob", ".webm", ".wmv", ".wtv", ".y4m",
}
AUDIO_EXTS = {
    ".aac", ".ac3", ".adts", ".aif", ".aifc", ".aiff", ".alac", ".amr", ".ape", ".au", ".caf",
    ".dts", ".eac3", ".flac", ".m4a", ".m4b", ".mka", ".mp2", ".mp3", ".mpc", ".oga", ".ogg",
    ".opus", ".ra", ".snd", ".spx", ".tta", ".voc", ".w64", ".wav", ".weba", ".wma", ".wv",
}
IMAGE_FILTER = "Pictures (*.png *.jpg *.jpeg *.bmp *.gif *.webp)"

# (key, name, hint, value)   value = x264 CRF for video, Vorbis -q:a for audio
VIDEO_QUALITIES = [
    ("smallest", "Smallest", "Lower picture", 32),
    ("small", "Small", "Good for sharing", 28),
    ("balanced", "Balanced", "Recommended", 23),
    ("high", "High", "Very good picture", 20),
    ("best", "Best", "Close to original", 17),
]
AUDIO_QUALITIES = [
    ("smallest", "Smallest", "Voice & podcasts", 2),
    ("small", "Small", "Good", 4),
    ("balanced", "Balanced", "Very good", 6),
    ("high", "High", "Excellent", 8),
    ("highest", "Highest", "Best possible", 10),
]
MP3_QUALITIES = [                 # value = constant bitrate in kbps
    ("smallest", "Smallest", "Voice & podcasts", 96),
    ("small", "Small", "Good", 128),
    ("balanced", "Balanced", "Very good", 192),
    ("high", "High", "Excellent", 256),
    ("highest", "Highest", "Best possible", 320),
]
EXACT_ALL_VIDEO_LIMIT = 600      # seconds: videos up to this long get exact sizes for every quality


# ============================================================================ first-run setup

def _ensure_dependencies() -> None:
    """Install PySide6 (+ a bundled FFmpeg if none is on the PC) the first time it runs."""
    if getattr(sys, "frozen", False):
        return
    need = []
    try:
        import PySide6  # noqa: F401
    except ImportError:
        need.append("PySide6")
    if not shutil.which("ffmpeg"):
        try:
            import imageio_ffmpeg  # noqa: F401
        except ImportError:
            need.append("imageio-ffmpeg")
    opt = []
    for mod, pkg in (("yt_dlp", "yt-dlp"), ("yt_dlp_ejs", "yt-dlp-ejs")):   # for the YouTube tab
        try:
            __import__(mod)
        except ImportError:
            opt.append(pkg)
    if not need and not opt:
        return

    result: dict = {}

    def pip(pkgs):
        base = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q", *pkgs]
        err = ""
        for extra in ([], ["--user"]):
            r = subprocess.run(base + extra, capture_output=True, text=True,
                               creationflags=CREATE_NO_WINDOW)
            if r.returncode == 0:
                return True, ""
            err = (r.stderr or r.stdout)[-600:]
        return False, err

    def work():
        if need:
            ok, err = pip(need)
            result["ok"] = ok
            if not ok:
                result["err"] = err
        else:
            result["ok"] = True
        for p in opt:          # YouTube parts: nice to have, never block the converter
            pip([p])

    try:  # small "please wait" window while installing
        import tkinter as tk
        root = tk.Tk()
        root.title(APP_NAME)
        root.configure(bg="#14151b")
        root.geometry("440x150")
        root.resizable(False, False)
        tk.Label(root, text="Getting things ready...", fg="white", bg="#14151b",
                 font=("Segoe UI", 15, "bold")).pack(pady=(32, 8))
        tk.Label(root, text="This only happens the first time. It can take a minute or two.",
                 fg="#9a9db0", bg="#14151b", font=("Segoe UI", 10)).pack()
        t = threading.Thread(target=work, daemon=True)
        t.start()

        def check():
            if t.is_alive():
                root.after(250, check)
            else:
                root.destroy()
        root.after(250, check)
        root.mainloop()
        t.join()
    except Exception:
        print("First run: installing " + ", ".join(need) + " ...")
        work()

    if not result.get("ok"):
        msg = ("The converter couldn't finish setting itself up.\n"
               "Please check the internet connection and open it again.\n\n" + result.get("err", ""))
        try:
            import tkinter as tk
            from tkinter import messagebox
            r = tk.Tk()
            r.withdraw()
            messagebox.showerror(APP_NAME, msg)
        except Exception:
            print(msg)
        sys.exit(1)

    import importlib
    import site
    importlib.invalidate_caches()
    try:
        user_site = site.getusersitepackages()
        if user_site not in sys.path:
            sys.path.append(user_site)
    except Exception:
        pass


# ============================================================================ conversion engine

class ConvertError(Exception):
    pass


class Cancelled(Exception):
    pass


def find_ffmpeg() -> str | None:
    if getattr(sys, "frozen", False):                      # bundled inside the .exe
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        for c in sorted(base.glob("ffmpeg*")):
            if c.is_file():
                return str(c)
    here = Path(sys.argv[0] if getattr(sys, "frozen", False) else __file__).resolve().parent
    local = here / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if local.is_file():
        return str(local)
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg  # type: ignore
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


@dataclass
class MediaInfo:
    duration: float = 0.0
    vcodec: str | None = None
    vline: str = ""
    fps: float = 0.0
    acodec: str | None = None
    arate: int = 0
    alayout: str = ""


def probe(ffmpeg: str, path: Path) -> MediaInfo:
    r = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW)
    info = MediaInfo()
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    if m:
        h, mi, s = m.groups()
        info.duration = int(h) * 3600 + int(mi) * 60 + float(s)
    for line in r.stderr.splitlines():
        if "Stream #" not in line:
            continue
        if info.vcodec is None and ": Video:" in line and "attached pic" not in line:
            info.vcodec = line.split(": Video:", 1)[1].split()[0].rstrip(",")
            info.vline = line
            f = re.search(r"([\d.]+) fps", line) or re.search(r"([\d.]+) tbr", line)
            info.fps = float(f.group(1)) if f else 25.0
        elif info.acodec is None and ": Audio:" in line:
            rest = line.split(": Audio:", 1)[1]
            info.acodec = rest.split()[0].rstrip(",")
            parts = [p.strip() for p in rest.split(",")]
            for i, p in enumerate(parts):
                hz = re.fullmatch(r"(\d+) Hz", p)
                if hz:
                    info.arate = int(hz.group(1))
                    if i + 1 < len(parts):
                        info.alayout = parts[i + 1].split("(")[0].strip()
                    break
    return info


def _popen(cmd: list[str], low: bool, **kw) -> subprocess.Popen:
    """Start ffmpeg. low=True runs it at lower priority so background measuring doesn't slow the PC."""
    flags = CREATE_NO_WINDOW | (BELOW_NORMAL_PRIORITY if low else 0)
    pre = (lambda: os.nice(10)) if (low and os.name != "nt") else None
    return subprocess.Popen(cmd, creationflags=flags, preexec_fn=pre, **kw)


def _run_ffmpeg(cmd: list[str], duration: float, on_progress, cancel, on_start, low: bool = False) -> str | None:
    """Run one ffmpeg command with -progress on stdout. Returns None on success, an error text on
    failure. Raises Cancelled if cancel is set."""
    with tempfile.TemporaryFile() as errf:
        proc = _popen(cmd, low, stdout=subprocess.PIPE, stderr=errf, text=True,
                      encoding="utf-8", errors="replace")
        if on_start:
            on_start(proc)
        stopped = False
        for line in proc.stdout:  # type: ignore[union-attr]
            if cancel is not None and cancel.is_set():
                stopped = True
                proc.terminate()
                break
            if line.startswith(("out_time_us=", "out_time_ms=")) and on_progress and duration:
                val = line.split("=", 1)[1].strip()
                if val.isdigit():
                    on_progress(min(int(val) / 1_000_000 / duration, 0.999))
        proc.wait()
        if stopped:
            raise Cancelled()
        if proc.returncode == 0:
            return None
        errf.seek(0)
        tail = errf.read().decode("utf-8", "replace").strip().splitlines()[-3:]
        return " | ".join(tail) or f"ffmpeg exit code {proc.returncode}"


def _run_quiet(cmd: list[str], cancel, low: bool) -> None:
    """Run ffmpeg without progress; raise ConvertError on failure, Cancelled on cancel."""
    with tempfile.TemporaryFile() as errf:
        proc = _popen(cmd, low, stdout=subprocess.DEVNULL, stderr=errf)
        while True:
            try:
                proc.wait(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if cancel is not None and cancel.is_set():
                    proc.terminate()
                    proc.wait()
                    raise Cancelled()
        if proc.returncode != 0:
            errf.seek(0)
            raise ConvertError(errf.read().decode("utf-8", "replace").strip()[-300:] or "ffmpeg failed")


def _count_bytes(cmd: list[str], cancel, low: bool) -> int:
    """Run ffmpeg writing to stdout and count the bytes it produces (nothing is saved)."""
    proc = _popen(cmd, low, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    total = 0
    while True:
        chunk = proc.stdout.read(1 << 20)  # type: ignore[union-attr]
        if not chunk:
            break
        total += len(chunk)
        if cancel is not None and cancel.is_set():
            proc.terminate()
            proc.wait()
            raise Cancelled()
    proc.wait()
    if proc.returncode != 0:
        raise ConvertError("ffmpeg failed while measuring")
    return total


def _try_attempts(attempts: list[tuple[str, list[str]]], tmp: Path, dst: Path, duration: float,
                  on_progress, cancel, on_start, low: bool) -> str:
    dst.parent.mkdir(parents=True, exist_ok=True)
    last_err = "unknown problem"
    for label, cmd in attempts:
        try:
            err = _run_ffmpeg(cmd, duration, on_progress, cancel, on_start, low)
        except Cancelled:
            tmp.unlink(missing_ok=True)
            raise
        if err is None:
            os.replace(tmp, dst)
            if on_progress:
                on_progress(1.0)
            return label
        last_err = err
        tmp.unlink(missing_ok=True)
    raise ConvertError(last_err)


def _tmp_for(dst: Path) -> Path:
    return dst.with_name(dst.stem + ".converting" + dst.suffix)


# ---- video -> mp4

def video_encode_args(encoder: str, crf: int) -> list[str]:
    q = str(crf)
    if encoder == "h264_nvenc":
        a, pix = ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", q, "-b:v", "0"], "yuv420p"
    elif encoder == "h264_qsv":
        a, pix = ["-c:v", "h264_qsv", "-preset", "medium", "-global_quality", q], "nv12"
    elif encoder == "h264_amf":
        a, pix = ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "cqp", "-qp_i", q, "-qp_p", q], "yuv420p"
    elif encoder == "h264_videotoolbox":
        a, pix = ["-c:v", "h264_videotoolbox", "-q:v", str(max(1, min(100, 120 - crf * 2 - 15)))], "yuv420p"
    else:
        a, pix = ["-c:v", "libx264", "-preset", "medium", "-crf", q], "yuv420p"
    return a + ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-pix_fmt", pix]


_GPU_LOCK = threading.Lock()
_GPU_CACHE: dict = {}


def detect_gpu_encoder(ffmpeg: str) -> str | None:
    """Return the first hardware H.264 encoder that actually works on this PC, else None."""
    with _GPU_LOCK:
        if "enc" in _GPU_CACHE:
            return _GPU_CACHE["enc"]
        found = None
        for enc in ("h264_nvenc", "h264_qsv", "h264_amf", "h264_videotoolbox"):
            cmd = [ffmpeg, "-hide_banner", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=320x240:d=0.2",
                   *video_encode_args(enc, 23), "-f", "null", "-"]
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=20, creationflags=CREATE_NO_WINDOW)
                if r.returncode == 0:
                    found = enc
                    break
            except Exception:
                pass
        _GPU_CACHE["enc"] = found
        return found


def convert_video(ffmpeg: str, src: Path, dst: Path, crf: int = 23, gpu: str | None = None,
                  on_progress=None, cancel: threading.Event | None = None, on_start=None,
                  low: bool = False) -> str:
    """Any video -> MP4 (H.264 + AAC 192k) at the given quality."""
    info = probe(ffmpeg, src)
    if info.vcodec is None:
        raise ConvertError("No video found in this file.")
    tmp = _tmp_for(dst)

    def cmd(enc: str, audio_ok: bool) -> list[str]:
        c = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", str(src),
             "-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "0", *video_encode_args(enc, crf)]
        if info.acodec:
            c += ["-c:a", "aac", "-b:a", "192k"] + ([] if audio_ok else ["-ac", "2"])
        return c + ["-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(tmp)]

    attempts = [(enc, cmd(enc, True)) for enc in ([gpu] if gpu else []) + ["libx264"]]
    if info.acodec:
        attempts.append(("libx264", cmd("libx264", False)))     # odd audio channel layouts
    return _try_attempts(attempts, tmp, dst, info.duration, on_progress, cancel, on_start, low)


def _framecrc_sizes(path: Path) -> list[int]:
    """Packet sizes, in order, from an ffmpeg -f framecrc listing."""
    sizes = []
    for line in path.read_text("utf-8", "replace").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 5 and parts[4].isdigit():
            sizes.append(int(parts[4]))
    return sizes


def estimate_video_sizes(ffmpeg: str, src: Path, info: MediaInfo, crfs: dict[str, int],
                         encoder: str, cancel=None, low: bool = True) -> dict[str, int]:
    """Quick size estimate for several qualities at once.

    Short samples spread across the video are decoded once and encoded at every quality.
    Each sample is measured frame by frame: the keyframe it is forced to start with is
    removed and replaced by the share of keyframes a real encode would contain
    (one every 250 frames), then the result is scaled to the full length and the real
    audio size is added."""
    D = info.duration
    if D <= 0:
        raise ConvertError("Can't tell how long this video is.")
    K = 1 if D <= 40 else min(24, max(6, int(D / 10)))        # one sample per ~10 s, 6..24 samples
    L = min(4.0, D / K) if K > 1 else D
    keyint = 250
    tmpd = Path(tempfile.mkdtemp(prefix="mc_est_"))
    try:
        vbytes = {q: 0.0 for q in crfs}
        covered = 0.0
        for i in range(K):
            start = 0.0 if K == 1 else max(0.0, (i + 0.5) * D / K - L / 2)
            cmd = [ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-y",
                   "-ss", f"{start:.3f}", "-t", f"{L:.3f}", "-i", str(src)]
            for q, crf in crfs.items():
                cmd += ["-map", "0:v:0", *video_encode_args(encoder, crf), "-an", "-sn", "-dn",
                        "-f", "framecrc", str(tmpd / f"{q}_{i}.txt")]
            _run_quiet(cmd, cancel, low)
            n_frames = 0
            for q in crfs:
                sizes = _framecrc_sizes(tmpd / f"{q}_{i}.txt")
                if not sizes:
                    continue
                n_frames = len(sizes)
                if K > 1:
                    vbytes[q] += sum(sizes[1:]) + sizes[0] * (len(sizes) / keyint)
                else:
                    vbytes[q] += sum(sizes)
            covered += n_frames / (info.fps or 25)
        if covered <= 0:
            raise ConvertError("Couldn't sample this video.")
        scale = D / covered
        abytes = 0
        if info.acodec:
            abytes = _count_bytes([ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-i", str(src),
                                   "-map", "0:a:0", "-vn", "-c:a", "aac", "-b:a", "192k",
                                   "-f", "adts", "pipe:1"], cancel, low)
            abytes -= int(D * (info.arate or 48000) / 1024) * 7       # ADTS headers aren't in an MP4
        overhead = int(D * (info.fps or 25) * 12 + (D * 47 * 8 if info.acodec else 0) + 6000)
        return {q: int(vbytes[q] * scale) + abytes + overhead for q in crfs}
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)


# ---- audio -> ogg

# copy tags from both places they can live: on the audio stream (OGG, Opus) and on the file
KEEP_TAGS = ["-map_metadata:g", "0:s:a:0", "-map_metadata:g", "0:g"]

def convert_audio(ffmpeg: str, src: Path, dst: Path, quality: int = 10,
                  on_progress=None, cancel: threading.Event | None = None, on_start=None,
                  low: bool = False) -> str:
    """Any audio (or a video's sound) -> OGG Vorbis at the given quality (-q:a 0..10).
    Tags (title, artist, and loop points like LOOPSTART/LOOPLENGTH) are kept."""
    info = probe(ffmpeg, src)
    if info.acodec is None:
        raise ConvertError("No sound found in this file.")
    tmp = _tmp_for(dst)

    def cmd(extra: list[str]) -> list[str]:
        return [ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", str(src),
                "-map", "0:a:0", "-vn", "-sn", "-dn", *KEEP_TAGS,
                "-c:a", "libvorbis", "-q:a", str(quality), *extra,
                "-progress", "pipe:1", "-nostats", "-f", "ogg", str(tmp)]

    attempts = [("vorbis", cmd([])), ("vorbis", cmd(["-ac", "2", "-ar", "48000"]))]
    return _try_attempts(attempts, tmp, dst, info.duration, on_progress, cancel, on_start, low)


# ---- audio -> mp3

def convert_mp3(ffmpeg: str, src: Path, dst: Path, kbps: int = 320,
                on_progress=None, cancel: threading.Event | None = None, on_start=None,
                low: bool = False) -> str:
    """Any audio (or a video's sound) -> MP3 (LAME, constant bitrate). Tags are kept."""
    info = probe(ffmpeg, src)
    if info.acodec is None:
        raise ConvertError("No sound found in this file.")
    tmp = _tmp_for(dst)

    def cmd(extra: list[str]) -> list[str]:
        return [ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", str(src),
                "-map", "0:a:0", "-vn", "-sn", "-dn", *KEEP_TAGS,
                "-c:a", "libmp3lame", "-b:a", f"{kbps}k", *extra,
                "-id3v2_version", "3", "-write_id3v1", "1",
                "-progress", "pipe:1", "-nostats", "-f", "mp3", str(tmp)]

    # MP3 only does mono/stereo and up to 48 kHz, so odd files get a stereo / 44.1 kHz retry
    attempts = [("mp3", cmd([])), ("mp3", cmd(["-ac", "2", "-ar", "44100"]))]
    return _try_attempts(attempts, tmp, dst, info.duration, on_progress, cancel, on_start, low)


def encode(fmt: str, ffmpeg: str, src: Path, dst: Path, value: int, gpu: str | None = None, **kw) -> str:
    """Convert src to dst in the given output format ('mp4', 'ogg' or 'mp3') at quality value."""
    if fmt == "ogg":
        return convert_audio(ffmpeg, src, dst, value, **kw)
    if fmt == "mp3":
        return convert_mp3(ffmpeg, src, dst, value, **kw)
    return convert_video(ffmpeg, src, dst, value, gpu, **kw)


# ---- merge a video with a sound / music file

@dataclass
class MergeOptions:
    mode: str = "replace"        # "replace" = new sound only, "mix" = video's own sound + new sound
    length: str = "video"        # "video" = keep the video's length, "loop" = repeat the sound to fill it,
                                 # "shortest" = stop when the shorter one ends
    new_volume: int = 100        # % volume of the new sound
    video_volume: int = 100      # % volume of the video's own sound (mix mode)
    offset: float = 0.0          # the new sound starts this many seconds into the video
    music_start: float = 0.0     # skip this many seconds at the beginning of the new sound
    crf: int = 23                # picture quality, only used if the picture has to be re-made

    def key(self) -> tuple:
        return (self.mode, self.length, self.new_volume, self.video_volume,
                round(self.offset, 2), round(self.music_start, 2), self.crf)


def video_can_be_copied(info: MediaInfo) -> bool:
    """True if the picture can go into the MP4 untouched (fast, no quality loss)."""
    return info.vcodec == "h264" and re.search(r"\byuv420p\b", info.vline) is not None


def merge_output_length(vinfo: MediaInfo, ainfo: MediaInfo, opts: MergeOptions) -> float:
    if opts.length == "shortest":
        heard = max(0.0, ainfo.duration - opts.music_start)
        return max(0.1, min(vinfo.duration, heard + opts.offset))
    return vinfo.duration


def merge_av(ffmpeg: str, video: Path, audio: Path, dst: Path, opts: MergeOptions, gpu: str | None = None,
             on_progress=None, cancel: threading.Event | None = None, on_start=None, low: bool = False) -> str:
    """Put a new sound on a video (replacing or mixing with its own sound) and save an MP4."""
    vi, ai = probe(ffmpeg, video), probe(ffmpeg, audio)
    if vi.vcodec is None:
        raise ConvertError("The video file has no picture in it.")
    if ai.acodec is None:
        raise ConvertError("The sound file has no sound in it.")
    if ai.duration and opts.music_start >= ai.duration:
        raise ConvertError("You skipped past the end of the music - make 'skip the first … seconds' smaller.")
    if vi.duration <= 0:
        raise ConvertError("Can't tell how long the video is.")
    tmp = _tmp_for(dst)
    mix = opts.mode == "mix" and vi.acodec is not None
    norm = "aformat=sample_rates=48000:channel_layouts=stereo"

    new_chain = [norm]
    # skip the start of the music; when looping, repeat only the part that's left
    # (looping inside the filter is gap-free; very long songs use the lighter file-level loop)
    loop_in_filter = opts.length == "loop" and (opts.music_start > 0 or 0 < ai.duration <= 300)
    if opts.music_start > 0:
        new_chain.append(f"atrim=start={opts.music_start:.3f},asetpts=PTS-STARTPTS")
    if loop_in_filter:
        left = max(0.1, (ai.duration or 0) - opts.music_start)
        new_chain.append(f"aloop=loop=-1:size={int(left * 48000)},asetpts=N/SR/TB")
    if opts.offset > 0:
        new_chain.append(f"adelay={int(round(opts.offset * 1000))}:all=1")
    new_chain.append(f"volume={opts.new_volume / 100:.3f}")
    fc = ["[1:a:0]" + ",".join(new_chain) + "[na]"]
    if mix:
        fc.append(f"[0:a:0]{norm},volume={opts.video_volume / 100:.3f}[va]")
        fc.append("[va][na]amix=inputs=2:duration=longest:normalize=0:dropout_transition=0,apad[aout]")
    else:
        fc.append("[na]apad[aout]")

    # always cut at the exact length we worked out (ffmpeg's own "-shortest" is imprecise when
    # the picture is copied, and the sound is padded with silence so it never ends early)
    out_len = merge_output_length(vi, ai, opts)
    length_args = ["-t", f"{out_len:.3f}"]

    def cmd(venc: list[str]) -> list[str]:
        c = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", str(video)]
        if opts.length == "loop" and not loop_in_filter:
            c += ["-stream_loop", "-1"]
        c += ["-i", str(audio), "-filter_complex", ";".join(fc),
              "-map", "0:v:0", "-map", "[aout]", "-map_metadata", "0", *venc,
              "-c:a", "aac", "-b:a", "192k", *length_args,
              "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(tmp)]
        return c

    attempts = []
    if video_can_be_copied(vi):
        attempts.append(("copy", cmd(["-c:v", "copy"])))
    for enc in ([gpu] if gpu else []) + ["libx264"]:
        attempts.append((enc, cmd(video_encode_args(enc, opts.crf))))
    return _try_attempts(attempts, tmp, dst, out_len, on_progress, cancel, on_start, low)


def estimate_merge_size(ffmpeg: str, video: Path, vinfo: MediaInfo, ainfo: MediaInfo, opts: MergeOptions,
                        encoder: str, cancel=None) -> int:
    """Quick estimate of the merged file's size (the exact size is measured separately)."""
    out_len = merge_output_length(vinfo, ainfo, opts)
    picture_only = MediaInfo(**{**asdict(vinfo), "acodec": None})
    if video_can_be_copied(vinfo):
        vbytes = _count_bytes([ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-i", str(video),
                               "-map", "0:v:0", "-c:v", "copy", "-an", "-t", f"{out_len:.3f}",
                               "-f", "h264", "pipe:1"], cancel, True)
    else:
        vbytes = estimate_video_sizes(ffmpeg, video, picture_only, {"q": opts.crf}, encoder, cancel)["q"]
        vbytes = int(vbytes * out_len / vinfo.duration) if vinfo.duration else vbytes
    return vbytes + int(out_len * 192000 / 8) + int(out_len * 47 * 8) + 6000


# ---- file helpers

def place_file(ready: Path, dst: Path) -> None:
    """Move an already-converted file to its destination (copying if it's another drive)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(ready, dst)
        return
    except OSError:
        pass
    tmp = _tmp_for(dst)
    shutil.copyfile(ready, tmp)
    os.replace(tmp, dst)
    ready.unlink(missing_ok=True)


def unique_path(p: Path, reserved: set) -> Path:
    if not p.exists() and p not in reserved:
        return p
    n = 2
    while True:
        c = p.with_name(f"{p.stem} ({n}){p.suffix}")
        if not c.exists() and c not in reserved:
            return c
        n += 1


def plan_outputs(sources: list[Path], folder: Path | None, if_exists: str, ext: str) -> list[Path]:
    """Output file for each source: same name, new extension. folder=None = next to the original."""
    reserved: set = set()
    out = []
    for src in sources:
        d = folder or src.parent
        dst = d / (src.stem + ext)
        if dst.resolve() == src.resolve():                    # never overwrite the original
            dst = d / (src.stem + " (converted)" + ext)
        if if_exists != "replace" or dst in reserved:
            dst = unique_path(dst, reserved)
        reserved.add(dst)
        out.append(dst)
    return out


def expand_paths(paths, exts: set, strict: bool = True) -> tuple[list[Path], int]:
    """Turn dropped files/folders into a list of matching files. Returns (files, skipped_count)."""
    found, skipped = [], 0
    for p in map(Path, paths):
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and f.suffix.lower() in exts and ".converting." not in f.name:
                    found.append(f)
        elif p.is_file():
            if not strict or p.suffix.lower() in exts:
                found.append(p)
            else:
                skipped += 1
    return found, skipped


def fmt_size(n: float) -> str:
    """Two decimals, same units Windows uses (1 MB = 1024 KB): 2158123456 -> '2.01 GB'."""
    if n < 1024:
        return f"{int(n)} bytes"
    for unit in ("KB", "MB", "GB", "TB"):
        n /= 1024
        if n < 1024 or unit == "TB":
            return f"{n:.2f} {unit}"
    return ""


def human_time(sec: float) -> str:
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def make_thumbnail(ffmpeg: str, src: Path, duration: float) -> str | None:
    out = Path(tempfile.gettempdir()) / f"mc_thumb_{abs(hash(str(src)))}.jpg"
    at = "1" if duration > 2 else "0"
    r = subprocess.run([ffmpeg, "-hide_banner", "-v", "error", "-y", "-ss", at, "-i", str(src),
                        "-frames:v", "1", "-vf", "scale=240:-2", str(out)],
                       capture_output=True, creationflags=CREATE_NO_WINDOW)
    return str(out) if r.returncode == 0 and out.exists() else None


CACHE_ROOT = Path(tempfile.gettempdir()) / "MediaConverterCache"


def clean_old_cache() -> None:
    try:
        for d in CACHE_ROOT.iterdir():
            if time.time() - d.stat().st_mtime > 12 * 3600:
                shutil.rmtree(d, ignore_errors=True)
    except OSError:
        pass


# ============================================================================ size preview service

@dataclass
class Item:
    rid: int
    path: Path
    info: MediaInfo | None = None
    bad: str = ""                                      # reason it can't be converted
    estimated: bool = False
    sizes: dict = field(default_factory=dict)          # quality -> (bytes, exact) ; bytes -1 = failed
    cached: dict = field(default_factory=dict)         # quality -> finished file in the cache
    removed: bool = False
    done: bool = False


class SizeMeasurer:
    """Background worker that works out the final size of every file at every quality.
    Thread-safe; the window calls add/remove/select/pause and reads snapshots.
    notify(rid) is called (from the worker thread) whenever something changed."""

    def __init__(self, fmt: str, ffmpeg: str | None, qualities, selected: str, use_gpu: bool, notify):
        self.fmt, self.ffmpeg = fmt, ffmpeg
        self.audio = fmt != "mp4"
        self.qvalues = {k: v for k, _n, _h, v in qualities}
        self.qorder = [k for k, *_ in qualities]
        self.selected, self.use_gpu = selected, use_gpu
        self.notify = notify
        self.lock = threading.Lock()
        self.items: dict[int, Item] = {}
        self.order: list[int] = []
        self.paused = False
        self.alive = True
        self.wake = threading.Event()
        self.cur: tuple | None = None
        self.cur_cancel = threading.Event()
        self.encoder: str | None = None
        self.encoder_ready = False
        self.cache_dir = CACHE_ROOT / f"{os.getpid()}_{fmt}"
        self.ext = "." + fmt
        self.thread = threading.Thread(target=self._loop, daemon=True)
        if ffmpeg:
            self.thread.start()

    # ---- called from the window
    def add(self, rid: int, path: Path) -> None:
        with self.lock:
            self.items[rid] = Item(rid, path)
            self.order.append(rid)
        self.wake.set()

    def _drop_cache(self, it: Item, keep: Path | None = None) -> None:
        for p in list(it.cached.values()):
            if p != keep:
                p.unlink(missing_ok=True)
        it.cached.clear()

    def remove(self, rid: int) -> None:
        with self.lock:
            it = self.items.get(rid)
            if it is None:
                return
            it.removed = True
            if self.cur and self.cur[1] is it:
                self.cur_cancel.set()
            self._drop_cache(it)

    def mark_done(self, rid: int, kept: Path | None = None) -> None:
        with self.lock:
            it = self.items.get(rid)
            if it is not None:
                it.done = True
                if self.cur and self.cur[1] is it:
                    self.cur_cancel.set()
                self._drop_cache(it, keep=kept)

    def select(self, q: str) -> None:
        with self.lock:
            self.selected = q
            if self.cur and self.cur[0] == "exact" and self.cur[2] != q:
                self.cur_cancel.set()          # do the newly picked quality first
        self.wake.set()

    def pause(self) -> None:
        with self.lock:
            self.paused = True
            self.cur_cancel.set()

    def resume(self) -> None:
        with self.lock:
            self.paused = False
        self.wake.set()

    def set_gpu(self, use_gpu: bool) -> None:
        """Different encoder = different sizes, so start measuring again."""
        with self.lock:
            if use_gpu == self.use_gpu:
                return
            self.use_gpu = use_gpu
            self.encoder_ready = False
            for it in self.items.values():
                it.sizes.clear()
                it.estimated = False
                self._drop_cache(it)
            self.cur_cancel.set()
        for rid in list(self.items):
            self.notify(rid)
        self.wake.set()

    def snapshot(self, rid: int) -> tuple[dict, str]:
        with self.lock:
            it = self.items.get(rid)
            return (dict(it.sizes), it.bad) if it else ({}, "")

    def take_cached(self, rid: int, q: str) -> Path | None:
        with self.lock:
            it = self.items.get(rid)
            p = it.cached.pop(q, None) if it else None
        return p if p is not None and p.exists() else None

    def is_busy(self) -> bool:
        with self.lock:
            return self.cur is not None

    def shutdown(self) -> None:
        with self.lock:
            self.alive = False
            self.cur_cancel.set()
        self.wake.set()
        if self.thread.is_alive():
            self.thread.join(timeout=3)
        shutil.rmtree(self.cache_dir, ignore_errors=True)

    # ---- worker thread
    def _pick(self):
        with self.lock:
            if self.paused or not self.alive:
                return None
            live = [self.items[r] for r in self.order
                    if not self.items[r].removed and not self.items[r].done and not self.items[r].bad]
            for it in live:
                if it.info is None:
                    return ("probe", it)
            if not self.audio:
                for it in live:
                    if not it.estimated:
                        return ("estimate", it)
            for q in [self.selected] + [k for k in self.qorder if k != self.selected]:
                for it in live:
                    have = it.sizes.get(q)
                    if have and have[1]:
                        continue
                    if (q != self.selected and not self.audio and it.info is not None
                            and it.info.duration > EXACT_ALL_VIDEO_LIMIT):
                        continue
                    return ("exact", it, q)
        return None

    def _loop(self) -> None:
        while self.alive:
            task = self._pick()
            if task is None:
                self.wake.wait(0.5)
                self.wake.clear()
                continue
            cancel = threading.Event()
            with self.lock:
                self.cur, self.cur_cancel = task, cancel
            it: Item = task[1]
            try:
                self._do(task, cancel)
            except Cancelled:
                pass
            except Exception as e:
                with self.lock:
                    if task[0] == "probe":
                        it.bad = str(e) or "Couldn't read this file."
                    elif task[0] == "estimate":
                        it.estimated = True
                    else:
                        it.sizes[task[2]] = (-1, True)
                self.notify(it.rid)
            finally:
                with self.lock:
                    self.cur = None

    def _gpu_encoder(self) -> str:
        if not self.encoder_ready:
            self.encoder = detect_gpu_encoder(self.ffmpeg) if self.use_gpu else None
            self.encoder_ready = True
        return self.encoder or "libx264"

    def _do(self, task, cancel: threading.Event) -> None:
        kind, it = task[0], task[1]
        ff = self.ffmpeg
        if kind == "probe":
            info = probe(ff, it.path)
            with self.lock:
                it.info = info
                if self.audio and not info.acodec:
                    it.bad = "No sound found in this file."
                if not self.audio and not info.vcodec:
                    it.bad = "No video found in this file."
            self.notify(it.rid)
            return

        if kind == "estimate":
            enc = self._gpu_encoder()
            est = estimate_video_sizes(ff, it.path, it.info, self.qvalues, enc, cancel)
            with self.lock:
                for q, b in est.items():
                    if not (q in it.sizes and it.sizes[q][1]):
                        it.sizes[q] = (b, False)
                it.estimated = True
            self.notify(it.rid)
            return

        q = task[2]
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        out = self.cache_dir / f"{it.rid}_{q}{self.ext}"
        gpu = None
        if not self.audio:
            enc = self._gpu_encoder()
            gpu = None if enc == "libx264" else enc
        encode(self.fmt, ff, it.path, out, self.qvalues[q], gpu, cancel=cancel, low=True)
        size = out.stat().st_size
        try:
            free = shutil.disk_usage(self.cache_dir).free
        except OSError:
            free = 0
        with self.lock:
            it.sizes[q] = (size, True)
            keep = (not it.removed and not it.done and q == self.selected and free > 2 * 1024 ** 3)
            if keep:
                it.cached[q] = out
        if not keep:
            out.unlink(missing_ok=True)
        self.notify(it.rid)


# ============================================================================ settings

def config_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / "MediaConverter"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class Settings:
    wallpaper: str = ""
    wallpaper_dim: int = 55          # how much the wallpaper is darkened, 0-85 %
    save_mode: str = "beside"        # "beside" = next to original, "folder" = save_folder
    save_folder: str = ""
    if_exists: str = "rename"        # "rename" (keep both) or "replace"
    video_quality: str = "balanced"
    use_gpu: bool = True
    audio_quality: str = "highest"
    mp3_quality: str = "highest"
    audio_format: str = "ogg"        # the audio tab makes "ogg" or "mp3"
    merge_mode: str = "replace"      # merge tab: "replace" or "mix"
    merge_length: str = "video"
    merge_new_volume: int = 100
    merge_video_volume: int = 100
    open_folder_when_done: bool = False
    last_dir: str = ""
    last_tab: int = 0
    yt_format: str = "mp4"           # YouTube tab: "mp4" or "mp3"
    yt_quality: int = 0              # YouTube tab: 0 = best, else the biggest height (1080/720/480)

    @classmethod
    def load(cls) -> "Settings":
        try:
            data = json.loads((config_dir() / "settings.json").read_text("utf-8"))
            names = {f.name for f in fields(cls)}
            s = cls(**{k: v for k, v in data.items() if k in names})
        except Exception:
            s = cls()
        if s.video_quality not in {k for k, *_ in VIDEO_QUALITIES}:
            s.video_quality = "balanced"
        if s.audio_quality not in {k for k, *_ in AUDIO_QUALITIES}:
            s.audio_quality = "highest"
        if s.mp3_quality not in {k for k, *_ in MP3_QUALITIES}:
            s.mp3_quality = "highest"
        if s.audio_format not in ("ogg", "mp3"):
            s.audio_format = "ogg"
        if s.yt_format not in ("mp4", "mp3"):
            s.yt_format = "mp4"
        if not isinstance(s.yt_quality, int):
            s.yt_quality = 0
        return s

    def save(self) -> None:
        try:
            (config_dir() / "settings.json").write_text(json.dumps(asdict(self), indent=2), "utf-8")
        except Exception:
            pass


# ============================================================================ downloader helpers

def downloads_dir() -> Path:
    d = Path.home() / "Downloads"
    return d if d.is_dir() else Path.home()


def clean_error(e: Exception) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", str(e)).replace("ERROR: ", "").strip()


def deno_ready() -> bool:
    """YouTube needs the small 'Deno' helper. Look for it (also where winget puts it)."""
    for d in (Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links",
              Path.home() / ".deno" / "bin"):
        if d.is_dir() and str(d) not in os.environ.get("PATH", ""):
            os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + str(d)
    return shutil.which("deno") is not None


def ytdlp_ffmpeg_location(ffmpeg: str) -> str:
    """yt-dlp wants a folder holding a file literally called ffmpeg; make one if needed."""
    p = Path(ffmpeg)
    if p.stem.lower() == "ffmpeg":
        return str(p.parent)
    d = config_dir() / "bin"
    t = d / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    try:
        d.mkdir(parents=True, exist_ok=True)
        if not t.exists() or t.stat().st_size != p.stat().st_size:
            shutil.copy2(p, t)
            t.chmod(0o755)
        return str(d)
    except OSError:
        return str(p)


DL_QUALITIES = [("Best available", 0), ("Up to 1080p", 1080), ("Up to 720p", 720), ("Up to 480p", 480)]


def format_for(cap: int) -> str:
    c = f"[height<={cap}]" if cap else ""
    return f"bv*[ext=mp4]{c}+ba[ext=m4a]/bv*{c}+ba/b{c}"


# ============================================================================ window

if __name__ == "__main__":
    _ensure_dependencies()

from PySide6.QtCore import QObject, QPointF, QRectF, QSize, Qt, QThread, QTimer, QUrl, Signal  # noqa: E402
from PySide6.QtGui import (QColor, QDesktopServices, QIcon, QImage, QLinearGradient,  # noqa: E402
                           QPainter, QPainterPath, QPalette, QPen, QPixmap, QPolygonF)
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox,  # noqa: E402
                               QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QMainWindow, QMessageBox, QProgressBar, QPushButton,
                               QRadioButton, QScrollArea, QSizePolicy, QSlider,
                               QTabWidget, QVBoxLayout, QWidget, QDoubleSpinBox, QGridLayout, QLineEdit)

ACCENT = "#7c6cff"
ACCENT_HOVER = "#9184ff"
GOOD = "#4fd18b"
BAD = "#ff6b7a"
BG = "#111218"

QSS = f"""
* {{ font-family: "Segoe UI", "SF Pro Text", "Helvetica Neue", "Noto Sans", Arial; font-size: 14px; color: #e9eaf2; }}
QMainWindow, QDialog {{ background: {BG}; }}
QToolTip {{ background: #1d1f29; color: #e9eaf2; border: 1px solid #2c2f3d; padding: 6px; border-radius: 6px; }}
QLabel {{ background: transparent; }}
QLabel#Title {{ font-size: 24px; font-weight: 700; }}
QLabel#Subtle {{ color: #a2a5b8; }}
QLabel#Section {{ font-size: 16px; font-weight: 700; color: #ffffff; padding-top: 4px; }}
QLabel#DropTitle {{ font-size: 21px; font-weight: 700; }}
QLabel#RowName {{ font-size: 15px; font-weight: 600; }}
QLabel#ChipName {{ font-size: 14px; font-weight: 700; }}
QLabel#ChipSize {{ font-size: 17px; font-weight: 700; }}
QLabel#ChipHint {{ font-size: 12px; color: #a2a5b8; }}
QWidget#Page, QWidget#ListHolder, QWidget#SettingsBody, QStackedWidget {{ background: transparent; }}
QTabWidget::pane {{ border: none; background: transparent; top: 0px; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{ background: rgba(26,28,38,0.82); border: 1px solid rgba(255,255,255,0.08); color: #a2a5b8;
               padding: 10px 24px; margin-right: 10px; border-radius: 12px; font-size: 15px; font-weight: 700; }}
QTabBar::tab:selected {{ background: {ACCENT}; border-color: {ACCENT}; color: white; }}
QTabBar::tab:hover:!selected {{ background: rgba(255,255,255,0.13); color: white; }}
QFrame#Card {{ background: rgba(26,28,38,0.86); border: 1px solid rgba(255,255,255,0.07); border-radius: 14px; }}
QFrame#Chip {{ background: rgba(26,28,38,0.86); border: 1px solid rgba(255,255,255,0.09); border-radius: 12px; }}
QFrame#Chip:hover {{ border-color: rgba(124,108,255,0.65); }}
QFrame#Chip[selected="true"] {{ background: rgba(124,108,255,0.28); border: 2px solid {ACCENT}; }}
QFrame#DropZone {{ background: rgba(26,28,38,0.78); border: 2px dashed rgba(255,255,255,0.22); border-radius: 18px; }}
QFrame#DropZone:hover {{ border-color: rgba(124,108,255,0.75); }}
QFrame#DropZone[hover="true"] {{ border-color: {ACCENT}; background: rgba(124,108,255,0.20); }}
QPushButton {{ background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.12);
              border-radius: 10px; padding: 9px 18px; }}
QPushButton:hover {{ background: rgba(255,255,255,0.15); }}
QPushButton:pressed {{ background: rgba(255,255,255,0.05); }}
QPushButton:disabled {{ color: #6c6f82; background: rgba(255,255,255,0.04); }}
QPushButton#Primary {{ background: {ACCENT}; border: none; font-size: 16px; font-weight: 700; padding: 12px 30px; color: white; }}
QPushButton#Primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#Primary:disabled {{ background: #3b3a5c; color: #8d8ca8; }}
QPushButton#Stop {{ background: #d9465a; border: none; font-size: 16px; font-weight: 700; padding: 12px 30px; color: white; }}
QPushButton#Stop:hover {{ background: #ea5d70; }}
QPushButton#Seg {{ padding: 8px 20px; font-weight: 700; border-radius: 10px; }}
QPushButton#Seg:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: white; }}
QPushButton#Flat {{ background: transparent; border: none; color: {ACCENT_HOVER}; padding: 2px 4px; font-weight: 600; }}
QPushButton#Flat:hover {{ color: #b7aeff; }}
QPushButton#Round {{ background: transparent; border: none; border-radius: 16px; padding: 0; font-size: 16px; color: #a2a5b8; }}
QPushButton#Round:hover {{ background: rgba(255,255,255,0.12); color: white; }}
QProgressBar {{ background: rgba(255,255,255,0.10); border: none; border-radius: 3px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: rgba(255,255,255,0.20); border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QComboBox {{ background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.14); border-radius: 8px; padding: 7px 12px; min-width: 280px; }}
QComboBox:hover {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{ background: #1d1f29; border: 1px solid #2c2f3d; selection-background-color: {ACCENT}; outline: none; padding: 4px; }}
QSlider::groove:horizontal {{ height: 6px; background: rgba(255,255,255,0.14); border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 3px; }}
QDoubleSpinBox {{ background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.14); border-radius: 8px; padding: 6px 8px; }}
QDoubleSpinBox:hover {{ border-color: {ACCENT}; }}
QSlider::handle:horizontal {{ background: white; width: 18px; height: 18px; margin: -6px 0; border-radius: 9px; }}
QRadioButton, QCheckBox {{ spacing: 10px; padding: 3px 0; }}
QLineEdit {{ background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.14); border-radius: 10px; padding: 10px 14px; selection-background-color: {ACCENT}; }}
QLineEdit:focus {{ border-color: {ACCENT}; }}
QMessageBox QLabel {{ font-size: 15px; }}
"""


def dark_palette() -> QPalette:
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: BG, QPalette.ColorRole.WindowText: "#e9eaf2",
        QPalette.ColorRole.Base: "#1b1d26", QPalette.ColorRole.AlternateBase: "#22242f",
        QPalette.ColorRole.Text: "#e9eaf2", QPalette.ColorRole.Button: "#242633",
        QPalette.ColorRole.ButtonText: "#e9eaf2", QPalette.ColorRole.Highlight: ACCENT,
        QPalette.ColorRole.HighlightedText: "#ffffff", QPalette.ColorRole.ToolTipBase: "#1d1f29",
        QPalette.ColorRole.ToolTipText: "#e9eaf2", QPalette.ColorRole.PlaceholderText: "#6c6f82",
        QPalette.ColorRole.Link: ACCENT_HOVER,
    }
    for role, color in roles.items():
        pal.setColor(role, QColor(color))
    return pal


def draw_note(p: QPainter, x: float, y: float, s: float, color: QColor) -> None:
    """A simple double music note inside the box (x, y, s, s)."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    r = s * 0.13
    p.drawEllipse(QPointF(x + s * 0.30, y + s * 0.72), r * 1.15, r)
    p.drawEllipse(QPointF(x + s * 0.70, y + s * 0.62), r * 1.15, r)
    w = s * 0.07
    p.drawRect(QRectF(x + s * 0.30 + r * 0.95, y + s * 0.26, w, s * 0.46))
    p.drawRect(QRectF(x + s * 0.70 + r * 0.95, y + s * 0.16, w, s * 0.46))
    beam = QPainterPath()
    x1, x2 = x + s * 0.30 + r * 0.95, x + s * 0.70 + r * 0.95 + w
    beam.moveTo(x1, y + s * 0.26)
    beam.lineTo(x2, y + s * 0.16)
    beam.lineTo(x2, y + s * 0.27)
    beam.lineTo(x1, y + s * 0.37)
    beam.closeSubpath()
    p.drawPath(beam)


def make_app_icon(size: int = 256) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), size * 0.24, size * 0.24)
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0, QColor("#9a7bff"))
    grad.setColorAt(1, QColor("#4f8dff"))
    p.fillPath(path, grad)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("white"))
    p.drawPolygon(QPolygonF([QPointF(size * 0.24, size * 0.22), QPointF(size * 0.24, size * 0.62),
                             QPointF(size * 0.56, size * 0.42)]))
    draw_note(p, size * 0.44, size * 0.42, size * 0.52, QColor(255, 255, 255, 230))
    p.end()
    return pm


def reveal_in_folder(path: Path) -> None:
    try:
        if os.name == "nt":
            subprocess.Popen(f'explorer /select,"{path}"')
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
            return
    except Exception:
        pass
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


def repolish(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


# ---------------------------------------------------------------------------- what each tab does

@dataclass
class Kind:
    key: str
    tab_label: str
    out_ext: str
    accept: set
    noun: str
    nouns: str
    drop_title: str
    dialog_title: str
    fail_hint: str
    audio: bool
    qualities: list
    fmt: str = "mp4"
    setting: str = "video_quality"     # which Settings field remembers this tab's quality
    type_name: str = "MP4 video"


VIDEO_KIND = Kind("video", "🎬   Video → MP4", ".mp4", VIDEO_EXTS, "video", "videos",
                  "Drag and drop your videos here", "Choose videos to convert",
                  "This file may be damaged, or it isn't a video.", False, VIDEO_QUALITIES)
AUDIO_KIND = Kind("audio", "🎵   Audio → OGG / MP3", ".ogg", AUDIO_EXTS | (VIDEO_EXTS - {".gif"}),
                  "audio file", "audio files",
                  "Drag and drop your music or sounds here", "Choose audio files to convert",
                  "This file may be damaged, or it has no sound.", True, AUDIO_QUALITIES,
                  "ogg", "audio_quality", "OGG audio")
MP3_KIND = Kind("mp3", "🎵   Audio → OGG / MP3", ".mp3", AUDIO_EXTS | (VIDEO_EXTS - {".gif"}),
                "audio file", "audio files",
                "Drag and drop your music or sounds here", "Choose audio files to convert",
                "This file may be damaged, or it has no sound.", True, MP3_QUALITIES,
                "mp3", "mp3_quality", "MP3 audio")
MERGE_KIND = Kind("merge", "🎞   Merge", ".mp4", VIDEO_EXTS | AUDIO_EXTS, "video", "videos",
                  "", "", "", False, [])


# ---------------------------------------------------------------------------- small widgets

class Background(QWidget):
    """Paints the wallpaper (cover-fit) with a dark overlay behind everything."""

    def __init__(self):
        super().__init__()
        self._src: QPixmap | None = None
        self._scaled: QPixmap | None = None
        self._scaled_for = QSize()
        self.dim = 55

    def set_wallpaper(self, path: str, dim: int) -> bool:
        self.dim = dim
        pm = QPixmap(path) if path else QPixmap()
        self._src = None if pm.isNull() else pm
        self._scaled = None
        self.update()
        return self._src is not None

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG))
        if self._src is not None:
            if self._scaled is None or self._scaled_for != self.size():
                self._scaled = self._src.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                                Qt.TransformationMode.SmoothTransformation)
                self._scaled_for = self.size()
            x = (self.width() - self._scaled.width()) // 2
            y = (self.height() - self._scaled.height()) // 2
            p.drawPixmap(x, y, self._scaled)
            p.fillRect(self.rect(), QColor(10, 11, 16, int(255 * self.dim / 100)))
        p.end()


class DropIcon(QWidget):
    def __init__(self, size: int = 76):
        super().__init__()
        self.setFixedSize(size, size)

    def paintEvent(self, _e):
        s = self.width()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(124, 108, 255, 55))
        p.drawEllipse(QRectF(0, 0, s, s))
        pen = QPen(QColor(ACCENT_HOVER), s * 0.06)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        cx = s / 2
        p.drawLine(QPointF(cx, s * 0.24), QPointF(cx, s * 0.58))                 # arrow shaft
        p.drawPolyline(QPolygonF([QPointF(cx - s * 0.13, s * 0.45), QPointF(cx, s * 0.58),
                                  QPointF(cx + s * 0.13, s * 0.45)]))           # arrow head
        p.drawPolyline(QPolygonF([QPointF(s * 0.27, s * 0.60), QPointF(s * 0.27, s * 0.73),
                                  QPointF(s * 0.73, s * 0.73), QPointF(s * 0.73, s * 0.60)]))  # tray
        p.end()


class DropZone(QFrame):
    clicked = Signal()

    def __init__(self, kind: Kind, sub: str | None = None, small: str | None = None, tip: str | None = None):
        super().__init__()
        self.setObjectName("DropZone")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tip or f"Click to choose {kind.nouns}, or drag them here")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)

        self.big = QWidget()
        bl = QVBoxLayout(self.big)
        bl.setSpacing(10)
        bl.addStretch(1)
        icon = DropIcon()
        bl.addWidget(icon, 0, Qt.AlignmentFlag.AlignHCenter)
        t = QLabel(kind.drop_title)
        t.setObjectName("DropTitle")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        s = QLabel(sub or "or click anywhere in this box to choose them")
        s.setObjectName("Subtle")
        s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bl.addWidget(t)
        bl.addWidget(s)
        bl.addStretch(1)

        self.small = QLabel(small or f"+   Add more {kind.nouns}  —  click here, or drop them anywhere")
        self.small.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.small.setObjectName("Subtle")

        lay.addWidget(self.big)
        lay.addWidget(self.small)
        for w in (self.big, self.small, icon, t, s):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.set_compact(False)

    def set_compact(self, compact: bool) -> None:
        self.big.setVisible(not compact)
        self.small.setVisible(compact)
        if compact:
            self.setFixedHeight(54)
        else:
            self.setMinimumHeight(220)
            self.setMaximumHeight(16777215)

    def set_hover(self, on: bool) -> None:
        self.setProperty("hover", "true" if on else "false")
        repolish(self)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()


class ElideLabel(QLabel):
    """Label that shortens long file names with '...' in the middle."""

    def __init__(self, text: str = ""):
        super().__init__()
        self._full = text
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(60)
        self._refresh()

    def setFullText(self, text: str) -> None:
        self._full = text
        self._refresh()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._refresh()

    def _refresh(self) -> None:
        self.setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideMiddle,
                                                   max(self.width(), 60)))


class Thumb(QWidget):
    def __init__(self, audio: bool, w: int = 104, h: int = 60):
        super().__init__()
        self.setFixedSize(w, h)
        self.audio = audio
        self.pm: QPixmap | None = None

    def set_image(self, img: QImage | None) -> None:
        self.pm = QPixmap.fromImage(img) if img is not None and not img.isNull() else None
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 9, 9)
        p.setClipPath(path)
        p.fillRect(self.rect(), QColor("#232533"))
        if self.audio:
            grad = QLinearGradient(0, 0, self.width(), self.height())
            grad.setColorAt(0, QColor(124, 108, 255, 120))
            grad.setColorAt(1, QColor(79, 141, 255, 70))
            p.fillRect(self.rect(), grad)
            s = self.height() * 0.8
            draw_note(p, (self.width() - s) / 2, (self.height() - s) / 2, s, QColor(255, 255, 255, 210))
        elif self.pm is not None:
            sc = self.pm.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap((self.width() - sc.width()) // 2, (self.height() - sc.height()) // 2, sc)
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 70))
            cx, cy = self.width() / 2, self.height() / 2
            p.drawPolygon(QPolygonF([QPointF(cx - 7, cy - 10), QPointF(cx - 7, cy + 10),
                                     QPointF(cx + 10, cy)]))
        p.end()


class QualityChip(QFrame):
    clicked = Signal(str)

    def __init__(self, key: str, name: str, hint: str):
        super().__init__()
        self.setObjectName("Chip")
        self.key = key
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 9, 12, 9)
        v.setSpacing(1)
        self.name_lbl = QLabel(name)
        self.name_lbl.setObjectName("ChipName")
        self.size_lbl = QLabel("…")
        self.size_lbl.setObjectName("ChipSize")
        self.hint_lbl = QLabel(hint)
        self.hint_lbl.setObjectName("ChipHint")
        for w in (self.name_lbl, self.size_lbl, self.hint_lbl):
            w.setAlignment(Qt.AlignmentFlag.AlignCenter)
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            v.addWidget(w)

    def set_selected(self, on: bool) -> None:
        self.setProperty("selected", "true" if on else "false")
        repolish(self)

    def set_size(self, text: str, tip: str) -> None:
        self.size_lbl.setText(text)
        self.setToolTip(tip)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit(self.key)


# ---------------------------------------------------------------------------- one row per file

class FileRow(QFrame):
    remove_requested = Signal(int)

    def __init__(self, rid: int, path: Path, kind: Kind):
        super().__init__()
        self.setObjectName("Card")
        self.rid, self.path, self.kind = rid, path, kind
        self.state = "waiting"
        self.bad = ""
        self.output: Path | None = None
        self.duration = 0.0
        self.extra = ""
        try:
            self.orig_bytes = path.stat().st_size
        except OSError:
            self.orig_bytes = 0

        h = QHBoxLayout(self)
        h.setContentsMargins(12, 10, 12, 10)
        h.setSpacing(14)
        self.thumb = Thumb(kind.audio)
        h.addWidget(self.thumb)

        mid = QVBoxLayout()
        mid.setSpacing(5)
        self.name = ElideLabel(path.name)
        self.name.setObjectName("RowName")
        self.detail = QLabel()
        self.detail.setObjectName("Subtle")
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.hide()
        mid.addWidget(self.name)
        mid.addWidget(self.detail)
        mid.addWidget(self.bar)
        h.addLayout(mid, 1)

        self.status = QLabel()
        self.status.setMinimumWidth(150)
        self.status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.show_btn = QPushButton("Show file")
        self.show_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.show_btn.clicked.connect(lambda: self.output and reveal_in_folder(self.output))
        self.show_btn.hide()
        self.remove_btn = QPushButton("✕")
        self.remove_btn.setObjectName("Round")
        self.remove_btn.setFixedSize(32, 32)
        self.remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove_btn.setToolTip("Remove from the list (doesn't delete the file)")
        self.remove_btn.clicked.connect(lambda: self.remove_requested.emit(self.rid))
        h.addWidget(self.status)
        h.addWidget(self.show_btn)
        h.addWidget(self.remove_btn)

        self.set_state("waiting")

    def pending(self) -> bool:
        return not self.bad and self.state in ("waiting", "failed", "cancelled")

    def _base_detail(self) -> str:
        parts = [human_time(self.duration)] if self.duration else []
        if self.extra:
            parts.append(self.extra)
        if self.orig_bytes:
            parts.append(f"now {fmt_size(self.orig_bytes)}")
        return "   ·   ".join(parts) or " "

    def set_info(self, img: QImage | None, duration: float, extra: str) -> None:
        self.duration, self.extra = duration, extra
        self.thumb.set_image(img)
        if self.state in ("waiting", "cancelled", "working"):
            self.detail.setText(self._base_detail())

    def _status(self, text: str, color: str) -> None:
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {color}; font-weight: 700;")

    def set_preview(self, text: str, tip: str) -> None:
        """Shows the expected size of the new file while it waits."""
        if self.state in ("waiting", "cancelled") and not self.bad:
            self._status(text, "#e9eaf2")
            self.status.setToolTip(tip)

    def mark_bad(self, reason: str) -> None:
        self.bad = reason
        self.state = "failed"
        self._status("Can't convert", BAD)
        self.detail.setText(self.kind.fail_hint)
        self.setToolTip(f"{self.path}\n\nDetails: {reason}")

    def set_state(self, state: str, text: str = "") -> None:
        if self.bad:
            return
        self.state = state
        self.bar.setVisible(state == "working")
        self.show_btn.setVisible(state == "done")
        self.remove_btn.setVisible(state != "working")
        self.setToolTip(str(self.path))
        self.status.setToolTip("")
        if state == "waiting":
            self._status("", "#a2a5b8")
            self.detail.setText(self._base_detail())
        elif state == "working":
            self.bar.setRange(0, 0)               # "busy" animation until real progress arrives
            self._status("Getting ready…", ACCENT_HOVER)
            self.detail.setText(self._base_detail())
        elif state == "done":
            self.output = Path(text)
            self._status("✓  Done", GOOD)
            try:
                n = self.output.stat().st_size
                self.detail.setText(f"Saved as  {self.output.name}   ·   {fmt_size(n)}")
                self.status.setToolTip(f"{n:,} bytes")
            except OSError:
                self.detail.setText(f"Saved as  {self.output.name}")
            self.setToolTip(f"Saved to:\n{self.output}")
        elif state == "failed":
            self._status("Couldn't convert", BAD)
            self.detail.setText(self.kind.fail_hint)
            self.setToolTip(f"{self.path}\n\nDetails: {text}")
        elif state == "cancelled":
            self._status("Stopped", "#a2a5b8")
            self.detail.setText(self._base_detail())

    def set_progress(self, f: float) -> None:
        if self.bar.maximum() == 0:
            self.bar.setRange(0, 1000)
        self.bar.setValue(int(f * 1000))
        self._status(f"Converting…  {int(f * 100)}%", ACCENT_HOVER)


# ---------------------------------------------------------------------------- background work

class InfoLoader(QObject):
    """Finds each file's length (and a preview picture for videos), in the background."""
    loaded = Signal(int, object, float, str)

    def __init__(self, ffmpeg: str | None, want_thumbs: bool):
        super().__init__()
        self.ffmpeg = ffmpeg
        self.want_thumbs = want_thumbs
        self.sem = threading.Semaphore(2)

    def request(self, rid: int, path: Path) -> None:
        if self.ffmpeg:
            threading.Thread(target=self._run, args=(self.ffmpeg, rid, path), daemon=True).start()

    def _run(self, ffmpeg: str, rid: int, path: Path) -> None:
        with self.sem:
            try:
                info = probe(ffmpeg, path)
                img, extra = None, ""
                if self.want_thumbs and info.vcodec:
                    t = make_thumbnail(ffmpeg, path, info.duration)
                    if t:
                        img = QImage(t)
                        try:
                            os.remove(t)
                        except OSError:
                            pass
                if not self.want_thumbs and info.arate:
                    layout = {"1 channels": "mono", "2 channels": "stereo"}.get(info.alayout, info.alayout)
                    extra = f"{info.arate / 1000:g} kHz {layout}".strip()
                self.loaded.emit(rid, img, info.duration, extra)
            except Exception:
                pass


class SizeBridge(QObject):
    """Carries 'sizes changed' notices from the measuring thread to the window."""
    changed = Signal(int)


class ConvertWorker(QThread):
    started_file = Signal(int, int, int)       # row id, index, total
    progress = Signal(int, float)
    finished_file = Signal(int, str, str)      # row id, state, text
    all_done = Signal(int, int, bool, str)     # ok, failed, cancelled, last output

    def __init__(self, prepare, jobs: list[tuple[int, Path, Path, Path | None]]):
        super().__init__()
        self.prepare = prepare                  # called in the thread; returns job(src, dst, **kw)
        self.jobs = jobs                        # (row id, source, destination, already-made file)
        self.cancel = threading.Event()
        self.proc: subprocess.Popen | None = None

    def stop(self) -> None:
        self.cancel.set()
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:
                pass

    def run(self) -> None:
        ok = fail = 0
        last = ""
        job = None
        for i, (rid, src, dst, ready) in enumerate(self.jobs):
            if self.cancel.is_set():
                break
            self.started_file.emit(rid, i, len(self.jobs))
            try:
                if ready is not None and ready.exists():
                    place_file(ready, dst)                      # measured earlier: just move it
                    self.progress.emit(rid, 1.0)
                else:
                    if job is None:
                        job = self.prepare()
                    job(src, dst, on_progress=lambda f, rid=rid: self.progress.emit(rid, f),
                        cancel=self.cancel, on_start=lambda p: setattr(self, "proc", p))
                ok += 1
                last = str(dst)
                self.finished_file.emit(rid, "done", str(dst))
            except Cancelled:
                self.finished_file.emit(rid, "cancelled", "")
                break
            except Exception as e:
                fail += 1
                self.finished_file.emit(rid, "failed", str(e))
        self.proc = None
        self.all_done.emit(ok, fail, self.cancel.is_set(), last)


# ---------------------------------------------------------------------------- one tab

class ConverterPage(QWidget):
    """One tab. kinds = the output formats this tab can make (the audio tab has OGG and MP3)."""

    def __init__(self, main: "MainWindow", kinds: list[Kind]):
        super().__init__()
        self.setObjectName("Page")
        self.main = main
        self.kinds = {k.fmt: k for k in kinds}
        start_fmt = main.settings.audio_format if len(kinds) > 1 else kinds[0].fmt
        self.kind = self.kinds.get(start_fmt, kinds[0])
        self.tab_label = kinds[0].tab_label
        kind = self.kind
        self.rows: dict[int, FileRow] = {}
        self.next_id = 1
        self.worker: ConvertWorker | None = None
        self.loader = InfoLoader(main.ffmpeg, want_thumbs=not kind.audio)
        self.loader.loaded.connect(self.on_info)
        self.selected = getattr(main.settings, kind.setting)

        self.bridge = SizeBridge()
        self.bridge.changed.connect(self.on_sizes_changed)
        # one size-measurer per format, so switching OGG <-> MP3 shows sizes straight away
        self.measurers = {k.fmt: SizeMeasurer(k.fmt, main.ffmpeg, k.qualities, getattr(main.settings, k.setting),
                                              main.settings.use_gpu, self.bridge.changed.emit)
                          for k in kinds}
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(120)
        self._refresh_timer.timeout.connect(self.refresh_sizes)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 14, 0, 0)
        v.setSpacing(12)
        self.v = v

        self.drop = DropZone(kind)
        self.drop.clicked.connect(self.choose_files)
        v.addWidget(self.drop, 1)

        # list
        self.list_box = QWidget()
        lv = QVBoxLayout(self.list_box)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(8)
        lh = QHBoxLayout()
        self.list_title = QLabel()
        self.list_title.setObjectName("Section")
        lh.addWidget(self.list_title)
        lh.addStretch(1)
        self.clear_btn = QPushButton("Clear list")
        self.clear_btn.setObjectName("Flat")
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.clicked.connect(self.clear_list)
        lh.addWidget(self.clear_btn)
        lv.addLayout(lh)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.viewport().setAutoFillBackground(False)
        holder = QWidget()
        holder.setObjectName("ListHolder")
        self.rows_layout = QVBoxLayout(holder)
        self.rows_layout.setContentsMargins(0, 0, 4, 0)
        self.rows_layout.setSpacing(8)
        self.rows_layout.addStretch(1)
        self.scroll.setWidget(holder)
        lv.addWidget(self.scroll, 1)
        v.addWidget(self.list_box, 0)

        # quality picker with size preview
        self.quality_box = QWidget()
        qv = QVBoxLayout(self.quality_box)
        qv.setContentsMargins(0, 0, 0, 0)
        qv.setSpacing(8)
        qh = QHBoxLayout()
        qt = QLabel("Quality  &  final size")
        qt.setObjectName("Section")
        qh.addWidget(qt)
        qh.addStretch(1)
        self.orig_lbl = QLabel()
        self.orig_lbl.setObjectName("Subtle")
        qh.addWidget(self.orig_lbl)
        qv.addLayout(qh)
        self.fmt_btns: dict[str, QPushButton] = {}
        if len(self.kinds) > 1:
            fr = QHBoxLayout()
            fr.setSpacing(8)
            fl = QLabel("Make an:")
            fl.setObjectName("Subtle")
            fr.addWidget(fl)
            tips = {"ogg": "OGG — great quality, used by games (RPG Maker) and many players",
                    "mp3": "MP3 — plays on absolutely everything: phones, cars, every computer"}
            for f in self.kinds:
                b = QPushButton(f"{f.upper()} file")
                b.setObjectName("Seg")
                b.setCheckable(True)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.setToolTip(tips.get(f, ""))
                b.clicked.connect(lambda _c=False, f=f: self.select_format(f))
                self.fmt_btns[f] = b
                fr.addWidget(b)
            self.fmt_note = QLabel()
            self.fmt_note.setObjectName("Subtle")
            fr.addSpacing(6)
            fr.addWidget(self.fmt_note)
            fr.addStretch(1)
            qv.addLayout(fr)
        chips = QHBoxLayout()
        chips.setSpacing(8)
        self.chips: dict[str, QualityChip] = {}
        for key, name, hint, _val in kind.qualities:
            c = QualityChip(key, name, hint)
            c.clicked.connect(self.select_quality)
            self.chips[key] = c
            chips.addWidget(c)
        qv.addLayout(chips)
        self.measure_lbl = QLabel()
        self.measure_lbl.setObjectName("Subtle")
        qv.addWidget(self.measure_lbl)
        v.addWidget(self.quality_box)

        # bottom bar
        bar = QFrame()
        bar.setObjectName("Card")
        bh = QHBoxLayout(bar)
        bh.setContentsMargins(18, 14, 14, 14)
        bh.setSpacing(12)
        info = QVBoxLayout()
        info.setSpacing(2)
        wr = QHBoxLayout()
        wr.setSpacing(4)
        self.where_lbl = QLabel()
        self.where_lbl.setObjectName("Subtle")
        change = QPushButton("Change")
        change.setObjectName("Flat")
        change.setCursor(Qt.CursorShape.PointingHandCursor)
        change.clicked.connect(main.open_settings)
        wr.addWidget(self.where_lbl)
        wr.addWidget(change)
        wr.addStretch(1)
        self.overall_lbl = QLabel()
        info.addLayout(wr)
        info.addWidget(self.overall_lbl)
        bh.addLayout(info, 1)
        self.saveas_btn = QPushButton("Save As…")
        self.saveas_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.saveas_btn.setToolTip("Choose the name and place for the new file yourself")
        self.saveas_btn.clicked.connect(lambda: self.start(save_as=True))
        self.convert_btn = QPushButton("Convert")
        self.convert_btn.setObjectName("Primary")
        self.convert_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.convert_btn.clicked.connect(self.convert_clicked)
        bh.addWidget(self.saveas_btn)
        bh.addWidget(self.convert_btn)
        v.addWidget(bar)

        self._show_format()
        self.apply_settings()
        self.update_view()

    @property
    def measurer(self) -> SizeMeasurer:
        return self.measurers[self.kind.fmt]

    def _show_format(self) -> None:
        for f, b in self.fmt_btns.items():
            b.setChecked(f == self.kind.fmt)
        if self.fmt_btns:
            self.fmt_note.setText({"ogg": "Great for games & music players",
                                   "mp3": "Plays on everything"}.get(self.kind.fmt, ""))
        for key, _name, hint, _val in self.kind.qualities:
            if key in self.chips:
                self.chips[key].hint_lbl.setText(hint)
        for k, c in self.chips.items():
            c.set_selected(k == self.selected)

    def select_format(self, fmt: str) -> None:
        if self.worker is not None or fmt == self.kind.fmt or fmt not in self.kinds:
            self._show_format()
            return
        self.kind = self.kinds[fmt]
        self.main.settings.audio_format = fmt
        self.main.settings.save()
        self.selected = getattr(self.main.settings, self.kind.setting)
        for r in self.ordered_rows():          # already converted? let them be made in the new format too
            if r.state == "done":
                r.set_state("waiting")
        self._show_format()
        self.apply_settings()
        self.update_view()

    # ---- looks
    def apply_settings(self) -> None:
        s = self.main.settings
        if s.save_mode == "folder" and s.save_folder:
            self.where_lbl.setText(f"Saving to:  {Path(s.save_folder).name or s.save_folder}")
            self.where_lbl.setToolTip(s.save_folder)
        else:
            self.where_lbl.setText(f"Saving to:  the same folder as each {self.kind.noun}")
            self.where_lbl.setToolTip("")
        if "mp4" in self.measurers:
            self.measurers["mp4"].set_gpu(s.use_gpu)

    def ordered_rows(self) -> list[FileRow]:
        out = []
        for i in range(self.rows_layout.count()):
            w = self.rows_layout.itemAt(i).widget()
            if isinstance(w, FileRow):
                out.append(w)
        return out

    def update_view(self) -> None:
        k = self.kind
        n = len(self.rows)
        has = n > 0
        self.drop.set_compact(has)
        self.list_box.setVisible(has)
        self.quality_box.setVisible(has)
        self.v.setStretchFactor(self.drop, 0 if has else 1)
        self.v.setStretchFactor(self.list_box, 1 if has else 0)
        self.list_title.setText(f"Your {k.nouns}  ({n})" if has else "")
        running = self.worker is not None
        self.clear_btn.setEnabled(not running)
        for c in self.chips.values():
            c.setEnabled(not running)
        for b in self.fmt_btns.values():
            b.setEnabled(not running)
        pending = sum(1 for r in self.rows.values() if r.pending())
        if not running:
            self.convert_btn.setEnabled(pending > 0)
            self.saveas_btn.setEnabled(pending > 0)
            self.convert_btn.setText(f"Convert {pending} files" if pending > 1 else "Convert")
            if not has:
                self.overall_lbl.setText(f"Add some {k.nouns} to get started.")
            elif pending == 0:
                self.overall_lbl.setText(f"All done! Add more {k.nouns} any time.")
            else:
                self.overall_lbl.setText(f"{pending} {k.noun if pending == 1 else k.nouns} ready to convert.")
        self.refresh_sizes()

    # ---- size preview
    def on_sizes_changed(self, _rid: int) -> None:
        self._refresh_timer.start()          # many updates arrive together; redraw once

    def select_quality(self, key: str) -> None:
        if self.worker is not None or key == self.selected:
            return
        self.selected = key
        setattr(self.main.settings, self.kind.setting, key)
        self.main.settings.save()
        for k, c in self.chips.items():
            c.set_selected(k == key)
        self.measurer.select(key)
        self.refresh_sizes()

    def refresh_sizes(self) -> None:
        pending = [r for r in self.ordered_rows() if r.pending()]
        snaps = {}
        for r in self.ordered_rows():
            sizes, bad = self.measurer.snapshot(r.rid)
            if bad and not r.bad:
                r.mark_bad(bad)
            snaps[r.rid] = sizes
        pending = [r for r in pending if not r.bad]

        orig = sum(r.orig_bytes for r in pending)
        self.orig_lbl.setText(f"Right now:  {fmt_size(orig)}" if pending else "")
        self.orig_lbl.setToolTip(f"{orig:,} bytes" if pending else "")

        any_estimate = any_missing = False
        for key, chip in self.chips.items():
            if not pending:
                chip.set_size("—", "")
                continue
            total, exact, missing, failed = 0, True, False, False
            for r in pending:
                got = snaps[r.rid].get(key)
                if got is None:
                    missing = True
                elif got[0] < 0:
                    failed = True
                else:
                    total += got[0]
                    exact = exact and got[1]
            if missing:
                chip.set_size("measuring…", "Working out the size in the background.")
                if key == self.selected:
                    any_missing = True
            elif failed:
                chip.set_size("?", "This quality couldn't be measured for one of the files.")
            elif exact:
                chip.set_size(fmt_size(total), f"Exact size: {total:,} bytes")
            else:
                chip.set_size("≈ " + fmt_size(total),
                              f"Estimated: about {total:,} bytes.\nUsually within a few percent. "
                              "Pick this quality to get the exact size.")
                if key == self.selected:
                    any_estimate = True

        for r in pending:
            got = snaps[r.rid].get(self.selected)
            if got is None:
                r.set_preview("measuring…", "")
            elif got[0] < 0:
                r.set_preview("", "")
            elif got[1]:
                r.set_preview(f"→  {fmt_size(got[0])}", f"Exact new size: {got[0]:,} bytes")
            else:
                r.set_preview(f"→  ≈ {fmt_size(got[0])}", f"Estimated new size: about {got[0]:,} bytes")

        if not pending:
            self.measure_lbl.setText("")
        elif any_missing or any_estimate:
            self.measure_lbl.setText("Measuring the exact size in the background…   "
                                     "(≈ means estimated — it becomes exact when measuring finishes)")
        elif any(not got[1] for r in pending for got in snaps[r.rid].values()):
            self.measure_lbl.setText("✓  Your choice shows the exact size.   "
                                     "≈ = estimated (long videos only measure the quality you pick).")
        else:
            self.measure_lbl.setText("✓  All sizes are exact — that's exactly what you'll get.")

    # ---- list management
    def add_files(self, files: list[Path]) -> int:
        known = {r.path.resolve() for r in self.rows.values()}
        added = 0
        for f in files:
            if f.resolve() in known:
                continue
            known.add(f.resolve())
            row = FileRow(self.next_id, f, self.kind)
            row.remove_requested.connect(self.remove_row)
            self.rows[self.next_id] = row
            self.rows_layout.insertWidget(self.rows_layout.count() - 1, row)
            self.loader.request(self.next_id, f)
            for m in self.measurers.values():
                m.add(self.next_id, f)
            self.next_id += 1
            added += 1
        self.update_view()
        return added

    def choose_files(self) -> None:
        s = self.main.settings
        pattern = " ".join("*" + e for e in sorted(self.kind.accept))
        label = "Audio files" if self.kind.audio else "Videos"
        files, _ = QFileDialog.getOpenFileNames(self, self.kind.dialog_title, s.last_dir or str(Path.home()),
                                                f"{label} ({pattern});;All files (*)")
        if files:
            s.last_dir = str(Path(files[0]).parent)
            s.save()
            self.add_files([Path(f) for f in files])

    def remove_row(self, rid: int) -> None:
        row = self.rows.pop(rid, None)
        if row is not None:
            for m in self.measurers.values():
                m.remove(rid)
            row.setParent(None)
            row.deleteLater()
        self.update_view()

    def clear_list(self) -> None:
        for rid in list(self.rows):
            self.remove_row(rid)

    def on_info(self, rid: int, img, duration: float, extra: str) -> None:
        row = self.rows.get(rid)
        if row is not None:
            row.set_info(img, duration, extra)

    # ---- converting
    def convert_clicked(self) -> None:
        if self.worker is not None:
            self.worker.stop()
            self.convert_btn.setEnabled(False)
            self.overall_lbl.setText("Stopping…")
        else:
            self.start(save_as=False)

    def make_prepare(self):
        ff = self.main.ffmpeg
        val = {k: v for k, _n, _h, v in self.kind.qualities}[self.selected]
        fmt = self.kind.fmt
        use_gpu = self.main.settings.use_gpu and fmt == "mp4"

        def prepare():
            gpu = detect_gpu_encoder(ff) if use_gpu else None
            return lambda src, dst, **kw: encode(fmt, ff, src, dst, val, gpu, **kw)
        return prepare

    def start(self, save_as: bool) -> None:
        if self.worker is not None:
            return
        if not self.main.ffmpeg:
            QMessageBox.critical(self, APP_NAME, "The converting engine (FFmpeg) is missing. "
                                                 "Please reopen the program so it can set itself up.")
            return
        rows = [r for r in self.ordered_rows() if r.pending()]
        if not rows:
            return
        s = self.main.settings
        ext = self.kind.out_ext

        if save_as and len(rows) == 1:
            src = rows[0].path
            start_dir = Path(s.last_dir) if s.last_dir else src.parent
            kind_name = self.kind.type_name
            fn, _ = QFileDialog.getSaveFileName(self, "Save the converted file as…",
                                                str(start_dir / (src.stem + ext)), f"{kind_name} (*{ext})")
            if not fn:
                return
            dst = Path(fn)
            if dst.suffix.lower() != ext:
                dst = dst.with_name(dst.name + ext)
            if dst.resolve() == src.resolve():
                QMessageBox.warning(self, APP_NAME, "Please pick a different name than the original file.")
                return
            s.last_dir = str(dst.parent)
            outputs = [dst]
        elif save_as:
            start_dir = s.last_dir or str(rows[0].path.parent)
            d = QFileDialog.getExistingDirectory(self, f"Choose where to save the converted {self.kind.nouns}",
                                                 start_dir)
            if not d:
                return
            s.last_dir = d
            outputs = plan_outputs([r.path for r in rows], Path(d), s.if_exists, ext)
        else:
            folder = Path(s.save_folder) if s.save_mode == "folder" and s.save_folder else None
            outputs = plan_outputs([r.path for r in rows], folder, s.if_exists, ext)
        s.save()

        for m in self.measurers.values():
            m.pause()                    # give the converting all the computer's attention
        for r in rows:
            r.set_state("waiting")
        jobs = [(r.rid, r.path, o, self.measurer.take_cached(r.rid, self.selected)) for r, o in zip(rows, outputs)]
        self.worker = ConvertWorker(self.make_prepare(), jobs)
        self.worker.started_file.connect(self.on_started)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_file.connect(self.on_finished_file)
        self.worker.all_done.connect(self.on_all_done)

        self.convert_btn.setText("Stop")
        self.convert_btn.setObjectName("Stop")
        repolish(self.convert_btn)
        self.convert_btn.setEnabled(True)
        self.saveas_btn.setEnabled(False)
        self.update_view()
        self.overall_lbl.setText("Getting ready…")
        self.worker.start()

    def on_started(self, rid: int, i: int, n: int) -> None:
        row = self.rows.get(rid)
        if row is not None:
            row.set_state("working")
            self.scroll.ensureWidgetVisible(row)
        self.overall_lbl.setText(f"Converting {i + 1} of {n}…  Please leave this window open.")

    def on_progress(self, rid: int, f: float) -> None:
        row = self.rows.get(rid)
        if row is not None:
            row.set_progress(f)

    def on_finished_file(self, rid: int, state: str, text: str) -> None:
        row = self.rows.get(rid)
        if row is not None:
            row.set_state(state, text)
        if state == "done":
            self.measurer.mark_done(rid)

    def on_all_done(self, ok: int, fail: int, cancelled: bool, last: str) -> None:
        if self.worker is not None:
            self.worker.wait(3000)
        self.worker = None
        self.convert_btn.setObjectName("Primary")
        repolish(self.convert_btn)
        for m in self.measurers.values():
            m.resume()
        self.update_view()
        if cancelled:
            self.overall_lbl.setText("Stopped. Press Convert to carry on.")
            return
        if ok and self.main.settings.open_folder_when_done and last:
            reveal_in_folder(Path(last))
        self.show_finished(ok, fail, last)

    def show_finished(self, ok: int, fail: int, last: str) -> None:
        k = self.kind
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setIconPixmap(make_app_icon(56))
        if fail == 0:
            box.setText("All done! 🎉" if ok > 1 else f"All done! 🎉  Your {k.noun} is ready.")
            if ok > 1:
                box.setInformativeText(f"{ok} {k.nouns} were converted.")
        elif ok == 0:
            box.setText("Sorry, that didn't work.")
            box.setInformativeText(k.fail_hint + "  Hover over it in the list for details.")
        else:
            box.setText(f"{ok} converted, {fail} couldn't be converted.")
            box.setInformativeText("The ones marked in red may be damaged. Hover over them for details.")
        show = box.addButton("Show me", QMessageBox.ButtonRole.AcceptRole) if ok else None
        box.addButton("OK", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if show is not None and box.clickedButton() is show and last:
            reveal_in_folder(Path(last))


# ---------------------------------------------------------------------------- youtube tab

YT_KIND = Kind("youtube", "▶   YouTube", ".mp4", set(), "video", "videos",
               "Paste or drop a YouTube link", "", "Check the link, then try again.", False, [])


class DownloadRow(FileRow):
    def __init__(self, rid: int, url: str):
        super().__init__(rid, Path("::youtube-link::"), YT_KIND)
        self.url, self.title = url, ""
        self.tip = url
        self.name.setFullText(url)
        self.setToolTip(url)

    def set_title(self, title: str) -> None:
        self.title = title
        self.name.setFullText(title)
        self.tip = f"{title}\n{self.url}"
        self.setToolTip(self.tip)

    def set_state(self, state: str, text: str = "") -> None:
        super().set_state(state, text)
        tip = getattr(self, "tip", "")
        if tip:
            self.setToolTip(tip)
        if state == "failed":
            self._status("Couldn't download", BAD)
            self.detail.setText((text or self.kind.fail_hint)[:120])
            self.setToolTip(f"{tip}\n\nDetails: {text}")

    def set_progress(self, f: float, extra: str = "") -> None:
        if self.bar.maximum() == 0:
            self.bar.setRange(0, 1000)
        self.bar.setValue(int(f * 1000))
        self._status(f"Downloading…  {int(f * 100)}%", ACCENT_HOVER)
        if extra:
            self.detail.setText(extra)


class InfoFetcher(QObject):
    """Looks up each link's title, length and preview picture in the background."""
    loaded = Signal(int, str, object, float, str)     # row id, title, picture, seconds, error

    def __init__(self):
        super().__init__()
        self.sem = threading.Semaphore(2)

    def request(self, rid: int, url: str) -> None:
        threading.Thread(target=self._run, args=(rid, url), daemon=True).start()

    def _run(self, rid: int, url: str) -> None:
        with self.sem:
            try:
                import yt_dlp
                with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True,
                                       "skip_download": True, "socket_timeout": 15}) as ydl:
                    info = ydl.extract_info(url, download=False)
                img = None
                thumb_url = info.get("thumbnail")
                if thumb_url:
                    try:
                        import urllib.request
                        img = QImage.fromData(urllib.request.urlopen(thumb_url, timeout=10).read())
                    except Exception:
                        img = None
                self.loaded.emit(rid, str(info.get("title") or ""), img, float(info.get("duration") or 0), "")
            except Exception as e:
                self.loaded.emit(rid, "", None, 0.0, clean_error(e))


def glob_escape(s: str) -> str:
    return re.sub(r"([\[\]*?])", r"[\1]", s)


class DownloadWorker(QThread):
    started_file = Signal(int, int, int)       # row id, index, total
    progress = Signal(int, float, str)         # row id, 0-1, speed text
    finished_file = Signal(int, str, str)      # row id, state, text
    all_done = Signal(int, int, bool, str)     # ok, failed, cancelled, last output

    def __init__(self, ffmpeg: str | None, jobs: list, cap: int, if_exists: str, fmt: str):
        super().__init__()
        self.ffmpeg, self.jobs, self.cap, self.if_exists, self.fmt = ffmpeg, jobs, cap, if_exists, fmt
        self.cancel = threading.Event()
        self.reserved: set = set()

    def stop(self) -> None:
        self.cancel.set()

    def run(self) -> None:
        ok = fail = 0
        last = ""
        try:
            import yt_dlp
            from yt_dlp.utils import sanitize_filename
        except Exception:
            for job in self.jobs:
                self.finished_file.emit(job[0], "failed",
                                        "The download engine (yt-dlp) is missing. Reopen the program so it can set itself up.")
            self.all_done.emit(0, len(self.jobs), False, "")
            return
        loc = ytdlp_ffmpeg_location(self.ffmpeg) if self.ffmpeg else None
        for i, (rid, url, dst, folder) in enumerate(self.jobs):
            if self.cancel.is_set():
                break
            self.started_file.emit(rid, i, len(self.jobs))
            try:
                out = self.one(yt_dlp, sanitize_filename, rid, url, dst, folder, loc)
                ok += 1
                last = str(out)
                self.finished_file.emit(rid, "done", str(out))
            except Cancelled:
                self.finished_file.emit(rid, "cancelled", "")
                break
            except Exception as e:
                if self.cancel.is_set():
                    self.finished_file.emit(rid, "cancelled", "")
                    break
                fail += 1
                self.finished_file.emit(rid, "failed", clean_error(e))
        self.all_done.emit(ok, fail, self.cancel.is_set(), last)

    def one(self, yt_dlp, sanitize, rid, url, dst, folder, loc) -> Path:
        ext = ".mp3" if self.fmt == "mp3" else ".mp4"
        common = {"quiet": True, "no_warnings": True, "noplaylist": True, "socket_timeout": 20}
        if loc:
            common["ffmpeg_location"] = loc
        if dst is None:     # name it after the video's title, in the chosen folder
            with yt_dlp.YoutubeDL(common) as ydl:
                info = ydl.extract_info(url, download=False)
            title = sanitize(str(info.get("title") or "video")).strip(". ")[:150] or "video"
            dst = Path(folder) / (title + ext)
            if self.if_exists != "replace" or dst in self.reserved:
                dst = unique_path(dst, self.reserved)
        self.reserved.add(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        seen: dict = {}

        def hook(d):
            if self.cancel.is_set():
                raise Cancelled()
            if d.get("status") != "downloading":
                return
            parts = max(1, len((d.get("info_dict") or {}).get("requested_formats") or [1]))
            idx = seen.setdefault(d.get("filename"), len(seen))
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total:
                f = min((idx + min(d.get("downloaded_bytes", 0) / total, 1.0)) / parts, 0.99)
                sp = d.get("speed") or 0
                self.progress.emit(rid, f, f"{sp / 1_000_000:.1f} MB/s" if sp else "")

        def post(d):
            if d.get("status") == "started":
                self.progress.emit(rid, 0.995, "Finishing up…")

        opts = dict(common, overwrites=True, progress_hooks=[hook], postprocessor_hooks=[post],
                    outtmpl=str(dst.with_suffix("")).replace("%", "%%") + ".%(ext)s")
        if self.fmt == "mp3":
            opts.update(format="ba/b", postprocessors=[{"key": "FFmpegExtractAudio",
                                                          "preferredcodec": "mp3", "preferredquality": "320"}])
        else:
            opts.update(format=format_for(self.cap), merge_output_format="mp4",
                        postprocessors=[{"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}])
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        if dst.exists():
            return dst
        found = sorted((p for p in dst.parent.glob(glob_escape(dst.stem) + ".*") if p.suffix != ".part"),
                       key=lambda p: p.stat().st_mtime)
        if found:
            return found[-1]
        raise ConvertError("The file wasn't saved. Check the link and try again.")


class DenoInstaller(QThread):
    done = Signal(bool)

    def run(self) -> None:
        try:
            r = subprocess.run(["winget", "install", "--id", "DenoLand.Deno", "-e",
                                "--accept-source-agreements", "--accept-package-agreements"],
                               capture_output=True, creationflags=CREATE_NO_WINDOW)
            self.done.emit(r.returncode == 0 or deno_ready())
        except Exception:
            self.done.emit(False)


class DownloadPage(QWidget):
    """The YouTube tab: paste links, save them as MP4 (or MP3 sound)."""

    def __init__(self, main: "MainWindow"):
        super().__init__()
        self.setObjectName("Page")
        self.main = main
        self.kind = YT_KIND
        self.tab_label = YT_KIND.tab_label
        self.measurers: dict = {}            # (the window's close handler expects this on every tab)
        self.rows: dict[int, DownloadRow] = {}
        self.next_id = 1
        self.worker: DownloadWorker | None = None
        self.installer: DenoInstaller | None = None
        self.fetcher = InfoFetcher()
        self.fetcher.loaded.connect(self.on_info)
        self.fmt = main.settings.yt_format

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 14, 0, 0)
        v.setSpacing(12)
        self.v = v

        # link box
        card = QFrame()
        card.setObjectName("Card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 12, 14, 12)
        cl.setSpacing(10)
        r = QHBoxLayout()
        r.setSpacing(8)
        self.entry = QLineEdit()
        self.entry.setPlaceholderText("Paste a YouTube (or other video) link here…")
        self.entry.returnPressed.connect(self.add_from_entry)
        paste = QPushButton("Paste")
        paste.clicked.connect(self.paste_link)
        add = QPushButton("Add")
        add.clicked.connect(self.add_from_entry)
        for b in (paste, add):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        r.addWidget(self.entry, 1)
        r.addWidget(paste)
        r.addWidget(add)
        cl.addLayout(r)
        q = QHBoxLayout()
        q.setSpacing(8)
        fl = QLabel("Save as:")
        fl.setObjectName("Subtle")
        q.addWidget(fl)
        self.fmt_btns: dict[str, QPushButton] = {}
        for f, label, tip in (("mp4", "MP4 video", "The whole video, plays everywhere"),
                              ("mp3", "MP3 audio", "Just the sound, as an MP3 music file")):
            b = QPushButton(label)
            b.setObjectName("Seg")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(tip)
            b.clicked.connect(lambda _c=False, f=f: self.select_format(f))
            self.fmt_btns[f] = b
            q.addWidget(b)
        q.addSpacing(10)
        self.ql = QLabel("Quality:")
        self.ql.setObjectName("Subtle")
        self.quality = QComboBox()
        for label, cap in DL_QUALITIES:
            self.quality.addItem(label, cap)
        self.quality.setCurrentIndex(max(0, self.quality.findData(main.settings.yt_quality)))
        self.quality.currentIndexChanged.connect(self.quality_changed)
        q.addWidget(self.ql)
        q.addWidget(self.quality)
        q.addStretch(1)
        cl.addLayout(q)
        v.addWidget(card)

        # YouTube helper notice
        self.deno_box = QFrame()
        self.deno_box.setObjectName("Card")
        dh = QHBoxLayout(self.deno_box)
        dh.setContentsMargins(14, 10, 10, 10)
        self.deno_lbl = QLabel("YouTube links need a small free helper (Deno) that isn't installed yet.")
        self.deno_lbl.setWordWrap(True)
        self.deno_lbl.setStyleSheet("color: #ffb74d;")
        self.deno_btn = QPushButton("Install it now" if os.name == "nt" else "Get it")
        self.deno_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.deno_btn.clicked.connect(self.install_deno)
        dh.addWidget(self.deno_lbl, 1)
        dh.addWidget(self.deno_btn)
        v.addWidget(self.deno_box)
        self.deno_box.setVisible(not deno_ready())

        # empty-state zone (also the place links get dropped)
        self.drop = DropZone(YT_KIND, "click here to paste the link you copied",
                             "+   Add another link  —  paste it above, or drop it anywhere",
                             "Click to paste a link from your clipboard")
        self.drop.clicked.connect(self.paste_link)
        v.addWidget(self.drop, 1)

        # list
        self.list_box = QWidget()
        lv = QVBoxLayout(self.list_box)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(8)
        lh = QHBoxLayout()
        self.list_title = QLabel()
        self.list_title.setObjectName("Section")
        lh.addWidget(self.list_title)
        lh.addStretch(1)
        self.clear_btn = QPushButton("Clear list")
        self.clear_btn.setObjectName("Flat")
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.clicked.connect(self.clear_list)
        lh.addWidget(self.clear_btn)
        lv.addLayout(lh)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.viewport().setAutoFillBackground(False)
        holder = QWidget()
        holder.setObjectName("ListHolder")
        self.rows_layout = QVBoxLayout(holder)
        self.rows_layout.setContentsMargins(0, 0, 4, 0)
        self.rows_layout.setSpacing(8)
        self.rows_layout.addStretch(1)
        self.scroll.setWidget(holder)
        lv.addWidget(self.scroll, 1)
        v.addWidget(self.list_box, 0)

        # bottom bar (same as the other tabs)
        bar = QFrame()
        bar.setObjectName("Card")
        bh = QHBoxLayout(bar)
        bh.setContentsMargins(18, 14, 14, 14)
        bh.setSpacing(12)
        info = QVBoxLayout()
        info.setSpacing(2)
        wr = QHBoxLayout()
        wr.setSpacing(4)
        self.where_lbl = QLabel()
        self.where_lbl.setObjectName("Subtle")
        change = QPushButton("Change")
        change.setObjectName("Flat")
        change.setCursor(Qt.CursorShape.PointingHandCursor)
        change.clicked.connect(main.open_settings)
        wr.addWidget(self.where_lbl)
        wr.addWidget(change)
        wr.addStretch(1)
        self.overall_lbl = QLabel()
        info.addLayout(wr)
        info.addWidget(self.overall_lbl)
        bh.addLayout(info, 1)
        self.saveas_btn = QPushButton("Save As…")
        self.saveas_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.saveas_btn.setToolTip("Choose the name and place for the downloaded file yourself")
        self.saveas_btn.clicked.connect(lambda: self.start(save_as=True))
        self.dl_btn = QPushButton("Download")
        self.dl_btn.setObjectName("Primary")
        self.dl_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dl_btn.clicked.connect(self.download_clicked)
        bh.addWidget(self.saveas_btn)
        bh.addWidget(self.dl_btn)
        v.addWidget(bar)

        self.select_format(self.fmt, save=False)
        self.apply_settings()
        self.update_view()

    # ---- looks / settings
    def apply_settings(self) -> None:
        s = self.main.settings
        if s.save_mode == "folder" and s.save_folder:
            self.where_lbl.setText(f"Saving to:  {Path(s.save_folder).name or s.save_folder}")
            self.where_lbl.setToolTip(s.save_folder)
        else:
            self.where_lbl.setText("Saving to:  your Downloads folder")
            self.where_lbl.setToolTip(str(downloads_dir()))

    def select_format(self, fmt: str, save: bool = True) -> None:
        self.fmt = fmt if fmt in ("mp4", "mp3") else "mp4"
        for f, b in self.fmt_btns.items():
            b.setChecked(f == self.fmt)
        self.ql.setVisible(self.fmt == "mp4")
        self.quality.setVisible(self.fmt == "mp4")
        if save:
            self.main.settings.yt_format = self.fmt
            self.main.settings.save()

    def quality_changed(self, *_):
        self.main.settings.yt_quality = int(self.quality.currentData() or 0)
        self.main.settings.save()

    def install_deno(self) -> None:
        if os.name != "nt":
            QDesktopServices.openUrl(QUrl("https://deno.com"))
            return
        self.deno_btn.setEnabled(False)
        self.deno_btn.setText("Installing…")
        self.installer = DenoInstaller()
        self.installer.done.connect(self.deno_done)
        self.installer.start()

    def deno_done(self, ok: bool) -> None:
        self.deno_btn.setEnabled(True)
        self.deno_btn.setText("Install it now")
        if ok and deno_ready():
            self.deno_box.hide()
        elif ok:
            self.deno_lbl.setText("Installed! Please close the program and open it again so it can find it.")
        else:
            self.deno_lbl.setText("Couldn't install it automatically. Open a command prompt and type:  winget install DenoLand.Deno")

    # ---- list management
    def ordered_rows(self) -> list[DownloadRow]:
        out = []
        for i in range(self.rows_layout.count()):
            w = self.rows_layout.itemAt(i).widget()
            if isinstance(w, DownloadRow):
                out.append(w)
        return out

    def update_view(self) -> None:
        n = len(self.rows)
        has = n > 0
        self.drop.set_compact(has)
        self.list_box.setVisible(has)
        self.v.setStretchFactor(self.drop, 0 if has else 1)
        self.v.setStretchFactor(self.list_box, 1 if has else 0)
        self.list_title.setText(f"Your links  ({n})" if has else "")
        running = self.worker is not None
        self.clear_btn.setEnabled(not running)
        for b in self.fmt_btns.values():
            b.setEnabled(not running)
        self.quality.setEnabled(not running)
        pending = sum(1 for r in self.rows.values() if r.pending())
        if not running:
            self.dl_btn.setEnabled(pending > 0)
            self.saveas_btn.setEnabled(pending > 0)
            self.dl_btn.setText(f"Download {pending} links" if pending > 1 else "Download")
            if not has:
                self.overall_lbl.setText("Add a link to get started.")
            elif pending == 0:
                self.overall_lbl.setText("All done! Add more links any time.")
            else:
                self.overall_lbl.setText(f"{pending} link{'s' if pending != 1 else ''} ready to download.")

    def add_files(self, _files) -> int:      # files are never routed here (this tab takes links)
        return 0

    def add_links(self, text: str) -> int:
        urls = re.findall(r"https?://[^\s<>\"']+", text or "")
        known = {r.url for r in self.rows.values()}
        added = 0
        for u in urls:
            if u in known:
                continue
            known.add(u)
            row = DownloadRow(self.next_id, u)
            row.remove_requested.connect(self.remove_row)
            self.rows[self.next_id] = row
            self.rows_layout.insertWidget(self.rows_layout.count() - 1, row)
            self.fetcher.request(self.next_id, u)
            self.next_id += 1
            added += 1
        self.update_view()
        if not urls:
            self.overall_lbl.setText("That doesn't look like a link. Links start with  https://")
        return added

    def add_from_entry(self) -> None:
        if self.add_links(self.entry.text()):
            self.entry.clear()

    def paste_link(self) -> None:
        text = QApplication.clipboard().text().strip()
        if text:
            self.add_links(text)
        else:
            self.entry.setFocus()
            self.overall_lbl.setText("Nothing to paste yet. Copy a video link first.")

    def remove_row(self, rid: int) -> None:
        row = self.rows.pop(rid, None)
        if row is not None:
            row.setParent(None)
            row.deleteLater()
        self.update_view()

    def clear_list(self) -> None:
        for rid in list(self.rows):
            self.remove_row(rid)

    def on_info(self, rid: int, title: str, img, duration: float, err: str) -> None:
        row = self.rows.get(rid)
        if row is None:
            return
        if title:
            row.set_title(title)
        row.set_info(img, duration, "")
        if err and not title and row.state == "waiting":
            row.detail.setText("Couldn't read this link yet. It may still work when you press Download.")
            row.setToolTip(f"{row.url}\n\n{err}")

    # ---- downloading
    def download_clicked(self) -> None:
        if self.worker is not None:
            self.worker.stop()
            self.dl_btn.setEnabled(False)
            self.overall_lbl.setText("Stopping…")
        else:
            self.start(save_as=False)

    def start(self, save_as: bool) -> None:
        if self.worker is not None:
            return
        rows = [r for r in self.ordered_rows() if r.pending()]
        if not rows:
            return
        s = self.main.settings
        ext = ".mp3" if self.fmt == "mp3" else ".mp4"
        type_name = "MP3 audio" if self.fmt == "mp3" else "MP4 video"
        if save_as and len(rows) == 1:
            r = rows[0]
            name = re.sub(r'[\\/:*?"<>|]+', "", r.title).strip() or "video"
            start_dir = Path(s.last_dir) if s.last_dir else downloads_dir()
            fn, _ = QFileDialog.getSaveFileName(self, "Save the download as…",
                                                str(start_dir / (name[:120] + ext)), f"{type_name} (*{ext})")
            if not fn:
                return
            dst = Path(fn)
            if dst.suffix.lower() != ext:
                dst = dst.with_name(dst.name + ext)
            s.last_dir = str(dst.parent)
            jobs = [(r.rid, r.url, dst, None)]
        elif save_as:
            d = QFileDialog.getExistingDirectory(self, "Choose where to save the downloads",
                                                 s.last_dir or str(downloads_dir()))
            if not d:
                return
            s.last_dir = d
            jobs = [(r.rid, r.url, None, Path(d)) for r in rows]
        else:
            folder = Path(s.save_folder) if s.save_mode == "folder" and s.save_folder else downloads_dir()
            jobs = [(r.rid, r.url, None, folder) for r in rows]
        s.save()

        for r in rows:
            r.set_state("waiting")
        self.worker = DownloadWorker(self.main.ffmpeg, jobs, int(self.quality.currentData() or 0),
                                     s.if_exists, self.fmt)
        self.worker.started_file.connect(self.on_started)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_file.connect(self.on_finished_file)
        self.worker.all_done.connect(self.on_all_done)
        self.dl_btn.setText("Stop")
        self.dl_btn.setObjectName("Stop")
        repolish(self.dl_btn)
        self.dl_btn.setEnabled(True)
        self.saveas_btn.setEnabled(False)
        self.update_view()
        self.overall_lbl.setText("Getting ready…")
        self.worker.start()

    def on_started(self, rid: int, i: int, n: int) -> None:
        row = self.rows.get(rid)
        if row is not None:
            row.set_state("working")
            self.scroll.ensureWidgetVisible(row)
        self.overall_lbl.setText(f"Downloading {i + 1} of {n}…  Please leave this window open.")

    def on_progress(self, rid: int, f: float, extra: str) -> None:
        row = self.rows.get(rid)
        if row is not None:
            row.set_progress(f, extra)

    def on_finished_file(self, rid: int, state: str, text: str) -> None:
        row = self.rows.get(rid)
        if row is not None:
            row.set_state(state, text)

    def on_all_done(self, ok: int, fail: int, cancelled: bool, last: str) -> None:
        if self.worker is not None:
            self.worker.wait(3000)
        self.worker = None
        self.dl_btn.setObjectName("Primary")
        repolish(self.dl_btn)
        self.update_view()
        if cancelled:
            self.overall_lbl.setText("Stopped. Press Download to carry on.")
            return
        if ok and self.main.settings.open_folder_when_done and last:
            reveal_in_folder(Path(last))
        self.show_finished(ok, fail, last)

    def show_finished(self, ok: int, fail: int, last: str) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setIconPixmap(make_app_icon(56))
        what = "sound" if self.fmt == "mp3" else "video"
        if fail == 0:
            box.setText("All done! 🎉" if ok > 1 else f"All done! 🎉  Your {what} is ready.")
            if ok > 1:
                box.setInformativeText(f"{ok} downloads finished.")
        elif ok == 0:
            box.setText("Sorry, that didn't work.")
            box.setInformativeText("Check that the link works and try again.  Hover over it in the list for details.")
        else:
            box.setText(f"{ok} downloaded, {fail} couldn't be downloaded.")
            box.setInformativeText("The ones marked in red didn't work. Hover over them for details.")
        show = box.addButton("Show me", QMessageBox.ButtonRole.AcceptRole) if ok else None
        box.addButton("OK", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if show is not None and box.clickedButton() is show and last:
            reveal_in_folder(Path(last))


# ---------------------------------------------------------------------------- merge tab

class MergeSlot(QFrame):
    """One of the two boxes on the Merge tab (the video, or the sound)."""
    clicked = Signal()
    cleared = Signal()
    dropped = Signal(list)

    def __init__(self, is_audio: bool, number: str, title: str, empty_text: str):
        super().__init__()
        self.setObjectName("DropZone")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(118)
        self.setAcceptDrops(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.path: Path | None = None
        self.empty_text = empty_text
        h = QHBoxLayout(self)
        h.setContentsMargins(16, 12, 12, 12)
        h.setSpacing(14)
        self.icon = DropIcon(56)
        self.thumb = Thumb(is_audio, 120, 68)
        self.thumb.hide()
        h.addWidget(self.icon)
        h.addWidget(self.thumb)
        col = QVBoxLayout()
        col.setSpacing(3)
        t = QLabel(f"{number}   {title}")
        t.setObjectName("Section")
        self.name = ElideLabel(empty_text)
        self.name.setObjectName("Subtle")
        self.detail = QLabel("")
        self.detail.setObjectName("Subtle")
        col.addStretch(1)
        col.addWidget(t)
        col.addWidget(self.name)
        col.addWidget(self.detail)
        col.addStretch(1)
        h.addLayout(col, 1)
        self.x_btn = QPushButton("✕")
        self.x_btn.setObjectName("Round")
        self.x_btn.setFixedSize(32, 32)
        self.x_btn.setToolTip("Remove (doesn't delete the file)")
        self.x_btn.clicked.connect(self.cleared.emit)
        self.x_btn.hide()
        h.addWidget(self.x_btn, 0, Qt.AlignmentFlag.AlignTop)
        for w in (self.icon, self.thumb, t, self.name, self.detail):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_file(self, path: Path | None) -> None:
        self.path = path
        filled = path is not None
        self.setObjectName("Card" if filled else "DropZone")
        repolish(self)
        self.icon.setVisible(not filled)
        self.thumb.setVisible(filled)
        self.x_btn.setVisible(filled)
        self.thumb.set_image(None)
        self.name.setObjectName("RowName" if filled else "Subtle")
        repolish(self.name)
        self.name.setFullText(path.name if filled else self.empty_text)
        self.detail.setText("")
        self.setToolTip(str(path) if filled else "Click to choose, or drag a file here")

    def set_info(self, img, duration: float, extra: str) -> None:
        if self.path is None:
            return
        self.thumb.set_image(img)
        parts = [human_time(duration)] if duration else []
        if extra:
            parts.append(extra)
        try:
            parts.append(fmt_size(self.path.stat().st_size))
        except OSError:
            pass
        self.detail.setText("   ·   ".join(parts))

    def set_hover(self, on: bool) -> None:
        self.setProperty("hover", "true" if on else "false")
        repolish(self)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and self.isEnabled():
            e.acceptProposedAction()
            self.setProperty("hover", "true")
            if self.path is not None:          # filled box: show it as the drop target too
                self.setObjectName("DropZone")
            repolish(self)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragLeaveEvent(self, _e):
        self.setProperty("hover", "false")
        self.setObjectName("Card" if self.path is not None else "DropZone")
        repolish(self)

    def dropEvent(self, e):
        self.dragLeaveEvent(e)
        paths = [Path(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()]
        paths = [p for p in paths if p.is_file()]
        if paths:
            e.acceptProposedAction()
            self.dropped.emit(paths)


class MergeBridge(QObject):
    est = Signal(int, object)          # token, dict(vinfo, ainfo, estimate)
    prog = Signal(int, float)          # token, 0..1 while measuring the exact size
    ready = Signal(int, str, object)   # token, finished file in the cache, size
    failed = Signal(int, str)          # token, reason


class MergePage(QWidget):
    """Put music / a new sound on a video."""

    def __init__(self, main: "MainWindow"):
        super().__init__()
        self.setObjectName("Page")
        self.main = main
        self.kind = MERGE_KIND
        self.tab_label = MERGE_KIND.tab_label
        self.measurers: dict = {}
        self.worker: ConvertWorker | None = None
        self.drop = self                      # the window asks pages for .drop.set_hover()
        self.vinfo: MediaInfo | None = None
        self.ainfo: MediaInfo | None = None
        self.token = 0
        self.bg_cancel = threading.Event()
        self.ready_path: Path | None = None
        self.ready_key = None
        self.ready_size = 0
        self.estimate = 0
        self.est_key = None
        self.done_path: Path | None = None
        self.bad = ""
        self.cache_dir = CACHE_ROOT / f"{os.getpid()}_merge"

        self.bridge = MergeBridge()
        self.bridge.est.connect(self.on_est)
        self.bridge.prog.connect(self.on_bg_prog)
        self.bridge.ready.connect(self.on_ready)
        self.bridge.failed.connect(self.on_bg_failed)
        self.req = {"video": 0, "audio": 0}     # newest request per box, so late answers are ignored
        self.vloader = InfoLoader(main.ffmpeg, want_thumbs=True)
        self.vloader.loaded.connect(lambda r, img, d, ex: r == self.req["video"] and self.vslot.set_info(img, d, ex))
        self.aloader = InfoLoader(main.ffmpeg, want_thumbs=False)
        self.aloader.loaded.connect(lambda r, img, d, ex: r == self.req["audio"] and self.aslot.set_info(img, d, ex))
        self.bg_key = None
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(700)
        self.debounce.timeout.connect(self.start_background)

        s = main.settings
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 14, 0, 0)
        v.setSpacing(12)

        intro = QLabel("Put music or a new sound on a video. Drop a video and a sound file (or another video) below.")
        intro.setObjectName("Subtle")
        intro.setWordWrap(True)
        v.addWidget(intro)

        slots = QHBoxLayout()
        slots.setSpacing(10)
        self.vslot = MergeSlot(False, "1", "Video", "Drag a video here, or click to choose")
        self.aslot = MergeSlot(True, "2", "Music or sound", "Drag a song or sound here, or click to choose")
        plus = QLabel("+")
        plus.setStyleSheet("font-size: 28px; font-weight: 700; color: #a2a5b8;")
        slots.addWidget(self.vslot, 1)
        slots.addWidget(plus)
        slots.addWidget(self.aslot, 1)
        v.addLayout(slots)
        self.vslot.clicked.connect(lambda: self.choose("video"))
        self.aslot.clicked.connect(lambda: self.choose("audio"))
        self.vslot.cleared.connect(lambda: self.set_slot("video", None))
        self.vslot.dropped.connect(lambda ps: self.slot_drop("video", ps))
        self.aslot.dropped.connect(lambda ps: self.slot_drop("audio", ps))
        self.aslot.cleared.connect(lambda: self.set_slot("audio", None))

        # ---- options
        self.opts_card = QFrame()
        self.opts_card.setObjectName("Card")
        g = QGridLayout(self.opts_card)
        g.setContentsMargins(18, 14, 18, 14)
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(10)
        g.setColumnStretch(1, 1)

        def label(text: str) -> QLabel:
            lb = QLabel(text)
            lb.setStyleSheet("font-weight: 700;")
            return lb

        # sound mode
        g.addWidget(label("Sound"), 0, 0)
        mrow = QHBoxLayout()
        mrow.setSpacing(8)
        self.mode_btns: dict[str, QPushButton] = {}
        for key, text, tip in (("replace", "Replace the video's sound", "Only the new music/sound will be heard"),
                               ("mix", "Mix with the video's sound", "Hear both: the video's own sound and the new one")):
            b = QPushButton(text)
            b.setObjectName("Seg")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(tip)
            b.clicked.connect(lambda _c=False, k=key: self.set_mode(k))
            self.mode_btns[key] = b
            mrow.addWidget(b)
        mrow.addStretch(1)
        g.addLayout(mrow, 0, 1)

        # volumes
        g.addWidget(label("Volume"), 1, 0)
        vrow = QHBoxLayout()
        vrow.setSpacing(10)

        def vol_slider(value: int):
            sl = QSlider(Qt.Orientation.Horizontal)
            sl.setRange(0, 200)
            sl.setSingleStep(5)
            sl.setPageStep(10)
            sl.setValue(value)
            sl.setMinimumWidth(110)
            val = QLabel(f"{value}%")
            val.setMinimumWidth(44)
            sl.valueChanged.connect(lambda x, lb=val: lb.setText(f"{x}%"))
            sl.valueChanged.connect(self.options_changed)
            return sl, val

        nl = QLabel("New sound")
        nl.setObjectName("Subtle")
        self.new_vol, nv = vol_slider(s.merge_new_volume)
        self.vid_vol_lbl = QLabel("Video's own sound")
        self.vid_vol_lbl.setObjectName("Subtle")
        self.vid_vol, self.vid_vol_val = vol_slider(s.merge_video_volume)
        for w in (nl, self.new_vol, nv):
            vrow.addWidget(w)
        vrow.addSpacing(16)
        for w in (self.vid_vol_lbl, self.vid_vol, self.vid_vol_val):
            vrow.addWidget(w)
        vrow.addStretch(1)
        g.addLayout(vrow, 1, 1)

        # timing / offset
        g.addWidget(label("Timing"), 2, 0)
        trow = QHBoxLayout()
        trow.setSpacing(8)

        def secs_box() -> QDoubleSpinBox:
            sb = QDoubleSpinBox()
            sb.setDecimals(1)
            sb.setSingleStep(0.1)
            sb.setRange(0.0, 36000.0)
            sb.setSuffix("  seconds")
            sb.setAccelerated(True)
            sb.setKeyboardTracking(False)
            sb.setMinimumWidth(130)
            sb.valueChanged.connect(self.options_changed)
            return sb

        t1 = QLabel("Start the music after")
        t1.setObjectName("Subtle")
        self.offset_box = secs_box()
        self.offset_box.setToolTip("The video plays this long before the music begins.\n"
                                   "Use the arrows (or type) to fine-tune it by 0.1 seconds.")
        t2 = QLabel("and skip the first")
        t2.setObjectName("Subtle")
        self.skip_box = secs_box()
        self.skip_box.setToolTip("Leave out the beginning of the music, e.g. to cut a slow intro.")
        t3 = QLabel("of the music")
        t3.setObjectName("Subtle")
        reset = QPushButton("Reset")
        reset.setObjectName("Flat")
        reset.setCursor(Qt.CursorShape.PointingHandCursor)
        reset.clicked.connect(self.reset_timing)
        for w in (t1, self.offset_box, t2, self.skip_box, t3, reset):
            trow.addWidget(w)
        trow.addStretch(1)
        g.addLayout(trow, 2, 1)

        # length
        g.addWidget(label("Length"), 3, 0)
        self.length_box = QComboBox()
        self.length_box.addItem("Keep the whole video  (the music just stops if it's shorter)", "video")
        self.length_box.addItem("Repeat the music to fill the whole video", "loop")
        self.length_box.addItem("End the video when the music ends", "shortest")
        self.length_box.setCurrentIndex(max(0, self.length_box.findData(s.merge_length)))
        self.length_box.currentIndexChanged.connect(self.options_changed)
        lrow = QHBoxLayout()
        lrow.addWidget(self.length_box)
        lrow.addStretch(1)
        g.addLayout(lrow, 3, 1)

        self.info_lbl = QLabel("")
        self.info_lbl.setObjectName("Subtle")
        self.info_lbl.setWordWrap(True)
        g.addWidget(self.info_lbl, 4, 0, 1, 2)
        v.addWidget(self.opts_card)
        v.addStretch(1)

        # ---- bottom bar
        bar = QFrame()
        bar.setObjectName("Card")
        bh = QHBoxLayout(bar)
        bh.setContentsMargins(18, 14, 14, 14)
        bh.setSpacing(12)
        info = QVBoxLayout()
        info.setSpacing(3)
        wr = QHBoxLayout()
        wr.setSpacing(4)
        self.where_lbl = QLabel()
        self.where_lbl.setObjectName("Subtle")
        change = QPushButton("Change")
        change.setObjectName("Flat")
        change.setCursor(Qt.CursorShape.PointingHandCursor)
        change.clicked.connect(main.open_settings)
        wr.addWidget(self.where_lbl)
        wr.addWidget(change)
        wr.addStretch(1)
        info.addLayout(wr)
        sr = QHBoxLayout()
        sr.setSpacing(8)
        self.size_lbl = QLabel()
        self.size_lbl.setObjectName("ChipSize")
        self.status_lbl = QLabel()
        self.status_lbl.setObjectName("Subtle")
        self.show_btn = QPushButton("Show file")
        self.show_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.show_btn.clicked.connect(lambda: self.done_path and reveal_in_folder(self.done_path))
        self.show_btn.hide()
        sr.addWidget(self.size_lbl)
        sr.addWidget(self.status_lbl)
        sr.addWidget(self.show_btn)
        sr.addStretch(1)
        info.addLayout(sr)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.hide()
        info.addWidget(self.bar)
        bh.addLayout(info, 1)
        self.saveas_btn = QPushButton("Save As…")
        self.saveas_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.saveas_btn.clicked.connect(lambda: self.start(save_as=True))
        self.merge_btn = QPushButton("Merge")
        self.merge_btn.setObjectName("Primary")
        self.merge_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.merge_btn.clicked.connect(self.merge_clicked)
        bh.addWidget(self.saveas_btn)
        bh.addWidget(self.merge_btn)
        v.addWidget(bar)

        self.set_mode(s.merge_mode if s.merge_mode in ("replace", "mix") else "replace", quiet=True)
        self.apply_settings()
        self.update_view()

    # ---- settings / options
    def apply_settings(self) -> None:
        s = self.main.settings
        if s.save_mode == "folder" and s.save_folder:
            self.where_lbl.setText(f"Saving to:  {Path(s.save_folder).name or s.save_folder}")
            self.where_lbl.setToolTip(s.save_folder)
        else:
            self.where_lbl.setText("Saving to:  the same folder as the video")
            self.where_lbl.setToolTip("")
        if hasattr(self, "length_box"):
            self.options_changed()      # quality or graphics-card setting may have changed

    def options(self) -> MergeOptions:
        crf = {k: v for k, _n, _h, v in VIDEO_QUALITIES}.get(self.main.settings.video_quality, 23)
        return MergeOptions(mode=self.mode, length=self.length_box.currentData(),
                            new_volume=self.new_vol.value(), video_volume=self.vid_vol.value(),
                            offset=self.offset_box.value(), music_start=self.skip_box.value(), crf=crf)

    def current_key(self):
        if self.vslot.path is None or self.aslot.path is None:
            return None
        return (str(self.vslot.path), str(self.aslot.path), self.options().key(), self.main.settings.use_gpu)

    def set_mode(self, mode: str, quiet: bool = False) -> None:
        self.mode = mode
        for k, b in self.mode_btns.items():
            b.setChecked(k == mode)
        mix = mode == "mix"
        for w in (self.vid_vol_lbl, self.vid_vol, self.vid_vol_val):
            w.setVisible(mix)
        if not quiet:
            self.options_changed()

    def reset_timing(self) -> None:
        self.offset_box.setValue(0.0)
        self.skip_box.setValue(0.0)

    def options_changed(self, *_):
        s = self.main.settings
        if hasattr(self, "mode"):
            s.merge_mode = self.mode
        s.merge_length = self.length_box.currentData()
        s.merge_new_volume = self.new_vol.value()
        s.merge_video_volume = self.vid_vol.value()
        s.save()
        self.done_path = None
        self.update_view()
        self.debounce.start()

    # ---- files
    def set_hover(self, on: bool) -> None:
        self.vslot.set_hover(on and self.vslot.path is None)
        self.aslot.set_hover(on and self.aslot.path is None)

    def choose(self, which: str) -> None:
        if self.worker is not None:
            return
        s = self.main.settings
        if which == "video":
            exts, title, label = VIDEO_EXTS, "Choose the video", "Videos"
        else:
            exts, title, label = AUDIO_EXTS | VIDEO_EXTS, "Choose the music or sound", "Music and sounds"
        pattern = " ".join("*" + e for e in sorted(exts))
        fn, _ = QFileDialog.getOpenFileName(self, title, s.last_dir or str(Path.home()),
                                            f"{label} ({pattern});;All files (*)")
        if fn:
            s.last_dir = str(Path(fn).parent)
            s.save()
            self.set_slot(which, Path(fn))

    def add_files(self, files: list[Path]) -> int:
        """Dropped files: videos fill the video box first, songs go in the sound box."""
        if self.worker is not None:
            return 0
        vids = [f for f in files if f.suffix.lower() in VIDEO_EXTS]
        auds = [f for f in files if f.suffix.lower() in AUDIO_EXTS]
        used = 0
        if auds:
            self.set_slot("audio", auds[0])
            used += 1
        if vids:
            self.set_slot("video", vids[0])
            used += 1
            if len(vids) > 1 and not auds:       # two videos: the second one gives the sound
                self.set_slot("audio", vids[1])
                used += 1
        return used

    def slot_drop(self, which: str, paths: list) -> None:
        """A file dropped right onto one of the two boxes."""
        if self.worker is not None:
            return
        f = paths[0]
        ext = f.suffix.lower()
        if which == "video" and ext in AUDIO_EXTS:
            which = "audio"                       # a song dropped on the video box: put it where it belongs
        if ext not in VIDEO_EXTS | AUDIO_EXTS:
            QMessageBox.information(self, APP_NAME, "That doesn't look like a video or a sound file.")
            return
        self.set_slot(which, f)

    def set_slot(self, which: str, path: Path | None) -> None:
        if self.worker is not None:
            return
        slot, loader = (self.vslot, self.vloader) if which == "video" else (self.aslot, self.aloader)
        slot.set_file(path)
        if which == "video":
            self.vinfo = None
        else:
            self.ainfo = None
            self.skip_box.setValue(0.0)
        if path is not None:
            self.req[which] += 1
            loader.request(self.req[which], path)
        self.est_key = None
        self.bad = ""
        self.options_changed()

    # ---- size preview (exact size is measured by really merging in the background)
    def start_background(self) -> None:
        key = self.current_key()
        if key is not None and key == self.bg_key and not self.bad and (
                not self.bg_cancel.is_set() or (self.ready_path is not None and self.ready_key == key)):
            return                                 # already measuring / measured exactly this
        self.bg_cancel.set()
        self._drop_ready()
        self.bg_key = None
        if key is None or self.worker is not None or not self.main.ffmpeg:
            return
        self.bg_key = key
        self.bad = ""
        self.token += 1
        token, cancel = self.token, threading.Event()
        self.bg_cancel = cancel
        ff, video, audio, opts = self.main.ffmpeg, self.vslot.path, self.aslot.path, self.options()
        use_gpu = self.main.settings.use_gpu
        out = self.cache_dir / f"{token}.mp4"

        def work():
            try:
                vi, ai = probe(ff, video), probe(ff, audio)
                if vi.vcodec is None:
                    raise ConvertError("The video file has no picture in it.")
                if ai.acodec is None:
                    raise ConvertError("The sound file has no sound in it.")
                gpu = detect_gpu_encoder(ff) if use_gpu and not video_can_be_copied(vi) else None
                try:
                    est = estimate_merge_size(ff, video, vi, ai, opts, gpu or "libx264", cancel)
                except Cancelled:
                    raise
                except Exception:
                    est = 0
                self.bridge.est.emit(token, {"v": vi, "a": ai, "est": est, "key": key})
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                merge_av(ff, video, audio, out, opts, gpu, on_progress=lambda f: self.bridge.prog.emit(token, f),
                         cancel=cancel, low=True)
                self.bridge.ready.emit(token, str(out), out.stat().st_size)
                cancel.set()                       # finished: nothing left running for this key
            except Cancelled:
                out.unlink(missing_ok=True)
            except Exception as e:
                out.unlink(missing_ok=True)
                cancel.set()
                self.bridge.failed.emit(token, str(e))

        threading.Thread(target=work, daemon=True).start()
        self.update_view()

    def _drop_ready(self) -> None:
        if self.ready_path is not None:
            self.ready_path.unlink(missing_ok=True)
        self.ready_path, self.ready_key, self.ready_size = None, None, 0

    def on_est(self, token: int, d: dict) -> None:
        if token != self.token:
            return
        self.vinfo, self.ainfo = d["v"], d["a"]
        self.estimate, self.est_key = d["est"], d["key"]
        self.offset_box.setMaximum(max(0.0, round(self.vinfo.duration - 0.1, 1)))
        self.skip_box.setMaximum(max(0.0, round(self.ainfo.duration - 0.1, 1)))
        self.bg_progress = 0.0
        self.update_view()

    def on_bg_prog(self, token: int, f: float) -> None:
        if token == self.token:
            self.bg_progress = f
            self.update_view()

    def on_ready(self, token: int, path: str, size) -> None:
        if token != self.token:
            Path(path).unlink(missing_ok=True)
            return
        self.ready_path, self.ready_key, self.ready_size = Path(path), self.current_key(), int(size)
        self.update_view()

    @staticmethod
    def friendly(reason: str) -> str:
        if reason.startswith(("The ", "You ", "Can't")):
            return reason
        return "One of the files may be damaged, or it isn't a video/sound file."

    def on_bg_failed(self, token: int, reason: str) -> None:
        if token == self.token:
            self.bad = reason
            self.update_view()

    # ---- what the screen shows
    def update_view(self) -> None:
        running = self.worker is not None
        both = self.vslot.path is not None and self.aslot.path is not None
        key = self.current_key()
        for w in (self.opts_card, self.vslot, self.aslot):
            w.setEnabled(not running)
        self.saveas_btn.setEnabled(both and not running and not self.bad)
        if not running:
            self.merge_btn.setEnabled(both and not self.bad and self.done_path is None)
        self.show_btn.setVisible(self.done_path is not None and not running)

        # lengths line
        vi, ai = self.vinfo, self.ainfo
        if both and vi and ai:
            o = self.options()
            new_len = merge_output_length(vi, ai, o)
            heard = max(0.0, ai.duration - o.music_start)
            msg = (f"Video {human_time(vi.duration)}   ·   music {human_time(heard)}"
                   f"{' (after skipping)' if o.music_start else ''}   →   new video {human_time(new_len)}.")
            if o.length == "video" and heard + o.offset < vi.duration - 0.5:
                msg += f"   The music ends at {human_time(heard + o.offset)}, then the rest is "
                msg += "the video's own sound." if o.mode == "mix" else "silent."
            if o.length == "video" and heard + o.offset > vi.duration + 0.5:
                msg += "   The end of the music is cut off when the video ends."
            pic = ("Picture: kept exactly as it is (no quality loss, fast)." if video_can_be_copied(vi) else
                   "Picture: this video's format has to be re-made for MP4, using the quality picked "
                   "on the Video tab.")
            self.info_lbl.setText(msg + "\n" + pic)
        elif both:
            self.info_lbl.setText("Reading the files…")
        else:
            self.info_lbl.setText("Pick a video and a music/sound file to see how long the new video will be.")

        # size + status line
        self.size_lbl.setStyleSheet("")
        if running:
            return
        if self.done_path is not None:
            try:
                n = self.done_path.stat().st_size
                self.size_lbl.setText(f"✓  {fmt_size(n)}")
                self.size_lbl.setToolTip(f"{n:,} bytes")
            except OSError:
                self.size_lbl.setText("✓")
            self.size_lbl.setStyleSheet(f"color: {GOOD};")
            self.status_lbl.setText(f"Saved as  {self.done_path.name}")
        elif not both:
            self.status_lbl.setToolTip("")
            self.size_lbl.setText("")
            self.status_lbl.setText("Add a video and a sound to get started.")
        elif self.bad:
            self.size_lbl.setText("Can't merge")
            self.size_lbl.setStyleSheet(f"color: {BAD};")
            self.status_lbl.setText(self.friendly(self.bad))
            self.status_lbl.setToolTip(f"Details: {self.bad}")
        elif self.ready_path is not None and self.ready_key == key:
            self.size_lbl.setText(fmt_size(self.ready_size))
            self.size_lbl.setToolTip(f"Exact size: {self.ready_size:,} bytes")
            self.status_lbl.setText("exact final size  ·  ready — merging will be instant")
        elif self.est_key == key and self.estimate:
            self.size_lbl.setText("≈ " + fmt_size(self.estimate))
            self.size_lbl.setToolTip(f"Estimated: about {self.estimate:,} bytes")
            pct = int(getattr(self, "bg_progress", 0.0) * 100)
            self.status_lbl.setText(f"estimated  ·  measuring the exact size… {pct}%")
        else:
            self.size_lbl.setText("measuring…")
            self.size_lbl.setToolTip("")
            self.status_lbl.setText("working out the final size")

    # ---- merging
    def merge_clicked(self) -> None:
        if self.worker is not None:
            self.worker.stop()
            self.merge_btn.setEnabled(False)
            self.status_lbl.setText("Stopping…")
        else:
            self.start(save_as=False)

    def start(self, save_as: bool) -> None:
        if self.worker is not None or self.vslot.path is None or self.aslot.path is None:
            return
        if not self.main.ffmpeg:
            QMessageBox.critical(self, APP_NAME, "The converting engine (FFmpeg) is missing. "
                                                 "Please reopen the program so it can set itself up.")
            return
        s = self.main.settings
        video, audio = self.vslot.path, self.aslot.path
        base_name = f"{video.stem} (merged)"
        named = video.parent / (base_name + ".src")     # plan_outputs swaps the ending for .mp4
        if save_as:
            start_dir = Path(s.last_dir) if s.last_dir else video.parent
            fn, _ = QFileDialog.getSaveFileName(self, "Save the merged video as…",
                                                str(start_dir / (base_name + ".mp4")), "MP4 video (*.mp4)")
            if not fn:
                return
            dst = Path(fn)
            if dst.suffix.lower() != ".mp4":
                dst = dst.with_name(dst.name + ".mp4")
            if dst.resolve() in (video.resolve(), audio.resolve()):
                QMessageBox.warning(self, APP_NAME, "Please pick a different name than the original files.")
                return
            s.last_dir = str(dst.parent)
        else:
            folder = Path(s.save_folder) if s.save_mode == "folder" and s.save_folder else None
            dst = plan_outputs([named], folder, s.if_exists, ".mp4")[0]
        s.save()

        key = self.current_key()
        ready = self.ready_path if (self.ready_path is not None and self.ready_key == key) else None
        self.ready_path, self.ready_key = None, None       # handed over to the worker
        self.bg_cancel.set()
        ff, opts, use_gpu = self.main.ffmpeg, self.options(), s.use_gpu

        def prepare():
            gpu = detect_gpu_encoder(ff) if use_gpu else None
            return lambda src, d, **kw: merge_av(ff, src, audio, d, opts, gpu, **kw)

        self.worker = ConvertWorker(prepare, [(1, video, dst, ready)])
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_file.connect(self.on_finished)
        self.worker.all_done.connect(self.on_all_done)
        self.merge_btn.setText("Stop")
        self.merge_btn.setObjectName("Stop")
        repolish(self.merge_btn)
        self.merge_btn.setEnabled(True)
        self.bar.setRange(0, 0)
        self.bar.show()
        self.size_lbl.setText("")
        self.status_lbl.setText("Merging…  Please leave this window open.")
        self.update_view()
        self.worker.start()

    def on_progress(self, _rid: int, f: float) -> None:
        if self.bar.maximum() == 0:
            self.bar.setRange(0, 1000)
        self.bar.setValue(int(f * 1000))
        self.status_lbl.setText(f"Merging…  {int(f * 100)}%   Please leave this window open.")

    def on_finished(self, _rid: int, state: str, text: str) -> None:
        if state == "done":
            self.done_path = Path(text)
        elif state == "failed":
            self.bad = text or "Something went wrong."

    def on_all_done(self, ok: int, fail: int, cancelled: bool, last: str) -> None:
        if self.worker is not None:
            self.worker.wait(3000)
        self.worker = None
        self.bar.hide()
        self.merge_btn.setText("Merge")
        self.merge_btn.setObjectName("Primary")
        repolish(self.merge_btn)
        if cancelled:
            self.update_view()
            self.status_lbl.setText("Stopped. Press Merge to try again.")
            self.debounce.start()
            return
        self.update_view()
        if ok and self.main.settings.open_folder_when_done and last:
            reveal_in_folder(Path(last))
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setIconPixmap(make_app_icon(56))
        if ok:
            box.setText("All done! 🎉  Your new video is ready.")
            show = box.addButton("Show me", QMessageBox.ButtonRole.AcceptRole)
        else:
            box.setText("Sorry, that didn't work.")
            box.setInformativeText("One of the files may be damaged.")
            show = None
        box.addButton("OK", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if show is not None and box.clickedButton() is show and last:
            reveal_in_folder(Path(last))

    def shutdown(self) -> None:
        self.bg_cancel.set()
        shutil.rmtree(self.cache_dir, ignore_errors=True)


# ---------------------------------------------------------------------------- settings window

class WallPreview(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(224, 126)
        self.pm: QPixmap | None = None
        self.dim = 55

    def set(self, path: str, dim: int) -> None:
        pm = QPixmap(path) if path else QPixmap()
        self.pm = None if pm.isNull() else pm
        self.dim = dim
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 10, 10)
        p.setClipPath(path)
        p.fillRect(self.rect(), QColor("#1b1d26"))
        if self.pm is not None:
            sc = self.pm.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap((self.width() - sc.width()) // 2, (self.height() - sc.height()) // 2, sc)
            p.fillRect(self.rect(), QColor(10, 11, 16, int(255 * self.dim / 100)))
        else:
            p.setPen(QColor("#6c6f82"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No wallpaper")
        p.setClipping(False)
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.end()


class SettingsDialog(QDialog):
    def __init__(self, parent: "MainWindow"):
        super().__init__(parent)
        self.main = parent
        self.s = parent.settings
        self.setWindowTitle("Settings")
        self.setMinimumWidth(600)
        self.resize(620, 640)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("SettingsBody")
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        v = QVBoxLayout(body)
        v.setContentsMargins(26, 18, 26, 10)
        v.setSpacing(10)

        def section(text: str, sub: str = "") -> None:
            lbl = QLabel(text)
            lbl.setObjectName("Section")
            v.addSpacing(6)
            v.addWidget(lbl)
            if sub:
                s = QLabel(sub)
                s.setObjectName("Subtle")
                s.setWordWrap(True)
                v.addWidget(s)

        # --- wallpaper
        section("Wallpaper", "Pick any picture to use as the background.")
        row = QHBoxLayout()
        row.setSpacing(16)
        self.preview = WallPreview()
        row.addWidget(self.preview)
        col = QVBoxLayout()
        col.setSpacing(8)
        choose = QPushButton("Choose picture…")
        choose.clicked.connect(self.choose_wallpaper)
        self.remove_wp = QPushButton("Remove wallpaper")
        self.remove_wp.clicked.connect(self.remove_wallpaper)
        col.addWidget(choose)
        col.addWidget(self.remove_wp)
        col.addSpacing(6)
        dl = QLabel("Darken it so text is easy to read:")
        dl.setObjectName("Subtle")
        col.addWidget(dl)
        self.dim = QSlider(Qt.Orientation.Horizontal)
        self.dim.setRange(0, 85)
        self.dim.setValue(self.s.wallpaper_dim)
        self.dim.valueChanged.connect(self.dim_changed)
        col.addWidget(self.dim)
        col.addStretch(1)
        row.addLayout(col, 1)
        v.addLayout(row)

        # --- where to save
        section("Where should converted and downloaded files go?")
        self.r_beside = QRadioButton("In the same folder as each original file  (YouTube downloads go to your Downloads folder)")
        self.r_folder = QRadioButton("Always in this folder:")
        grp = QButtonGroup(self)
        grp.addButton(self.r_beside)
        grp.addButton(self.r_folder)
        v.addWidget(self.r_beside)
        fr = QHBoxLayout()
        fr.addWidget(self.r_folder)
        self.folder_lbl = ElideLabel()
        self.folder_lbl.setObjectName("Subtle")
        fr.addWidget(self.folder_lbl, 1)
        pick = QPushButton("Choose folder…")
        pick.clicked.connect(self.choose_folder)
        fr.addWidget(pick)
        v.addLayout(fr)
        (self.r_folder if self.s.save_mode == "folder" and self.s.save_folder else self.r_beside).setChecked(True)
        self.r_beside.toggled.connect(self.save_mode_changed)

        el = QLabel("If a file with the same name is already there:")
        el.setObjectName("Subtle")
        v.addSpacing(4)
        v.addWidget(el)
        self.exists = QComboBox()
        self.exists.addItem("Keep both  (the new one gets a number)", "rename")
        self.exists.addItem("Replace the old one", "replace")
        self.exists.setCurrentIndex(max(0, self.exists.findData(self.s.if_exists)))
        self.exists.currentIndexChanged.connect(self.changed)
        v.addWidget(self.exists, 0, Qt.AlignmentFlag.AlignLeft)

        # --- speed
        section("Speed", "Quality is picked on each tab, where you can see the file sizes.")
        self.gpu = QCheckBox("Use the graphics card to convert videos faster  (if the computer has one)")
        self.gpu.setChecked(self.s.use_gpu)
        self.gpu.toggled.connect(self.changed)
        v.addWidget(self.gpu)

        # --- general
        section("When finished")
        self.open_done = QCheckBox("Open the folder automatically")
        self.open_done.setChecked(self.s.open_folder_when_done)
        self.open_done.toggled.connect(self.changed)
        v.addWidget(self.open_done)
        v.addStretch(1)

        foot = QHBoxLayout()
        foot.setContentsMargins(26, 10, 26, 20)
        foot.addStretch(1)
        done = QPushButton("Done")
        done.setObjectName("Primary")
        done.clicked.connect(self.accept)
        foot.addWidget(done)
        outer.addLayout(foot)
        self.refresh()

    def refresh(self) -> None:
        self.preview.set(self.s.wallpaper, self.s.wallpaper_dim)
        self.remove_wp.setEnabled(bool(self.s.wallpaper))
        self.folder_lbl.setFullText(self.s.save_folder or "(no folder chosen yet)")

    def push(self) -> None:
        self.s.save()
        self.main.apply_settings()
        self.refresh()

    def changed(self, *_):
        self.s.if_exists = self.exists.currentData()
        self.s.use_gpu = self.gpu.isChecked()
        self.s.open_folder_when_done = self.open_done.isChecked()
        self.push()

    def dim_changed(self, val: int) -> None:
        self.s.wallpaper_dim = val
        self.push()

    def choose_wallpaper(self) -> None:
        fn, _ = QFileDialog.getOpenFileName(self, "Choose a wallpaper picture", str(Path.home()), IMAGE_FILTER)
        if not fn:
            return
        if QPixmap(fn).isNull():
            QMessageBox.warning(self, "Wallpaper", "Sorry, that picture couldn't be opened. Try another one.")
            return
        src = Path(fn)
        dest = config_dir() / ("wallpaper" + src.suffix.lower())
        try:   # keep our own copy so it still works if the original is moved or deleted
            if src.resolve() != dest.resolve():
                for old in config_dir().glob("wallpaper.*"):
                    old.unlink(missing_ok=True)
                shutil.copy2(src, dest)
            self.s.wallpaper = str(dest)
        except OSError:
            self.s.wallpaper = str(src)
        self.push()

    def remove_wallpaper(self) -> None:
        for old in config_dir().glob("wallpaper.*"):
            old.unlink(missing_ok=True)
        self.s.wallpaper = ""
        self.push()

    def choose_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose where converted files go",
                                             self.s.save_folder or str(Path.home()))
        if d:
            self.s.save_folder = d
            self.s.save_mode = "folder"
            self.r_folder.setChecked(True)
            self.push()

    def save_mode_changed(self, beside_checked: bool) -> None:
        if not beside_checked and not self.s.save_folder:
            self.choose_folder()
            if not self.s.save_folder:
                self.r_beside.setChecked(True)
                return
        self.s.save_mode = "beside" if beside_checked else "folder"
        self.push()


# ---------------------------------------------------------------------------- main window

class MainWindow(QMainWindow):
    def __init__(self, ffmpeg: str | None, start_files: list[str]):
        super().__init__()
        self.ffmpeg = ffmpeg
        self.settings = Settings.load()

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(make_app_icon()))
        self.resize(900, 820)
        self.setMinimumSize(720, 640)
        self.setAcceptDrops(True)

        self.bg = Background()
        self.setCentralWidget(self.bg)
        outer = QVBoxLayout(self.bg)
        outer.setContentsMargins(26, 22, 26, 22)
        outer.setSpacing(14)

        head = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(make_app_icon(44))
        head.addWidget(logo)
        tcol = QVBoxLayout()
        tcol.setSpacing(0)
        title = QLabel(APP_NAME)
        title.setObjectName("Title")
        sub = QLabel("Turn videos into MP4 and music into OGG or MP3 — or save a video from a link.")
        sub.setObjectName("Subtle")
        tcol.addWidget(title)
        tcol.addWidget(sub)
        head.addSpacing(6)
        head.addLayout(tcol)
        head.addStretch(1)
        settings_btn = QPushButton("⚙   Settings")
        settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_btn.clicked.connect(self.open_settings)
        head.addWidget(settings_btn)
        outer.addLayout(head)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setCursor(Qt.CursorShape.PointingHandCursor)
        self.tabs.tabBar().setDrawBase(False)
        self.pages = [ConverterPage(self, [VIDEO_KIND]), ConverterPage(self, [AUDIO_KIND, MP3_KIND]),
                      MergePage(self), DownloadPage(self)]
        for pg in self.pages:
            self.tabs.addTab(pg, pg.tab_label)
        self.tabs.setCurrentIndex(min(max(self.settings.last_tab, 0), len(self.pages) - 1))
        self.tabs.currentChanged.connect(self.tab_changed)
        outer.addWidget(self.tabs, 1)

        self.apply_settings()
        if start_files:
            self.route_files(start_files)
        if not ffmpeg:
            QMessageBox.critical(self, APP_NAME,
                                 "The converting engine (FFmpeg) is missing.\n\n"
                                 "Close this window and open the program again — it will try to "
                                 "set itself up. If that doesn't help, install FFmpeg "
                                 "(Windows: open a command prompt and type  winget install ffmpeg).")

    def current_page(self) -> ConverterPage:
        return self.pages[self.tabs.currentIndex()]

    def tab_changed(self, i: int) -> None:
        self.settings.last_tab = i
        self.settings.save()

    def apply_settings(self) -> None:
        s = self.settings
        if s.wallpaper and not self.bg.set_wallpaper(s.wallpaper, s.wallpaper_dim):
            s.wallpaper = ""
            s.save()
        if not s.wallpaper:
            self.bg.set_wallpaper("", s.wallpaper_dim)
        for pg in getattr(self, "pages", []):
            pg.apply_settings()

    def open_settings(self) -> None:
        SettingsDialog(self).exec()
        self.settings.save()
        self.apply_settings()

    def route_files(self, paths) -> None:
        """Send dropped files to the right tab: the current tab if it takes them, otherwise the other one."""
        all_exts = set().union(*(pg.kind.accept for pg in self.pages))
        files, _ = expand_paths(paths, all_exts, strict=False)
        cur = self.tabs.currentIndex()
        order = [cur] + [i for i in range(len(self.pages)) if i != cur]
        buckets: dict[int, list[Path]] = {i: [] for i in order}
        skipped = 0
        for f in files:
            for i in order:
                if f.suffix.lower() in self.pages[i].kind.accept:
                    buckets[i].append(f)
                    break
            else:
                skipped += 1
        added_to = [i for i in order if buckets[i] and self.pages[i].add_files(buckets[i])]
        if added_to and cur not in added_to:
            self.tabs.setCurrentIndex(added_to[0])
        if not added_to and (skipped or not files):
            QMessageBox.information(self, APP_NAME,
                                    "Those don't look like video or audio files.\n\n"
                                    "Videos: .mov, .avi, .mkv, .wmv, .webm …   Audio: .mp3, .wav, .flac, .m4a, .wma …")

    # ---- drag & drop (works anywhere in the window)
    def on_download_tab(self) -> bool:
        return isinstance(self.current_page(), DownloadPage)

    def dragEnterEvent(self, e):
        md = e.mimeData()
        if md.hasUrls() or (self.on_download_tab() and md.hasText()):
            e.acceptProposedAction()
            self.current_page().drop.set_hover(True)

    def dragMoveEvent(self, e):
        md = e.mimeData()
        if md.hasUrls() or (self.on_download_tab() and md.hasText()):
            e.acceptProposedAction()

    def dragLeaveEvent(self, _e):
        self.current_page().drop.set_hover(False)

    def dropEvent(self, e):
        for pg in self.pages:
            pg.drop.set_hover(False)
        md = e.mimeData()
        if self.on_download_tab():          # links dropped on the YouTube tab
            links = [u.toString() for u in md.urls() if not u.isLocalFile()]
            if not links and md.hasText():
                links = [md.text()]
            if links:
                e.acceptProposedAction()
                self.current_page().add_links("\n".join(links))
                return
        paths = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
        if paths:
            e.acceptProposedAction()
            self.route_files(paths)

    def closeEvent(self, e):
        busy = [pg for pg in self.pages if pg.worker is not None]
        if busy:
            ans = QMessageBox.question(self, APP_NAME, "Something is still converting.\n\nStop it and close?")
            if ans != QMessageBox.StandardButton.Yes:
                e.ignore()
                return
            for pg in busy:
                if pg.worker is not None:
                    pg.worker.stop()
                    pg.worker.wait(4000)
        for pg in self.pages:
            for m in pg.measurers.values():
                m.shutdown()
            if hasattr(pg, "shutdown"):
                pg.shutdown()
        self.settings.save()
        e.accept()


# ============================================================================ start

def main() -> int:
    if os.name == "nt":   # own taskbar icon instead of the Python one
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MediaConverter.App")
        except Exception:
            pass
    if getattr(sys, "frozen", False):
        os.environ["PATH"] = str(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) + os.pathsep + os.environ.get("PATH", "")
    app = QApplication(sys.argv)
    if len(sys.argv) == 3 and sys.argv[1] == "--write-icon":    # used by build_exe.bat
        make_app_icon(256).save(sys.argv[2])
        return 0
    clean_old_cache()
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setPalette(dark_palette())
    app.setStyleSheet(QSS)
    app.setWindowIcon(QIcon(make_app_icon()))
    win = MainWindow(find_ffmpeg(), sys.argv[1:])   # files dragged onto the program icon open too
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
