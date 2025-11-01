# main.py
from fastapi import FastAPI, UploadFile, File, Form, Response, HTTPException
from fastapi.responses import JSONResponse
from typing import Optional
from PIL import Image
import piexif
import io

app = FastAPI(title="Geotag Service")

@app.get("/healthz")
def healthz():
    return {"status": "ok"}

def _to_dms_rationals(value: float):
    """Convert decimal degrees to EXIF DMS rationals"""
    sign = 1 if value >= 0 else -1
    v = abs(value)
    deg = int(v)
    minutes_float = (v - deg) * 60
    minutes = int(minutes_float)
    seconds = round((minutes_float - minutes) * 60, 6)
    # Use integer rationals to avoid float in EXIF
    return (
        (deg, 1),
        (minutes, 1),
        (int(seconds * 1_000_000), 1_000_000),
    ), sign

@app.post("/geotag")
async def geotag(
    file: UploadFile = File(...),
    lat: float = Form(...),
    lon: float = Form(...),
    address: Optional[str] = Form(None),
):
    try:
        raw = await file.read()
        if not raw:
            raise HTTPException(status_code=400, detail="Empty file")

        # Ensure JPEG output
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=95)
        jpeg_bytes = buf.getvalue()

        # Build EXIF GPS
        lat_dms, lat_sign = _to_dms_rationals(lat)
        lon_dms, lon_sign = _to_dms_rationals(lon)

        gps_ifd = {
            piexif.GPSIFD.GPSLatitudeRef: b"N" if lat_sign >= 0 else b"S",
            piexif.GPSIFD.GPSLatitude: lat_dms,
            piexif.GPSIFD.GPSLongitudeRef: b"E" if lon_sign >= 0 else b"W",
            piexif.GPSIFD.GPSLongitude: lon_dms,
        }

        exif_ifd = {}
        if address:
            # EXIF UserComment (must be ASCII header + bytes)
            exif_ifd[piexif.ExifIFD.UserComment] = b"ASCII\x00\x00\x00" + address.encode("ascii", "ignore")

        exif_dict = {"0th": {}, "Exif": exif_ifd, "GPS": gps_ifd, "1st": {}, "thumbnail": None}
        exif_bytes = piexif.dump(exif_dict)

        # Insert EXIF and return binary
        out_bytes = piexif.insert(exif_bytes, jpeg_bytes)
        return Response(
            content=out_bytes,
            media_type="image/jpeg",
            headers={"Content-Disposition": f'attachment; filename="geotagged.jpg"'},
        )
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/")
def root():
    return {"endpoints": ["/healthz", "/docs", "/geotag (POST multipart/form-data)"]}
