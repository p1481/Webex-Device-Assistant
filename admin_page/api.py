from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse


router = APIRouter(prefix="/admin-page", tags=["admin-page"])
REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_FILE = STATIC_DIR / "index.html"
DOCS_FILE = STATIC_DIR / "docs.html"
DOCS_KO_FILE = STATIC_DIR / "docs-ko.html"
ARCHITECTURE_GUIDE_FILE = STATIC_DIR / "architecture-guide.html"
WEBEX_TEST_FILE = STATIC_DIR / "webex-test.html"
ALLOWED_ASSETS = {
    "admin.css": STATIC_DIR / "admin.css",
    "admin.js": STATIC_DIR / "admin.js",
    "webex-test.js": STATIC_DIR / "webex-test.js",
}
MANUAL_FILES = {
    "ARCHITECTURE.md": REPO_ROOT / "ARCHITECTURE.md",
    "INSTALL.md": REPO_ROOT / "INSTALL.md",
    "USER_MANUAL.md": REPO_ROOT / "USER_MANUAL.md",
    "MANUAL_KO.md": REPO_ROOT / "MANUAL_KO.md",
}


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def admin_page() -> HTMLResponse:
    return HTMLResponse(INDEX_FILE.read_text(encoding="utf-8"))


@router.get("/docs", response_class=HTMLResponse)
@router.get("/docs/", response_class=HTMLResponse)
async def admin_page_docs() -> HTMLResponse:
    return HTMLResponse(DOCS_FILE.read_text(encoding="utf-8"))


@router.get("/docs-ko", response_class=HTMLResponse)
@router.get("/docs-ko/", response_class=HTMLResponse)
async def admin_page_docs_ko() -> HTMLResponse:
    return HTMLResponse(DOCS_KO_FILE.read_text(encoding="utf-8"))


@router.get("/architecture-guide", response_class=HTMLResponse)
@router.get("/architecture-guide/", response_class=HTMLResponse)
async def admin_page_architecture_guide() -> HTMLResponse:
    return HTMLResponse(ARCHITECTURE_GUIDE_FILE.read_text(encoding="utf-8"))


@router.get("/webex-test", response_class=HTMLResponse)
@router.get("/webex-test/", response_class=HTMLResponse)
async def admin_page_webex_test() -> HTMLResponse:
    return HTMLResponse(WEBEX_TEST_FILE.read_text(encoding="utf-8"))


@router.get("/static/{asset_name}")
async def admin_page_asset(asset_name: str) -> FileResponse:
    asset_path = ALLOWED_ASSETS.get(asset_name)
    if asset_path is None:
        raise HTTPException(status_code=404, detail="Admin asset not found.")
    return FileResponse(asset_path)


@router.get("/manuals/{manual_name}")
async def admin_page_manual(manual_name: str) -> FileResponse:
    manual_path = MANUAL_FILES.get(manual_name)
    if manual_path is None:
        raise HTTPException(status_code=404, detail="Manual not found.")
    return FileResponse(manual_path, media_type="text/markdown")


@router.get("/healthz")
async def healthz() -> dict[str, object]:
    return {
        "status": "ok",
        "ui": "ready",
        "page": "/admin-page",
        "note": "Admin page is served from static assets and backed by /admin/* APIs.",
    }
