# main.py
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from typing import Optional
from PIL import Image
import piexif
import io

app = FastAPI(title="Geotag Service")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


def _to_rational_dms(value: float):
    """
    Convert signed decimal degrees to EXIF rational DMS tuples.
    EXIF expects ((deg,1), (min,1), (sec,1e6)) – all positive.
    """
    v = abs(value)
    deg = int(v)
    minutes_float = (v - deg) * 60
    minutes = int(minutes_float)
    seconds = round((minutes_float - minutes) * 60 * 1_000_000)
    return ((deg, 1), (minutes, 1), (seconds, 1_000_000))


@app.post("/geotag")
async def geotag(
    file: UploadFile = File(..., description="JPEG image to tag"),
    lat: float = Form(..., description="Latitude in decimal degrees"),
    lon: float = Form(..., description="Longitude in decimal degrees"),
    address: Optional[str] = Form(None),
):
    # Basic validation
    if not file.content_type or "image" not in file.content_type:
        raise HTTPException(status_code=415, detail="Only image uploads are accepted.")
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        raise HTTPException(status_code=422, detail="Invalid latitude/longitude.")

    # Read upload to memory and open with Pillow
    raw = await file.read()
    try:
        img = Image.open(io.BytesIO(raw))
    except Exception:
        raise HTTPException(status_code=400, detail="Unable to read image file.")

    # Build or load EXIF
    exif_src = img.info.get("exif")
    if exif_src:
        try:
            exif_dict = piexif.load(exif_src)
        except Exception:
            # Fall back to a fresh structure if parsing fails
            exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
    else:
        exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}

    # GPS tags
    gps_ifd = exif_dict.get("GPS", {})
    gps_ifd[piexif.GPSIFD.GPSLatitudeRef] = b"N" if lat >= 0 else b"S"
    gps_ifd[piexif.GPSIFD.GPSLongitudeRef] = b"E" if lon >= 0 else b"W"
    gps_ifd[piexif.GPSIFD.GPSLatitude] = _to_rational_dms(lat)
    gps_ifd[piexif.GPSIFD.GPSLongitude] = _to_rational_dms(lon)

    # Optional: store address in a user comment (0th IFD)
    if address:
        # EXIF UserComment must be bytes; prefix with ASCII tag
        user_comment = b"ASCII\x00\x00\x00" + address.encode("utf-8", errors="ignore")
        exif_dict["Exif"][piexif.ExifIFD.UserComment] = user_comment

    exif_dict["GPS"] = gps_ifd
    exif_bytes = piexif.dump(exif_dict)

    # Ensure JPEG output (EXIF is preserved in JPEG)
    if img.mode != "RGB":
        img = img.convert("RGB")

    out = io.BytesIO()
    try:
        img.save(out, format="JPEG", exif=exif_bytes, quality=95, optimize=True)
    except Exception:
        # If save with EXIF fails, emit a clear error
        return JSONResponse(
            status_code=500,
            content={"error": "Failed to embed EXIF GPS data into image."},
        )
    out.seek(0)

    return StreamingResponse(
        out,
        media_type="image/jpeg",
        headers={"Content-Disposition": 'attachment; filename="geotagged.jpg"'},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000)
