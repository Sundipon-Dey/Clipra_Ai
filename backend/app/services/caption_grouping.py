"""Deterministic, readable short-form caption cue grouping."""

from __future__ import annotations

import re
from typing import Iterable


DEFAULT_GROUPING = {"max_words_per_line": 4, "max_lines": 2, "max_cue_seconds": 3.8, "pause_seconds": 0.55, "display_mode": "phrase"}
PUNCTUATION = re.compile(r"[.!?,;:]$")
CONNECTORS = {"a", "an", "and", "as", "at", "but", "for", "from", "in", "is", "of", "on", "or", "the", "to", "with"}


def normalize_grouping(grouping: dict | None) -> dict:
    result = {**DEFAULT_GROUPING, **(grouping or {})}
    if not isinstance(result["max_words_per_line"], int) or not 1 <= result["max_words_per_line"] <= 12:
        raise ValueError("Maximum words per line must be between 1 and 12.")
    if not isinstance(result["max_lines"], int) or not 1 <= result["max_lines"] <= 2:
        raise ValueError("Maximum caption lines must be 1 or 2.")
    if not 1 <= float(result["max_cue_seconds"]) <= 8 or not 0.1 <= float(result["pause_seconds"]) <= 3:
        raise ValueError("Caption grouping timing is invalid.")
    if not isinstance(result["display_mode"], str) or result["display_mode"] not in {"phrase", "one_word"}:
        raise ValueError("Caption display mode must be phrase or one word.")
    return result


def group_words(words: Iterable[dict], grouping: dict | None = None) -> list[dict]:
    config = normalize_grouping(grouping)
    words = list(words)
    max_words = config["max_words_per_line"] * config["max_lines"]
    groups: list[list[dict]] = []
    current: list[dict] = []
    for word in words:
        if not current:
            current.append(word)
            continue
        previous = current[-1]
        pause = float(word["start_seconds"]) - float(previous["end_seconds"])
        elapsed = float(word["end_seconds"]) - float(current[0]["start_seconds"])
        text = str(previous["text"]).strip()
        reaches_capacity = len(current) >= max_words
        preferred_break = bool(PUNCTUATION.search(text)) and len(current) >= 2
        pause_break = pause >= float(config["pause_seconds"]) and len(current) >= 2
        duration_break = elapsed > float(config["max_cue_seconds"]) and len(current) >= 2
        if reaches_capacity or preferred_break or pause_break or duration_break:
            groups.append(current)
            current = [word]
        else:
            current.append(word)
    if current:
        groups.append(current)
    return [_segment(group, config, ordinal) for ordinal, group in enumerate(groups)]


def _segment(words: list[dict], config: dict, ordinal: int) -> dict:
    max_per_line = config["max_words_per_line"]
    split = min(max_per_line, len(words))
    if len(words) > max_per_line and len(words) <= max_per_line * 2:
        midpoint = len(words) / 2
        candidates = range(max(1, int(midpoint) - 1), min(len(words), int(midpoint) + 2) + 1)
        split = min(candidates, key=lambda index: _split_cost(words, index, midpoint))
    rendered = [str(word["text"]).strip() for word in words]
    text = " ".join(rendered[:split])
    if split < len(rendered):
        text += "\n" + " ".join(rendered[split:])
    return {"ordinal": ordinal, "start_seconds": float(words[0]["start_seconds"]), "end_seconds": float(words[-1]["end_seconds"]), "generated_text": text, "words": words}


def _split_cost(words: list[dict], index: int, midpoint: float) -> float:
    left = str(words[index - 1]["text"]).lower().strip(".,!?;:")
    right = str(words[index]["text"]).lower().strip(".,!?;:") if index < len(words) else ""
    connector_penalty = 4 if left in CONNECTORS or right in CONNECTORS else 0
    character_balance = abs(sum(len(str(word["text"])) for word in words[:index]) - sum(len(str(word["text"])) for word in words[index:])) / 10
    return abs(index - midpoint) + connector_penalty + character_balance
