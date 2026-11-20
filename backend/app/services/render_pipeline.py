"""Shared 9:16 FFmpeg renderer for review previews and approved exports."""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from pathlib import Path

from app.core.config import settings
from app.services.storage import managed_directory, managed_path, relative_path

WIDTH, HEIGHT = 1080, 1920


def _ass_color(value: str, opacity: float = 1.0) -> str:
    value = value if re.fullmatch(r"#[0-9A-Fa-f]{6}", str(value)) else "#FFFFFF"
    rgb = value[1:]
    alpha = max(0, min(255, round((1 - opacity) * 255)))
    return f"&H{alpha:02X}{rgb[4:6]}{rgb[2:4]}{rgb[0:2]}"


def _ass_text(value: str) -> str:
    return value.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N").replace("\r", "")


def _ass_inline_color(value: str) -> str:
    return _ass_color(value) + "&"


def _ass_pop(duration_ms: int) -> str:
    return f"\\fscx72\\fscy72\\t(0,{duration_ms},\\fscx128\\fscy128)\\t({duration_ms},{duration_ms + 90},\\fscx106\\fscy106)" if duration_ms > 0 else ""


def _ass_caption_pop(duration_ms: int) -> str:
    return f"\\fscx88\\fscy88\\t(0,{duration_ms},\\fscx100\\fscy100)" if duration_ms > 0 else ""


def _phrase_markup(phrase: str, active_word: str | None, base: str, highlight: str, pop_ms: int = 0) -> str:
    rendered: list[str] = []
    for token in re.split(r"(\s+)", phrase):
        if active_word and token.strip() == active_word:
            pop_tags = _ass_pop(pop_ms)
            reset_scale = "\\fscx100\\fscy100" if pop_ms > 0 else ""
            rendered.append("{\\c" + _ass_inline_color(highlight) + pop_tags + "}" + _ass_text(token) + "{\\c" + _ass_inline_color(base) + reset_scale + "}")
        else:
            rendered.append(_ass_text(token))
    return "".join(rendered)


def _timestamp(seconds: float) -> str:
    centis = max(0, round(seconds * 100))
    hours, rem = divmod(centis, 360000)
    minutes, rem = divmod(rem, 6000)
    secs, cs = divmod(rem, 100)
    return f"{hours}:{minutes:02}:{secs:02}.{cs:02}"


def build_ass(track: dict | None, clip: dict) -> str:
    header = """[Script Info]\nScriptType: v4.00+\nWrapStyle: 2\nScaledBorderAndShadow: yes\nPlayResX: 1080\nPlayResY: 1920\n\n[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"""
    if not track:
        return header + "\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
    style = track["style"]
    align = {"left": 1, "center": 2, "right": 3}[style.get("alignment", "center")] + (3 - 1) * 3
    bold = -1 if int(style.get("font_weight", 700)) >= 700 else 0
    # Preview and export share this exact script. Browser dimensions are 360x640.
    fs = round(max(13, float(style.get("font_size", 62)) / 3.9) * 3)
    x = round(float(track.get("position_x", .5)) * WIDTH)
    y = round(float(track.get("position_y", .76)) * HEIGHT)
    bg = _ass_color(style.get("background_color", "#000000"), float(style.get("background_opacity", 0)))
    font = re.sub(r"[^\w .-]", "", str(style.get("font_family", "Arial")), flags=re.UNICODE)[:64] or "Arial"
    border_style = 3 if float(style.get("background_opacity", 0)) > 0 else 1
    # Keep preset shadows while ignoring legacy outline widths; the editor has no stroke setting.
    shadow = max(0.0, float(style.get("shadow_offset", 0))) * 1.5
    style_line = f"Style: Default,{font},{fs},{_ass_color(style.get('text_color','#FFFFFF'))},{_ass_color(style.get('highlight_color','#FFFFFF'))},{_ass_color(style.get('outline_color','#000000'))},{bg},{bold},0,{border_style},0,{shadow:.1f},{align},30,30,0,1"
    out = header + style_line + "\n\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
    grouping = track.get("grouping") or {}
    one_word = grouping.get("display_mode") == "one_word"
    base, hi = _ass_color(style.get("text_color", "#FFFFFF")), _ass_color(style.get("highlight_color", "#FFFFFF"))
    animation, anim_ms = style.get("animation", "none"), int(style.get("animation_ms", 0))
    fade = f"\\fad({anim_ms},0)" if animation == "fade" and anim_ms else ""
    for seg in track.get("segments", []):
        offset = float(track.get("timing_offset_seconds", 0))
        words = seg.get("words", [])
        if one_word and words:
            for word in words:
                text = re.sub(r"[.,]", "", word.get("text", "")).strip()
                if not text:
                    continue
                start = max(0, float(word["start_seconds"]) + offset)
                end = max(start + .01, float(word["end_seconds"]) + offset)
                # Each word cue starts with the same pop as the editor overlay.
                word_pop = _ass_pop(anim_ms or 120)
                tags = f"\\an{align}\\pos({x},{y})\\4c{_ass_inline_color(style.get('shadow_color','#000000'))}" + fade + word_pop
                out += f"Dialogue: 0,{_timestamp(start)},{_timestamp(end)},Default,,0,0,0,,{{{tags}\\c{_ass_inline_color(hi)}}}{_ass_text(text)}\n"
            continue
        start = max(0, float(seg["start_seconds"]) + offset)
        end = max(start + .01, float(seg["end_seconds"]) + offset)
        phrase = seg.get("override_text") or seg.get("generated_text") or ""
        if words:
            # Render the full phrase for each timed interval, highlighting only the word active at that moment.
            # This mirrors CaptionOverlay and avoids ASS karaoke color-state differences between renderers.
            segment_start, segment_end = float(seg["start_seconds"]), float(seg["end_seconds"])
            boundaries = {segment_start, segment_end}
            for word in words:
                word_start, word_end = float(word["start_seconds"]), float(word["end_seconds"])
                if word_end > segment_start and word_start < segment_end:
                    boundaries.add(max(segment_start, word_start))
                    boundaries.add(min(segment_end, word_end))
            ordered = sorted(boundaries)
            for interval_start, interval_end in zip(ordered, ordered[1:]):
                if interval_end - interval_start < .005:
                    continue
                midpoint = (interval_start + interval_end) / 2
                active = next((word for word in words if float(word["start_seconds"]) <= midpoint < float(word["end_seconds"])), None)
                word_pop_ms = (anim_ms or 120) if active else 0
                markup = _phrase_markup(phrase, str(active.get("text", "")).strip() if active else None, style.get("text_color", "#FFFFFF"), style.get("highlight_color", "#FFFFFF"), word_pop_ms)
                interval_fade = fade if abs(interval_start - segment_start) < .001 else ""
                interval_pop = _ass_caption_pop(anim_ms) if abs(interval_start - segment_start) < .001 and animation in {"pop", "pop_karaoke"} else ""
                tags = f"\\an{align}\\pos({x},{y})\\4c{_ass_inline_color(style.get('shadow_color','#000000'))}" + interval_fade + interval_pop
                cue_start = max(0, interval_start + offset)
                cue_end = max(cue_start + .01, interval_end + offset)
                out += f"Dialogue: 0,{_timestamp(cue_start)},{_timestamp(cue_end)},Default,,0,0,0,,{{{tags}}}{markup}\n"
            continue
        caption_pop = _ass_caption_pop(anim_ms) if animation in {"pop", "pop_karaoke"} else ""
        tags = f"\\an{align}\\pos({x},{y})\\4c{_ass_inline_color(style.get('shadow_color','#000000'))}" + fade + caption_pop
        out += f"Dialogue: 0,{_timestamp(start)},{_timestamp(end)},Default,,0,0,0,,{{{tags}}}{_ass_text(phrase)}\n"
    return out


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


def filter_graph(snapshot: dict, ass_path: Path) -> str:
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
    # subtitles/libass is used for both preview and final, preserving geometry and timing.
    path = ass_path.as_posix().replace(":", r"\:").replace("'", r"\'")
    return f"{graph},subtitles='{path}'"


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


def split_filter_graph(snapshot: dict, ass_path: Path) -> str:
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
    path = ass_path.as_posix().replace(":", r"\:").replace("'", r"\'")
    pieces.append(f"[stacked]subtitles='{path}'[outv]")
    return ";".join(pieces)


def render(snapshot: dict, output: Path, *, preview: bool, job_id: str, progress_callback) -> None:
    source = managed_path(snapshot["source_relative_path"], must_exist=True)
    ass_dir = managed_directory("temp/rendering")
    ass_path = ass_dir / f"{job_id}.ass"
    partial = ass_dir / f"{job_id}.partial.mp4"
    ass_path.write_text(build_ass(snapshot.get("caption_track"), snapshot["clip"]), encoding="utf-8")
    duration = snapshot["clip"]["end_seconds"] - snapshot["clip"]["start_seconds"]
    command = [settings.ffmpeg_path or "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{snapshot['clip']['start_seconds']:.6f}", "-i", str(source)]
    split_layout = snapshot["clip"].get("layout_type", "original") == "split_streamer_gameplay"
    if split_layout and snapshot["clip"]["split_layout"]["top"]["source_mode"] == "custom_image":
        image = managed_path(snapshot["layout_image_relative_path"], must_exist=True)
        fps = max(1.0, min(120.0, float(snapshot.get("source_frame_rate_decimal") or 30)))
        command.extend(["-loop", "1", "-framerate", f"{fps:.6f}", "-i", str(image)])
    command.extend(["-t", f"{duration:.6f}"])
    if split_layout:
        command.extend(["-filter_complex", split_filter_graph(snapshot, ass_path), "-map", "[outv]"])
    else:
        command.extend(["-vf", filter_graph(snapshot, ass_path), "-map", "0:v:0"])
    command.extend(["-map", "0:a:0?", "-c:v", "libx264", "-preset", "ultrafast" if preview else "medium", "-crf", "30" if preview else "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(partial)])
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", shell=False)
        def read_progress() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                if line.startswith("out_time_ms="):
                    try: progress_callback(min(.99, int(line.split("=", 1)[1]) / (duration * 1_000_000)))
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
        ass_path.unlink(missing_ok=True)
        partial.unlink(missing_ok=True)

