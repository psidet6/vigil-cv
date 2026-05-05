import io
import os
from datetime import datetime
from urllib.parse import urlparse

from PIL import Image


def sanitize_zip_name(name: str) -> str:
    invalid = set('/\\:*?"<>|')
    fixed = "".join("_" if char in invalid else char for char in name).strip()
    return fixed or "image"


def filename_from_url(url: str) -> str:
    parsed = urlparse(url)
    base = os.path.basename(parsed.path) or "image"
    base = base.split(";")[0]
    return sanitize_zip_name(base) or "image"


def infer_ext_from_bytes(img_bytes: bytes) -> str:
    try:
        img = Image.open(io.BytesIO(img_bytes))
        fmt = (img.format or "").upper()
        return {
            "JPEG": ".jpg",
            "JPG": ".jpg",
            "PNG": ".png",
            "BMP": ".bmp",
            "WEBP": ".webp",
            "GIF": ".gif",
            "TIFF": ".tif",
        }.get(fmt, ".jpg")
    except Exception:
        return ".jpg"


def ensure_hours_list(raw_list) -> list[str]:
    hours: list[str] = []
    if not raw_list:
        return hours
    items = raw_list if isinstance(raw_list, list) else [raw_list]
    for hour in items:
        try:
            value = int(hour)
            if 0 <= value <= 23:
                hours.append(f"{value:02d}")
        except Exception:
            continue
    return hours


def parse_and_normalize_dt(value: str) -> str:
    if not value:
        raise ValueError("time is empty")

    value = value.strip()
    formats = [
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ]
    dt = None
    for fmt in formats:
        try:
            dt = datetime.strptime(value, fmt)
            break
        except Exception:
            continue
    if dt is None:
        raise ValueError(f"unable to parse datetime: {value}")
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def default_time_range() -> tuple[str, str]:
    end = datetime.now()
    start = end.replace(minute=0, second=0, microsecond=0)
    fmt = "%Y-%m-%d %H:%M:%S"
    return start.strftime(fmt), end.strftime(fmt)


def to_datetime_local_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def format_timestamp(ts: int | None) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(ts).strftime("%Y/%m/%d %H:%M:%S")
