"""Versioned caption styles limited to future ASS-compatible primitives."""

from __future__ import annotations

from copy import deepcopy


STYLE_VERSION = 1
PRESETS: dict[str, dict] = {
    "clean_minimal": {"name": "Clean Minimal", "font_family": "Arial", "font_weight": 700, "font_size": 62, "text_color": "#FFFFFF", "highlight_color": "#FFFFFF", "outline_color": "#000000", "outline_width": 3, "shadow_color": "#000000", "shadow_offset": 3, "background_color": "#000000", "background_opacity": 0, "alignment": "center", "animation": "none", "animation_ms": 0},
    "karaoke_focus": {"name": "Karaoke Focus", "font_family": "Arial", "font_weight": 800, "font_size": 68, "text_color": "#FFFFFF", "highlight_color": "#E8FF4D", "outline_color": "#000000", "outline_width": 4, "shadow_color": "#000000", "shadow_offset": 3, "background_color": "#000000", "background_opacity": 0, "alignment": "center", "animation": "karaoke", "animation_ms": 90},
    "gaming_pulse": {"name": "Gaming Pulse", "font_family": "Arial Black", "font_weight": 900, "font_size": 76, "text_color": "#FFFFFF", "highlight_color": "#00F5FF", "outline_color": "#111111", "outline_width": 6, "shadow_color": "#FF008C", "shadow_offset": 4, "background_color": "#000000", "background_opacity": 0, "alignment": "center", "animation": "pop_karaoke", "animation_ms": 120},
    "neon_impact": {"name": "Neon Impact", "font_family": "Arial Black", "font_weight": 900, "font_size": 74, "text_color": "#FFFFFF", "highlight_color": "#FF4FD8", "outline_color": "#17122A", "outline_width": 6, "shadow_color": "#713DFF", "shadow_offset": 4, "background_color": "#000000", "background_opacity": 0, "alignment": "center", "animation": "pop", "animation_ms": 140},
    "bold_punch": {"name": "Bold Punch", "font_family": "Impact", "font_weight": 900, "font_size": 80, "text_color": "#FFFFFF", "highlight_color": "#FFD34D", "outline_color": "#000000", "outline_width": 6, "shadow_color": "#000000", "shadow_offset": 5, "background_color": "#000000", "background_opacity": 0, "alignment": "center", "animation": "pop", "animation_ms": 110},
    "story_box": {"name": "Story Box", "font_family": "Arial", "font_weight": 700, "font_size": 58, "text_color": "#FFFFFF", "highlight_color": "#FFFFFF", "outline_color": "#000000", "outline_width": 0, "shadow_color": "#000000", "shadow_offset": 0, "background_color": "#141414", "background_opacity": 0.82, "alignment": "center", "animation": "fade", "animation_ms": 160},
    "minimal_lower_third": {"name": "Minimal Lower Third", "font_family": "Arial", "font_weight": 600, "font_size": 52, "text_color": "#FFFFFF", "highlight_color": "#FFFFFF", "outline_color": "#000000", "outline_width": 2, "shadow_color": "#000000", "shadow_offset": 2, "background_color": "#000000", "background_opacity": 0, "alignment": "center", "animation": "fade", "animation_ms": 120},
}
ALLOWED_ANIMATIONS = {"none", "fade", "pop", "karaoke", "pop_karaoke"}
ALLOWED_SAFE_ZONES = {"shorts", "reels", "tiktok", "facebook"}


def preset_style(preset_id: str) -> dict:
    if preset_id not in PRESETS:
        raise ValueError("Unknown caption preset.")
    return deepcopy(PRESETS[preset_id])


def validate_style(style: dict) -> dict:
    if not isinstance(style, dict):
        raise ValueError("Caption style must be an object.")
    required = set(PRESETS["clean_minimal"])
    if not required.issubset(style):
        raise ValueError("Caption style is missing required render settings.")
    if style["animation"] not in ALLOWED_ANIMATIONS:
        raise ValueError("Caption animation is not render-compatible.")
    for key in ("font_size", "outline_width", "shadow_offset", "animation_ms"):
        if not isinstance(style[key], (int, float)) or isinstance(style[key], bool):
            raise ValueError("Caption style contains an invalid numeric value.")
    if not 18 <= style["font_size"] <= 160 or not 0 <= style["outline_width"] <= 16 or not 0 <= style["shadow_offset"] <= 24 or not 0 <= style["animation_ms"] <= 500:
        raise ValueError("Caption style value is outside the supported range.")
    if not isinstance(style["background_opacity"], (int, float)) or not 0 <= style["background_opacity"] <= 1:
        raise ValueError("Background opacity must be between 0 and 1.")
    if style["alignment"] not in {"left", "center", "right"}:
        raise ValueError("Caption alignment is invalid.")
    return {key: style[key] for key in required}
