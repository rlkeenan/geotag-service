# main.py
from fastapi import FastAPI
from pydantic import BaseModel
import base64, io, piexif
from PIL import Image

app = FastAPI()

@app.get("/healthz")
def healthz():
    return {"status": "ok"}

class GeoTagRequest(BaseModel):
    image_base64: str          # data URI or raw base64 of a JPEG/PNG
    latitude: float
    longitude: float

def _to_deg(value: float):
    d = int(abs(value))
    m_full = (abs(value) - d) * 60
    m = int(m_full)
    s = int(round((m_full - m) * 60 * 100))
    return ((d, 1), (m, 1), (s, 100))

@app.post("/geotag")
def geotag(req: GeoTagRequest):
    raw = req.image_base64.split(",")[-1]  # strip data URI if present
    img_bytes = base64.b64decode(raw)

    # ensure JPEG output for EXIF
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")

    gps = {
        piexif.GPSIFD.GPSLatitudeRef: b"N" if req.latitude >= 0 else b"S",
        piexif.GPSIFD.GPSLongitudeRef: b"E" if req.longitude >= 0 else b"W",
        piexif.GPSIFD.GPSLatitude: _to_deg(req.latitude),
        piexif.GPSIFD.GPSLongitude: _to_deg(req.longitude),
    }
    exif_dict = {"GPS": gps}
    exif_bytes = piexif.dump(exif_dict)

    out = io.BytesIO()
    img.save(out, format="JPEG", exif=exif_bytes)
    b64 = base64.b64encode(out.getvalue()).decode("utf-8")
    return {"image_base64": f"data:image/jpeg;base64,{b64}"}
