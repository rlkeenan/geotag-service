from fastapi import FastAPI
from fastapi.responses import FileResponse
import requests, uuid, piexif, os

app = FastAPI()

def deg_to_dmsRational(deg_float):
    deg = int(deg_float)
    minutes_float = abs(deg_float - deg) * 60
    minutes = int(minutes_float)
    seconds = round((minutes_float - minutes) * 60 * 10000)
    return ((abs(deg), 1), (minutes, 1), (seconds, 10000))

@app.get("/geotag")
def geotag(image_url: str, lat: float, lng: float):
    img_data = requests.get(image_url).content
    temp_filename = f"/tmp/{uuid.uuid4()}.jpg"
    with open(temp_filename, "wb") as f:
        f.write(img_data)

    gps_ifd = {
        piexif.GPSIFD.GPSLatitude: deg_to_dmsRational(lat),
        piexif.GPSIFD.GPSLatitudeRef: "N" if lat >= 0 else "S",
        piexif.GPSIFD.GPSLongitude: deg_to_dmsRational(lng),
        piexif.GPSIFD.GPSLongitudeRef: "E" if lng >= 0 else "W",
    }

    exif_dict = {"GPS": gps_ifd}
    exif_bytes = piexif.dump(exif_dict)
    piexif.insert(exif_bytes, temp_filename)

    return FileResponse(temp_filename, media_type="image/jpeg")