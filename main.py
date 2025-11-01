import os
import io
from typing import Optional, Tuple

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Depends, Security
from fastapi.security.api_key import APIKeyHeader
from starlette.responses import StreamingResponse, JSONResponse
from PIL import Image
import piexif

app = FastAPI(title="Geotag Service", version="1.0.0")

# -------- Security: API key via header --------
API_KEY = os.getenv("API_KEY")  # set in Render → Environment
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def require_key(key: Optional[str] = Security(api_key_header)):
    if not API_KEY:
        # If you forgot to set it in Render, block by default
        raise HTTPException(status_code=500, detail="Server missing API_KEY")
    if not key or key != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True

# -------- Health check --------
@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}

# -------- helpers for GPS EXIF --------
def _deg_to_dms_rational(deg: float) -> Tuple[tuple, int]:
    sign = 1 if deg >= 0 else -1
    deg = abs(deg)
    d = int(deg)
    m_float = (deg - d) * 60
    m = int(m_float)
    s = round((m_float - m) * 60 * 10000)
    return ((d, 1), (m, 1), (s, 10000)), sign

def _apply_gps_exif(img: Image.Image, lat: float, lon: float, desc: Optional[str]) -> bytes:
    # load existing exif if present
    exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
    raw = img.info.get("exif")
    if raw:
        try:
            exif_dict = piexif.load(raw)
        except Exception:
            exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}

    lat_dms, lat_sign = _deg_to_dms_rational(lat)
    lon_dms, lon_sign = _deg_to_dms_rational(lon)

    exif_dict["GPS"][piexif.GPSIFD.GPSLatitudeRef]  = "N" if lat_sign >= 0 else "S"
    exif_dict["GPS"][piexif.GPSIFD.GPSLatitude]     = lat_dms
    exif_dict["GPS"][piexif.GPSIFD.GPSLongitudeRef] = "E" if lon_sign >= 0 else "W"
    exif_dict["GPS"][piexif.GPSIFD.GPSLongitude]    = lon_dms

    if desc:
        exif_dict["0th"][piexif.ImageIFD.ImageDescription] = desc.encode("utf-8", "ignore")

    out = io.BytesIO()
    # Ensure JPEG with EXIF block
    save_img = img
    if save_img.mode not in ("RGB", "L"):
        save_img = save_img.convert("RGB")
    save_img.save(out, format="JPEG", exif=piexif.dump(exif_dict), quality=92)
    out.seek(0)
    return out.getvalue()

# -------- main endpoint --------
@app.post("/geotag", dependencies=[Depends(require_key)], response_class=StreamingResponse)
async def geotag(
    file: UploadFile = File(...),
    lat: float = Form(...),
    lon: float = Form(...),
    address: Optional[str] = Form(None),
):
    # basic validation
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="Only image uploads are accepted")

    content = await file.read()
    if len(content) > 20 * 1024 * 1024:  # 20 MB guard
        raise HTTPException(status_code=413, detail="File exceeds 20MB")

    try:
        img = Image.open(io.BytesIO(content))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image data")

    try:
        with_exif = _apply_gps_exif(img, lat, lon, address)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"EXIF write failed: {e}")

    filename = f"geotagged_{file.filename or 'image.jpg'}"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(io.BytesIO(with_exif), media_type="image/jpeg", headers=headers)
