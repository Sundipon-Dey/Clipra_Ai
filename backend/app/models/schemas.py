"""Validated request and response models for projects and media."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ProjectSummary(BaseModel):
    id: str
    name: str
    created_at: str
    updated_at: str
    media_count: int


class MediaOut(BaseModel):
    id: str
    project_id: str
    original_filename: str
    size_bytes: int
    duration_seconds: float
    width: int
    height: int
    frame_rate: str | None
    frame_rate_decimal: float | None
    video_codec: str
    audio_codec: str | None
    has_audio: bool
    container_format: str
    preview_status: str
    preview_error: str | None
    imported_at: str
    stream_url: str
    preview_stream_url: str


class ProjectDetail(ProjectSummary):
    media: list[MediaOut]


class ImportFailure(BaseModel):
    filename: str
    error: str


class ImportResult(BaseModel):
    imported: list[MediaOut]
    failed: list[ImportFailure]


class PreviewResult(BaseModel):
    media: MediaOut
    message: str


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    detail: str


class AnalysisStart(BaseModel):
    force: bool = False


class HighlightCandidateOut(BaseModel):
    id: str
    ordinal: int
    start_seconds: float
    end_seconds: float
    title: str
    description: str
    category: str
    reasoning: str
    confidence: float | None


class AnalysisRunOut(BaseModel):
    id: str
    project_id: str
    media_id: str
    status: str
    model_name: str
    prompt_version: str
    created_at: str
    started_at: str | None
    completed_at: str | None
    error_code: str | None
    error_message: str | None
    cleanup_pending: bool
    candidates: list[HighlightCandidateOut] = Field(default_factory=list)


class FocalPointOut(BaseModel):
    time_seconds: float
    x: float
    y: float
    confidence: float | None = None


class ClipCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    start_seconds: float = Field(ge=0, allow_inf_nan=False)
    end_seconds: float = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def ordered(self):
        if self.end_seconds <= self.start_seconds:
            raise ValueError("Clip end time must be after its start time.")
        return self


class SplitSectionConfig(BaseModel):
    framing_mode: Literal["crop", "fit"] = "crop"
    zoom: float = Field(default=1, ge=1, le=3, allow_inf_nan=False)
    position_x: float = Field(default=.5, ge=0, le=1, allow_inf_nan=False)
    position_y: float = Field(default=.5, ge=0, le=1, allow_inf_nan=False)
    fit_background_color: str = Field(default="#090a0f", pattern=r"^#[0-9A-Fa-f]{6}$")


class SplitTopConfig(SplitSectionConfig):
    source_mode: Literal["same_video", "custom_image", "solid_color"] = "same_video"
    image_asset_id: str | None = None
    solid_color: str = Field(default="#151923", pattern=r"^#[0-9A-Fa-f]{6}$")


class SplitLayoutConfig(BaseModel):
    split_ratio: float = Field(default=.5, ge=.25, le=.75, allow_inf_nan=False)
    top: SplitTopConfig = Field(default_factory=SplitTopConfig)
    bottom: SplitSectionConfig = Field(default_factory=SplitSectionConfig)


class LayoutImageOut(BaseModel):
    id: str
    clip_id: str
    original_filename: str
    content_type: str
    size_bytes: int
    width: int
    height: int
    created_at: str
    image_url: str


class ClipUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    start_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    end_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    framing_mode: str | None = None
    manual_focus_x: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    manual_focus_y: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    manual_zoom: float | None = Field(default=None, ge=1, le=3, allow_inf_nan=False)
    blur_strength: float | None = Field(default=None, ge=0, le=40, allow_inf_nan=False)
    fit_background_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    manual_override_enabled: bool | None = None
    layout_type: Literal["original", "split_streamer_gameplay"] | None = None
    split_layout: SplitLayoutConfig | None = None


class ClipOut(BaseModel):
    id: str
    project_id: str
    media_id: str
    source_candidate_id: str | None
    title: str
    start_seconds: float
    end_seconds: float
    workflow_status: str
    framing_mode: str
    recommended_framing_mode: str | None
    manual_focus_x: float
    manual_focus_y: float
    manual_zoom: float
    blur_strength: float
    fit_background_color: str
    manual_override_enabled: bool = False
    layout_type: Literal["original", "split_streamer_gameplay"] = "original"
    split_layout: SplitLayoutConfig = Field(default_factory=SplitLayoutConfig)
    framing_status: str
    framing_error_code: str | None
    framing_error_message: str | None
    framing_model: str | None
    framing_requested_at: str | None
    framing_completed_at: str | None
    framing_start_seconds: float | None
    framing_end_seconds: float | None
    created_at: str
    updated_at: str
    focal_points: list[FocalPointOut] = Field(default_factory=list)


class RenderJobOut(BaseModel):
    id: str
    clip_id: str
    project_id: str
    kind: Literal["export"]
    status: str
    config_hash: str
    progress: float
    stage: str
    error_message: str | None
    output_bytes: int | None
    version_number: int | None
    approved_at: str | None
    created_at: str
    completed_at: str | None
    stream_url: str | None = None
    download_url: str | None = None
    current: bool = False


class RenderApproval(BaseModel):
    approved: bool
    caption_track_id: str | None = None


class FramingSuggestionRequest(BaseModel):
    consent_to_send_frames: bool
    retry: bool = False


class HardwareProfileOut(BaseModel):
    cpu_count: int
    memory_gib: float | None
    free_disk_gib: float
    recommendation_model: str
    explanation: str


class TranscriptionModelOut(BaseModel):
    id: str
    display_name: str
    language: str
    estimated_download_mb: int
    installed: bool
    recommended: bool


class ModelDownloadOut(BaseModel):
    id: str
    status: str
    error_message: str | None = None


class TranscriptionStart(BaseModel):
    model_id: str | None = None
    language: str = "en"
    start_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    end_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False)


class CaptionWordOut(BaseModel):
    id: str
    ordinal: int
    start_seconds: float
    end_seconds: float
    original_text: str
    text: str
    confidence: float | None


class CaptionSegmentOut(BaseModel):
    id: str
    ordinal: int
    start_seconds: float
    end_seconds: float
    generated_text: str
    override_text: str | None
    manually_edited: bool
    words: list[CaptionWordOut] = Field(default_factory=list)


class CaptionTrackOut(BaseModel):
    id: str
    clip_id: str
    transcription_run_id: str | None
    name: str
    language: str
    preset_id: str
    style_version: int
    style: dict
    grouping: dict
    position_x: float
    position_y: float
    safe_zone_profile: str
    timing_offset_seconds: float
    boundary_start_seconds: float
    boundary_end_seconds: float
    stale: bool
    created_at: str
    updated_at: str
    segments: list[CaptionSegmentOut] = Field(default_factory=list)


class TranscriptionRunOut(BaseModel):
    id: str
    clip_id: str
    media_id: str
    status: str
    model_id: str
    language: str
    device_profile: str
    clip_start_seconds: float
    clip_end_seconds: float
    started_at: str | None
    completed_at: str | None
    error_code: str | None
    error_message: str | None
    created_at: str
    caption_track_id: str | None = None


class CaptionTrackCreate(BaseModel):
    transcription_run_id: str | None = None
    name: str = Field(default="Captions", min_length=1, max_length=160)
    preset_id: str = "clean_minimal"


class CaptionTrackUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    preset_id: str | None = None
    style: dict | None = None
    grouping: dict | None = None
    position_x: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    position_y: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    safe_zone_profile: str | None = None
    timing_offset_seconds: float | None = Field(default=None, ge=-10, le=10, allow_inf_nan=False)


class CaptionSegmentUpdate(BaseModel):
    start_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    end_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    override_text: str | None = Field(default=None, max_length=500)


class CaptionWordUpdate(BaseModel):
    text: str = Field(min_length=1, max_length=100)


class CaptionReflow(BaseModel):
    max_words_per_line: int = Field(default=4, ge=1, le=12)
    max_lines: int = Field(default=2, ge=1, le=2)
