"""Validated request and response models for projects and media."""

from __future__ import annotations

from typing import Any, Literal

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


class ClipwingImportRequest(BaseModel):
    analysis_text: str = Field(min_length=1, max_length=100_000)
    confirm_rights: bool


class ClipwingDownloadRequest(BaseModel):
    format_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")


class ClipwingFormatOut(BaseModel):
    format_id: str
    label: str
    width: int | None
    height: int
    ext: str
    video_codec: str
    audio_codec: str | None
    fps: float | None
    filesize_bytes: int | None


class ClipwingEntryOut(BaseModel):
    id: str
    ordinal: int
    title: str
    start_seconds: float
    end_seconds: float
    score: float | None
    transcript: str | None
    caption_source: str
    selected_format_id: str | None
    status: str
    progress: float
    error_message: str | None
    media_id: str | None
    clip_id: str | None
    video_url: str


class ClipwingImportOut(BaseModel):
    id: str
    project_id: str
    status: str
    stage: str
    progress: float
    video_title: str | None
    video_duration_seconds: float | None
    formats: list[ClipwingFormatOut] = Field(default_factory=list)
    error_message: str | None
    created_at: str
    updated_at: str
    entries: list[ClipwingEntryOut]


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
    source_mode: Literal["same_video", "custom_image", "solid_color"] = "same_video"
    image_asset_id: str | None = None
    solid_color: str = Field(default="#151923", pattern=r"^#[0-9A-Fa-f]{6}$")
    framing_mode: Literal["crop", "fit"] = "crop"
    vertical_crop_percent: float = Field(default=0, ge=0, le=40, allow_inf_nan=False)
    zoom: float = Field(default=1, ge=1, le=10, allow_inf_nan=False)
    position_x: float = Field(default=.5, ge=0, le=1, allow_inf_nan=False)
    position_y: float = Field(default=.5, ge=0, le=1, allow_inf_nan=False)
    fit_background_color: str = Field(default="#090a0f", pattern=r"^#[0-9A-Fa-f]{6}$")


class SplitTopConfig(SplitSectionConfig):
    pass


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


class CustomTextConfig(BaseModel):
    enabled: bool = False
    text: str = Field(default="", max_length=1000)
    preset_id: str = Field(default="gaming_pulse", pattern=r"^[a-z0-9_]{1,48}$")
    position_x: float = Field(default=0.5, ge=0, le=1, allow_inf_nan=False)
    position_y: float = Field(default=0.5, ge=0, le=1, allow_inf_nan=False)
    font_family: str = Field(default="Arial Black", max_length=80)
    font_weight: int = Field(default=900, ge=100, le=900)
    font_size: int = Field(default=76, ge=18, le=160)
    text_color: str = Field(default="#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    background_color: str = Field(default="#000000", pattern=r"^#[0-9A-Fa-f]{6}$")
    background_opacity: float = Field(default=0, ge=0, le=1, allow_inf_nan=False)
    animation: Literal["none", "fade", "pop", "karaoke", "pop_karaoke"] = "pop_karaoke"
    animation_ms: int = Field(default=120, ge=0, le=1000)
    stroke_enabled: bool = False
    stroke_width: float = Field(default=4, ge=0, le=20, allow_inf_nan=False)
    stroke_color: str = Field(default="#000000", pattern=r"^#[0-9A-Fa-f]{6}$")
    shadow_enabled: bool = True
    shadow_blur: float = Field(default=5, ge=0, le=40, allow_inf_nan=False)
    shadow_color: str = Field(default="#000000", pattern=r"^#[0-9A-Fa-f]{6}$")
    shadow_x: float = Field(default=3, ge=-30, le=30, allow_inf_nan=False)
    shadow_y: float = Field(default=3, ge=-30, le=30, allow_inf_nan=False)


class ClipUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    start_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    end_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    framing_mode: str | None = None
    manual_focus_x: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    manual_focus_y: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    manual_zoom: float | None = Field(default=None, ge=1, le=3, allow_inf_nan=False)
    vertical_crop_percent: float | None = Field(default=None, ge=0, le=40, allow_inf_nan=False)
    blur_strength: float | None = Field(default=None, ge=0, le=40, allow_inf_nan=False)
    fit_background_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    manual_override_enabled: bool | None = None
    layout_type: Literal["original", "split_streamer_gameplay"] | None = None
    split_layout: SplitLayoutConfig | None = None
    custom_text: CustomTextConfig | None = None


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
    vertical_crop_percent: float = 0
    blur_strength: float
    fit_background_color: str
    manual_override_enabled: bool = False
    layout_type: Literal["original", "split_streamer_gameplay"] = "original"
    split_layout: SplitLayoutConfig = Field(default_factory=SplitLayoutConfig)
    custom_text: CustomTextConfig = Field(default_factory=CustomTextConfig)
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
    resolution: Literal["1080", "1440"] = "1080"


class RenderApproval(BaseModel):
    approved: bool
    caption_track_id: str | None = None
    resolution: Literal["1080", "1440"] = "1080"


class SocialContentStart(BaseModel):
    consent_to_upload_video: bool


class SocialPackageUpdate(BaseModel):
    content: dict[str, Any]


class ManualSocialContentImport(BaseModel):
    output: str = Field(min_length=1, max_length=100_000)


class SocialContentGenerationOut(BaseModel):
    id: str
    render_job_id: str
    status: str
    progress: float
    stage: str
    model_name: str
    prompt_version: str
    error_code: str | None
    error_message: str | None
    cleanup_pending: bool
    created_at: str
    completed_at: str | None
    generated_packages: dict[str, dict[str, Any]] | None = None
    packages: dict[str, dict[str, Any]] | None = None


class YouTubeStatusOut(BaseModel):
    configured: bool
    connected: bool
    authorization_pending: bool = False
    message: str


class YouTubeUploadStart(BaseModel):
    generation_id: str
    privacy_status: Literal["private", "unlisted", "public"] = "private"


class YouTubeUploadOut(BaseModel):
    id: str
    render_job_id: str
    generation_id: str
    status: Literal["queued", "uploading", "completed", "failed", "interrupted"]
    progress: float
    stage: str
    privacy_status: Literal["private", "unlisted", "public"]
    video_id: str | None
    video_url: str | None = None
    error_message: str | None
    created_at: str
    completed_at: str | None


class FacebookPageOut(BaseModel):
    id: str
    name: str
    instagram_user_id: str | None = None
    instagram_username: str | None = None


class FacebookStatusOut(BaseModel):
    configured: bool
    connected: bool
    authorization_pending: bool = False
    authorization_error: str | None = None
    pages: list[FacebookPageOut] = Field(default_factory=list)
    message: str


class FacebookUploadStart(BaseModel):
    generation_id: str
    page_id: str = Field(min_length=1, max_length=80)


class FacebookUploadOut(BaseModel):
    id: str
    render_job_id: str
    generation_id: str
    page_id: str
    page_name: str
    status: Literal["queued", "uploading", "completed", "failed", "interrupted"]
    progress: float
    stage: str
    video_id: str | None
    post_id: str | None
    video_url: str | None = None
    error_message: str | None
    created_at: str
    completed_at: str | None


class InstagramAccountOut(BaseModel):
    instagram_user_id: str
    instagram_username: str
    page_id: str
    page_name: str


class InstagramStatusOut(BaseModel):
    configured: bool
    connected: bool
    r2_storage_configured: bool = False
    authorization_pending: bool = False
    authorization_error: str | None = None
    accounts: list[InstagramAccountOut] = Field(default_factory=list)
    message: str


class InstagramUploadStart(BaseModel):
    approved: bool = False
    generation_id: str
    instagram_user_id: str = Field(min_length=1, max_length=80)


class InstagramUploadOut(BaseModel):
    id: str
    render_job_id: str
    generation_id: str
    page_id: str
    page_name: str
    instagram_user_id: str
    instagram_username: str
    status: Literal["queued", "uploading", "completed", "failed", "interrupted"]
    progress: float
    stage: str
    media_id: str | None
    permalink: str | None = None
    container_id: str | None = None
    error_message: str | None
    created_at: str
    completed_at: str | None


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
