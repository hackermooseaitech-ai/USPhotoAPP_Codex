from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from django.core.files.base import ContentFile
from PIL import Image, ImageDraw, ImageFont, ImageOps

OUTPUT_SIZE = 600
PRINT_TEMPLATE_SIZE = (1800, 1200)  # 6x4 inches at 300 DPI, landscape.
TARGET_HEAD_RATIO = 0.60
TARGET_EYE_HEIGHT_FROM_BOTTOM = 0.64
MIN_HEAD_RATIO = 0.53
MAX_HEAD_RATIO = 0.62
DEFAULT_BACKGROUND_COLOR = "#FFFFFF"


@dataclass(frozen=True)
class FaceGeometry:
    center_x: float
    eye_y: float
    head_top_y: float
    chin_y: float

    @property
    def head_height(self) -> float:
        return max(1.0, self.chin_y - self.head_top_y)


@dataclass(frozen=True)
class ProcessedPhoto:
    final_jpeg: ContentFile
    preview_jpeg: ContentFile
    print_template_jpeg: ContentFile
    notes: list[str]


@dataclass(frozen=True)
class PreparedPhoto:
    prepared_jpeg: ContentFile
    face: FaceGeometry | None
    notes: list[str]


def process_order_photo(uploaded_file, head_ratio: float = TARGET_HEAD_RATIO, offset_x: float = 0, offset_y: float = 0, background_color: str = DEFAULT_BACKGROUND_COLOR) -> ProcessedPhoto:
    image = Image.open(uploaded_file)
    image = ImageOps.exif_transpose(image).convert("RGB")

    notes: list[str] = []
    head_ratio = min(max(head_ratio, MIN_HEAD_RATIO), MAX_HEAD_RATIO)
    white_background = _remove_background_to_color(image, notes, background_color)
    face = _detect_face_geometry(white_background, notes)
    return render_visa_photo(white_background, face, notes, head_ratio=head_ratio, offset_x=offset_x, offset_y=offset_y, background_color=background_color)


def prepare_photo_source(uploaded_file, background_color: str = DEFAULT_BACKGROUND_COLOR) -> PreparedPhoto:
    image = Image.open(uploaded_file)
    image = ImageOps.exif_transpose(image).convert("RGB")

    notes: list[str] = []
    white_background = _remove_background_to_color(image, notes, background_color)
    face = _detect_face_geometry(white_background, notes)
    return PreparedPhoto(
        prepared_jpeg=_jpeg_file(white_background, "prepared-photo.jpg", quality=94),
        face=face,
        notes=notes,
    )


def render_visa_photo(
    prepared_file,
    face: FaceGeometry | None,
    notes: list[str] | None = None,
    head_ratio: float = TARGET_HEAD_RATIO,
    offset_x: float = 0,
    offset_y: float = 0,
    background_color: str = DEFAULT_BACKGROUND_COLOR,
) -> ProcessedPhoto:
    if isinstance(prepared_file, Image.Image):
        white_background = prepared_file
    else:
        white_background = Image.open(prepared_file)
    white_background = ImageOps.exif_transpose(white_background).convert("RGB")

    render_notes = list(notes or [])
    head_ratio = min(max(head_ratio, MIN_HEAD_RATIO), MAX_HEAD_RATIO)
    final = _crop_to_visa_spec(white_background, face, render_notes, head_ratio=head_ratio, offset_x=offset_x, offset_y=offset_y, background_color=background_color)
    preview = _add_watermark(final.copy())
    print_template = _make_4x6_print_template(final, background_color)

    return ProcessedPhoto(
        final_jpeg=_jpeg_file(final, "visa-photo-600.jpg"),
        preview_jpeg=_jpeg_file(preview, "visa-photo-preview.jpg", quality=88),
        print_template_jpeg=_jpeg_file(print_template, "visa-photo-4x6.jpg"),
        notes=render_notes,
    )


def _remove_background_to_color(image: Image.Image, notes: list[str], background_color: str) -> Image.Image:
    try:
        from rembg import remove
    except Exception:
        notes.append("rembg is not installed; background removal was skipped.")
        return _paste_on_background(image, background_color)

    result = remove(image)
    if not isinstance(result, Image.Image):
        result = Image.open(BytesIO(result))

    result = ImageOps.exif_transpose(result).convert("RGBA")
    canvas = Image.new("RGBA", result.size, background_color)
    canvas.alpha_composite(result)
    notes.append(f"Background removed with rembg and replaced with {background_color}.")
    return canvas.convert("RGB")


def _detect_face_geometry(image: Image.Image, notes: list[str]) -> FaceGeometry | None:
    try:
        import mediapipe as mp
        import numpy as np
    except Exception:
        notes.append("mediapipe is not installed; trying OpenCV face detection fallback.")
        return _detect_face_geometry_with_opencv(image, notes)

    if not hasattr(mp, "solutions"):
        notes.append("Installed mediapipe does not expose the legacy solutions API; used OpenCV face detection fallback.")
        return _detect_face_geometry_with_opencv(image, notes)

    rgb = np.array(image)
    with mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True,
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5,
    ) as face_mesh:
        result = face_mesh.process(rgb)

    if not result.multi_face_landmarks:
        notes.append("No face landmarks detected; used conservative center crop fallback.")
        return None

    landmarks = result.multi_face_landmarks[0].landmark
    width, height = image.size

    def point(index: int) -> tuple[float, float]:
        landmark = landmarks[index]
        return landmark.x * width, landmark.y * height

    left_eye = _average_points([point(i) for i in (33, 133, 159, 145)])
    right_eye = _average_points([point(i) for i in (362, 263, 386, 374)])
    forehead = point(10)
    chin = point(152)
    face_center_x = (left_eye[0] + right_eye[0]) / 2
    eye_y = (left_eye[1] + right_eye[1]) / 2

    face_height = max(1.0, chin[1] - forehead[1])
    estimated_head_top_y = max(0.0, forehead[1] - face_height * 0.35)

    notes.append("Face landmarks detected with mediapipe.")
    return FaceGeometry(
        center_x=face_center_x,
        eye_y=eye_y,
        head_top_y=estimated_head_top_y,
        chin_y=chin[1],
    )


def _detect_face_geometry_with_opencv(image: Image.Image, notes: list[str]) -> FaceGeometry | None:
    try:
        import cv2
        import numpy as np
    except Exception:
        notes.append("OpenCV is not available; used conservative center crop fallback.")
        return None

    rgb = np.array(image)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    eye_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")
    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.08, minNeighbors=5, minSize=(80, 80))

    if len(faces) == 0:
        notes.append("No face detected with OpenCV; used conservative center crop fallback.")
        return None

    x, y, w, h = max(faces, key=lambda rect: rect[2] * rect[3])
    face_roi = gray[y : y + h, x : x + w]
    eyes = eye_cascade.detectMultiScale(face_roi, scaleFactor=1.08, minNeighbors=5, minSize=(18, 18))

    if len(eyes) >= 2:
        eyes = sorted(eyes, key=lambda rect: rect[2] * rect[3], reverse=True)[:2]
        eye_centers = [(x + ex + ew / 2, y + ey + eh / 2) for ex, ey, ew, eh in eyes]
        center_x = sum(point[0] for point in eye_centers) / 2
        eye_y = sum(point[1] for point in eye_centers) / 2
    else:
        center_x = x + w / 2
        eye_y = y + h * 0.42

    head_top_y = max(0.0, y - h * 0.18)
    chin_y = min(float(image.height), y + h * 1.10)
    notes.append("Face detected with OpenCV fallback.")
    return FaceGeometry(center_x=center_x, eye_y=eye_y, head_top_y=head_top_y, chin_y=chin_y)


def _crop_to_visa_spec(
    image: Image.Image,
    face: FaceGeometry | None,
    notes: list[str],
    head_ratio: float,
    offset_x: float,
    offset_y: float,
    background_color: str,
) -> Image.Image:
    width, height = image.size

    if face is None:
        base_side = min(width, height)
        zoom_side = base_side * (TARGET_HEAD_RATIO / head_ratio)
        left = (width - zoom_side) / 2 - (offset_x / OUTPUT_SIZE) * zoom_side
        top = max(0, (height - zoom_side) * 0.38) - (offset_y / OUTPUT_SIZE) * zoom_side
        crop = _safe_square_crop(image, left, top, zoom_side, background_color)
        notes.append(f"Output resized to 600x600 JPEG at 300 DPI with fallback zoom target {head_ratio:.0%}.")
        return crop.resize((OUTPUT_SIZE, OUTPUT_SIZE), Image.Resampling.LANCZOS)

    min_side_for_face = face.head_height / 0.69
    max_side_for_face = face.head_height / 0.50
    crop_side = min(max(face.head_height / head_ratio, min_side_for_face), max_side_for_face)

    left = face.center_x - crop_side / 2 - (offset_x / OUTPUT_SIZE) * crop_side
    top = face.eye_y - (1 - TARGET_EYE_HEIGHT_FROM_BOTTOM) * crop_side - (offset_y / OUTPUT_SIZE) * crop_side

    crop = _safe_square_crop(image, left, top, crop_side, background_color)
    final = crop.resize((OUTPUT_SIZE, OUTPUT_SIZE), Image.Resampling.LANCZOS)
    effective_eye_from_bottom = TARGET_EYE_HEIGHT_FROM_BOTTOM - (offset_y / OUTPUT_SIZE)
    notes.append(f"Cropped to 600x600 with head height targeted at {head_ratio:.0%}, eye-line near {effective_eye_from_bottom:.0%} from the bottom, and manual offset x={offset_x:.0f}px y={offset_y:.0f}px.")
    return final


def _safe_square_crop(image: Image.Image, left: float, top: float, side: float, background_color: str = DEFAULT_BACKGROUND_COLOR) -> Image.Image:
    width, height = image.size
    side = max(1.0, side)
    right = left + side
    bottom = top + side

    pad_left = max(0, int(round(-left)))
    pad_top = max(0, int(round(-top)))
    pad_right = max(0, int(round(right - width)))
    pad_bottom = max(0, int(round(bottom - height)))

    if any((pad_left, pad_top, pad_right, pad_bottom)):
        padded = Image.new("RGB", (width + pad_left + pad_right, height + pad_top + pad_bottom), background_color)
        padded.paste(image, (pad_left, pad_top))
        image = padded
        left += pad_left
        top += pad_top

    box = (int(round(left)), int(round(top)), int(round(left + side)), int(round(top + side)))
    return image.crop(box)


def _add_watermark(image: Image.Image) -> Image.Image:
    overlay = Image.new("RGBA", image.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    font = _font(42)
    text = "HACKER MOOSE PREVIEW"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    for y in range(80, image.height, 150):
        x = (image.width - text_width) / 2
        draw.text((x, y), text, fill=(30, 30, 30, 82), font=font)

    locked = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(locked)
    draw.rounded_rectangle((28, image.height - 86, image.width - 28, image.height - 28), radius=10, fill="#111827")
    draw.text((48, image.height - 72), "Pay to download high-resolution JPEG + 4x6 template", fill="#FFFFFF", font=_font(20))
    return locked


def _make_4x6_print_template(photo: Image.Image, background_color: str = DEFAULT_BACKGROUND_COLOR) -> Image.Image:
    canvas = Image.new("RGB", PRINT_TEMPLATE_SIZE, background_color)
    photo = photo.resize((600, 600), Image.Resampling.LANCZOS)
    positions = [(0, 0), (600, 0), (1200, 0), (0, 600), (600, 600), (1200, 600)]
    for position in positions:
        canvas.paste(photo, position)
    return canvas


def _jpeg_file(image: Image.Image, filename: str, quality: int = 95) -> ContentFile:
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=quality, dpi=(300, 300), optimize=True)
    return ContentFile(buffer.getvalue(), name=filename)


def _paste_on_background(image: Image.Image, background_color: str) -> Image.Image:
    canvas = Image.new("RGB", image.size, background_color)
    canvas.paste(image.convert("RGB"))
    return canvas


def _average_points(points: list[tuple[float, float]]) -> tuple[float, float]:
    return sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)


def _font(size: int):
    candidates = [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()
