"""Local, best-effort Windows resource inspection for transcription advice."""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess

from app.core.config import settings


def hardware_profile() -> dict:
    cpu_count = os.cpu_count() or 1
    memory_gib = _memory_gib()
    free_disk_gib = round(shutil.disk_usage(settings.workspace_dir).free / 1024**3, 1)
    if memory_gib is not None and memory_gib >= 8 and cpu_count >= 8:
        recommendation = ("small.en", "cpu", "int8", "Your CPU and memory are suitable for small.en in local INT8 mode. Processing time depends on clip length and speech density.")
    else:
        recommendation = ("base.en", "cpu", "int8", "Use base.en in local INT8 mode to reduce memory use. It trades some accuracy for a lighter workload.")
    return {"cpu_count": cpu_count, "memory_gib": memory_gib, "free_disk_gib": free_disk_gib, "recommendation_model": recommendation[0], "explanation": recommendation[3] + " Transcription always runs on CPU INT8 and may take longer."}


def _memory_gib() -> float | None:
    if os.name != "nt":
        return None
    class MemoryStatus(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return round(status.ullTotalPhys / 1024**3, 1)


