"""Upload, HEAD-check, and delete a tiny temporary object in the R2 ig-reels/ prefix."""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import instagram_r2_storage as r2  # noqa: E402


def main() -> int:
    path = r2.make_smoke_test_file()
    key = r2.new_object_key()
    failed = False
    try:
        urls = r2.upload_object(path, key)
        print(f"Uploaded disposable R2 test object: {key}")
        print(f"Presigned GET URL location (query redacted): {r2.display_url_without_signature(urls.get_url)}")
        r2.verify_presigned_url(urls.head_url, path.stat().st_size)
        print("HEAD check passed: HTTP 200, video/mp4, matching Content-Length, no redirects.")
    except Exception as exc:
        failed = True
        print(f"R2 check failed: {exc}", file=sys.stderr)
    finally:
        try:
            # Deleting a UUID key is safe even if upload_file failed after the
            # server accepted the bytes but before the client got a response.
            r2.delete_object(key)
            print("Disposable R2 test object deleted.")
        except r2.R2StorageError as exc:
            failed = True
            print(f"R2 test object cleanup failed; check the bucket lifecycle rule: {exc}", file=sys.stderr)
        path.unlink(missing_ok=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
