"""Shared 9:16 FFmpeg renderer for explicitly approved exports."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path

from app.core.config import settings
from app.services.storage import managed_directory, managed_path, relative_path

WIDTH, HEIGHT = 1080, 1920


def _focus_expr(snapshot: dict) -> tuple[str, str]:
    clip = snapshot["clip"]
    if clip.get("manual_override_enabled") or clip["framing_mode"] == "manual_crop":
        return str(clip["manual_focus_x"]), str(clip["manual_focus_y"])
    points = snapshot.get("focal_points", []) if clip["framing_mode"] == "smart_crop" else []
    if not points:
        return "0.5", "0.5"
    points = sorted(points, key=lambda p: p["time_seconds"])
    # piecewise linear interpolation follows the editor's saved focal path.
    def expr(axis: str) -> str:
        values = []
        for a, b in zip(points, points[1:]):
            t0, t1 = a["time_seconds"] - clip["start_seconds"], b["time_seconds"] - clip["start_seconds"]
            va, vb = float(a[axis]), float(b[axis])
            interp = f"({va:.6f}+((t-{t0:.6f})*{(vb-va)/(t1-t0):.8f}))" if t1 > t0 else f"{va:.6f}"
            values.append(f"if(between(t,{t0:.6f},{t1:.6f}),{interp},")
        tail = f"{float(points[-1][axis]):.6f}"
        return "".join(values) + tail + ")" * len(values)
    return expr("x"), expr("y")


def filter_graph(snapshot: dict) -> str:
    clip = snapshot["clip"]
    mode = clip["framing_mode"]
    if mode == "fit":
        color = clip.get("fit_background_color", "#090a0f").lstrip("#")
        graph = f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=0x{color},setsar=1"
    elif mode == "blurred_background":
        blur = max(0, min(120, int(clip.get("blur_strength", 18)) * 3))
        graph = f"split[bg][fg];[bg]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT},boxblur={blur}:1[blur];[fg]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease[front];[blur][front]overlay=(W-w)/2:(H-h)/2,setsar=1"
    else:
        fx, fy = _focus_expr(snapshot)
        zoom = max(1.0, min(3.0, float(clip.get("manual_zoom", 1))))
        cw, ch = WIDTH / zoom, HEIGHT / zoom
        graph = f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={cw:.3f}:{ch:.3f}:(iw-ow)*({fx}):(ih-oh)*({fy}),scale={WIDTH}:{HEIGHT},setsar=1"
    return graph


def _section_graph(source_label: str, output_label: str, section: dict, width: int, height: int) -> str:
    zoom = max(1.0, min(3.0, float(section["zoom"])))
    px, py = max(0.0, min(1.0, float(section["position_x"]))), max(0.0, min(1.0, float(section["position_y"])))
    sw = max(2, round(width * zoom / 2) * 2)
    sh = max(2, round(height * zoom / 2) * 2)
    color = section["fit_background_color"].lstrip("#")
    if section["framing_mode"] == "fit":
        graph = f"scale={sw}:{sh}:force_original_aspect_ratio=decrease,pad={sw}:{sh}:(ow-iw)*{px:.6f}:(oh-ih)*{py:.6f}:color=0x{color}"
        graph += f",crop={width}:{height}:(iw-ow)*{px:.6f}:(ih-oh)*{py:.6f}"
    else:
        graph = f"scale={sw}:{sh}:force_original_aspect_ratio=increase,crop={width}:{height}:(iw-ow)*{px:.6f}:(ih-oh)*{py:.6f}"
    return f"[{source_label}]{graph},setsar=1[{output_label}]"


def split_filter_graph(snapshot: dict, caption_input: int | None = None) -> str:
    config = snapshot["clip"]["split_layout"]
    ratio = max(.25, min(.75, float(config["split_ratio"])))
    top_height = max(2, round(HEIGHT * ratio / 2) * 2)
    bottom_height = HEIGHT - top_height
    top_config, bottom_config = config["top"], config["bottom"]
    fps = max(1.0, min(120.0, float(snapshot.get("source_frame_rate_decimal") or 30)))
    pieces: list[str] = []
    if top_config["source_mode"] == "same_video":
        pieces.append("[0:v]split=2[top_input][bottom_input]")
    elif top_config["source_mode"] == "custom_image":
        pieces.extend(("[0:v]null[bottom_input]", "[1:v]null[top_input]"))
    else:
        color = top_config["solid_color"].lstrip("#")
        pieces.extend(("[0:v]null[bottom_input]", f"color=c=0x{color}:s={WIDTH}x{top_height}:r={fps:.6f},setsar=1[top]"))
    if top_config["source_mode"] != "solid_color":
        pieces.append(f"[top_input]setpts=PTS-STARTPTS,fps={fps:.6f}[top_timed]")
    pieces.append(f"[bottom_input]setpts=PTS-STARTPTS,fps={fps:.6f}[bottom_timed]")
    if top_config["source_mode"] != "solid_color":
        pieces.append(_section_graph("top_timed", "top", top_config, WIDTH, top_height))
    pieces.append(_section_graph("bottom_timed", "bottom", bottom_config, WIDTH, bottom_height))
    pieces.append("[top][bottom]vstack=inputs=2[stacked]")
    if caption_input is None:
        pieces.append("[stacked]null[outv]")
    else:
        pieces.append(f"[stacked][{caption_input}:v]overlay=0:0:format=auto:eof_action=pass[outv]")
    return ";".join(pieces)


def _render_caption_frames(snapshot: dict, job_id: str, fps: float, frame_count: int, progress_callback) -> tuple[Path, Path]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", job_id):
        raise ValueError("Render job ID is invalid.")
    track = snapshot.get("caption_track")
    if not track or not track.get("segments"):
        raise ValueError("Caption frame rendering requires a caption track with segments.")

    script = Path(__file__).resolve().parents[3] / "frontend" / "scripts" / "render-captions.mjs"
    node = shutil.which(os.getenv("CLIPRA_CAPTION_RENDERER_NODE", "node"))
    if not node:
        raise RuntimeError("Node.js is required to render captions with the editor's Chromium styles.")
    if not script.is_file():
        raise RuntimeError("The CLIPRA caption renderer is missing. Restore frontend/scripts/render-captions.mjs.")

    parent = managed_directory("temp/rendering")
    frame_directory = parent / f"{job_id}-caption-frames"
    frame_directory.mkdir(parents=False, exist_ok=False)
    relative_frames = relative_path(frame_directory)
    frame_directory = managed_path(relative_frames, must_exist=True)
    request_path = managed_path(relative_path(parent / f"{job_id}-caption-request.json"))
    duration = float(snapshot["clip"]["end_seconds"]) - float(snapshot["clip"]["start_seconds"])
    request = {
        "track": track,
        "clipStartSeconds": float(snapshot["clip"]["start_seconds"]),
        "durationSeconds": duration,
        "fps": fps,
        "frameCount": frame_count,
        "framesDirectory": str(frame_directory),
    }
    try:
        request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
    except Exception:
        request_path.unlink(missing_ok=True)
        shutil.rmtree(managed_path(relative_frames, must_exist=True), ignore_errors=True)
        raise

    command = [node, str(script), str(request_path)]
    try:
        process = subprocess.Popen(command, cwd=str(script.parent.parent), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8", errors="replace", shell=False)
    except Exception:
        request_path.unlink(missing_ok=True)
        shutil.rmtree(managed_path(relative_frames, must_exist=True), ignore_errors=True)
        raise
    stderr_lines: list[str] = []
    def read_stderr() -> None:
        assert process.stderr is not None
        for line in process.stderr:
            stderr_lines.append(line)
            if len(stderr_lines) > 100:
                del stderr_lines[:20]
    stderr_reader = threading.Thread(target=read_stderr, daemon=True)
    stderr_reader.start()
    timed_out = threading.Event()
    def stop_after_timeout() -> None:
        if process.poll() is None:
            timed_out.set()
            try:
                process.kill()
            except OSError:
                pass
    timeout_timer = threading.Timer(settings.preview_timeout_seconds, stop_after_timeout)
    timeout_timer.daemon = True
    timeout_timer.start()
    try:
        assert process.stdout is not None
        for line in process.stdout:
            try:
                event = json.loads(line)
                progress_callback(min(.12, .12 * int(event["frame"]) / max(1, frame_count)))
            except (ValueError, KeyError, TypeError):
                continue
        code = process.wait()
        if timed_out.is_set():
            raise RuntimeError("Chromium exceeded the configured caption rendering time limit.")
        stderr_reader.join(timeout=2)
        if code:
            detail = "".join(stderr_lines)[-3000:].strip()
            raise RuntimeError(detail or "Chromium could not render the caption frames.")
        first_frame = frame_directory / "frame-00000000.png"
        if not first_frame.is_file():
            raise RuntimeError("Chromium did not produce caption frames.")
        header = first_frame.open("rb")
        try:
            png_header = header.read(26)
        finally:
            header.close()
        if png_header[:8] != b"\x89PNG\r\n\x1a\n" or png_header[25] not in {4, 6}:
            raise RuntimeError("Chromium caption frames must preserve transparency for video compositing.")
        request_path.unlink(missing_ok=True)
        return frame_directory, first_frame
    except Exception:
        if process.poll() is None:
            process.kill()
            process.wait()
        request_path.unlink(missing_ok=True)
        shutil.rmtree(managed_path(relative_frames, must_exist=True), ignore_errors=True)
        raise
    finally:
        timeout_timer.cancel()


def render(snapshot: dict, output: Path, *, job_id: str, progress_callback) -> None:
    source = managed_path(snapshot["source_relative_path"], must_exist=True)
    managed_directory("temp/rendering")
    partial = managed_path(f"temp/rendering/{job_id}.partial.mp4")
    duration = snapshot["clip"]["end_seconds"] - snapshot["clip"]["start_seconds"]
    command = [settings.ffmpeg_path or "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{snapshot['clip']['start_seconds']:.6f}", "-i", str(source)]
    split_layout = snapshot["clip"].get("layout_type", "original") == "split_streamer_gameplay"
    caption_track = snapshot.get("caption_track")
    caption_frames: Path | None = None
    if split_layout and snapshot["clip"]["split_layout"]["top"]["source_mode"] == "custom_image":
        image = managed_path(snapshot["layout_image_relative_path"], must_exist=True)
        fps = max(1.0, min(120.0, float(snapshot.get("source_frame_rate_decimal") or 30)))
        command.extend(["-loop", "1", "-framerate", f"{fps:.6f}", "-i", str(image)])
    fps = max(1.0, min(120.0, float(snapshot.get("source_frame_rate_decimal") or 30)))
    frame_count = max(1, round(float(duration) * fps))
    if caption_track and caption_track.get("segments"):
        caption_frames, _first_frame = _render_caption_frames(
            snapshot, job_id, fps, frame_count,
            lambda progress: progress_callback(progress),
        )
        caption_input = 2 if split_layout and snapshot["clip"]["split_layout"]["top"]["source_mode"] == "custom_image" else 1
        command.extend(["-framerate", f"{fps:.6f}", "-start_number", "0", "-i", str(caption_frames / "frame-%08d.png")])
    else:
        caption_input = None
    command.extend(["-t", f"{duration:.6f}"])
    if split_layout:
        command.extend(["-filter_complex", split_filter_graph(snapshot, caption_input), "-map", "[outv]"])
    elif caption_input is not None:
        command.extend(["-filter_complex", f"[0:v]{filter_graph(snapshot)}[base];[base][{caption_input}:v]overlay=0:0:format=auto:eof_action=pass[outv]", "-map", "[outv]"])
    else:
        command.extend(["-vf", filter_graph(snapshot), "-map", "0:v:0"])
    command.extend(["-map", "0:a:0?", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(partial)])
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", shell=False)
        def read_progress() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                if line.startswith("out_time_ms="):
                    try:
                        fraction = int(line.split("=", 1)[1]) / (duration * 1_000_000)
                        progress_callback(.12 + min(.87, .87 * fraction) if caption_frames is not None else min(.99, fraction))
                    except (ValueError, ZeroDivisionError): pass
        reader = threading.Thread(target=read_progress, daemon=True)
        reader.start()
        try:
            code = process.wait(timeout=settings.preview_timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.wait()
            raise RuntimeError("FFmpeg exceeded the configured render time limit.") from exc
        reader.join(timeout=2)
        stderr = process.stderr.read() if process.stderr else ""
        if code or not partial.is_file() or partial.stat().st_size == 0:
            raise RuntimeError(stderr[-800:] or "FFmpeg did not produce a valid video.")
        if output.exists():
            raise FileExistsError("Render destination already exists; refusing to replace an earlier render.")
        os.replace(partial, output)
    finally:
        partial.unlink(missing_ok=True)
        if caption_frames is not None:
            shutil.rmtree(managed_path(relative_path(caption_frames), must_exist=True), ignore_errors=True)

