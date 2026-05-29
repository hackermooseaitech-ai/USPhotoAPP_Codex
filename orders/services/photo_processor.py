from dataclasses import dataclass
from collections import deque
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from PIL import Image, ImageDraw, ImageFont, ImageOps

OUTPUT_SIZE = 600
PRINT_TEMPLATE_SIZE = (1800, 1200)  # 6x4 inches at 300 DPI, landscape.
TARGET_HEAD_RATIO = 0.60
TARGET_EYE_Y_RATIO = 0.50
MIN_HEAD_RATIO = 0.53
MAX_HEAD_RATIO = 0.62
DEFAULT_BACKGROUND_COLOR = "#FFFFFF"
MAX_PROCESSING_SIDE = 900
PROCESSOR_VERSION = "white-bg-v6"


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
    image = _load_processing_image(uploaded_file)

    notes: list[str] = []
    head_ratio = min(max(head_ratio, MIN_HEAD_RATIO), MAX_HEAD_RATIO)
    white_background = _remove_background_to_color(image, notes, background_color)
    face = _detect_face_geometry(white_background, notes)
    return render_visa_photo(white_background, face, notes, head_ratio=head_ratio, offset_x=offset_x, offset_y=offset_y, background_color=background_color)


def prepare_photo_source(uploaded_file, background_color: str = DEFAULT_BACKGROUND_COLOR) -> PreparedPhoto:
    image = _load_processing_image(uploaded_file)

    notes: list[str] = []
    white_background = _remove_background_to_color(image, notes, background_color)
    face = _detect_face_geometry(white_background, notes)
    return PreparedPhoto(
        prepared_jpeg=_jpeg_file(white_background, "prepared-photo.jpg", quality=94),
        face=face,
        notes=notes,
    )


def _load_processing_image(uploaded_file) -> Image.Image:
    image = Image.open(uploaded_file)
    image = ImageOps.exif_transpose(image).convert("RGB")
    if max(image.size) > MAX_PROCESSING_SIDE:
        image.thumbnail((MAX_PROCESSING_SIDE, MAX_PROCESSING_SIDE), Image.Resampling.LANCZOS)
    return image


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
    final = _add_output_border(final)
    preview = _add_watermark(final.copy())
    print_template = _make_4x6_print_template(final, background_color)

    return ProcessedPhoto(
        final_jpeg=_jpeg_file(final, "visa-photo-600.jpg"),
        preview_jpeg=_jpeg_file(preview, "visa-photo-preview.jpg", quality=88),
        print_template_jpeg=_jpeg_file(print_template, "visa-photo-4x6.jpg"),
        notes=render_notes,
    )


def _remove_background_to_color(image: Image.Image, notes: list[str], background_color: str) -> Image.Image:
    notes.append(f"Processor version {PROCESSOR_VERSION}.")
    if not settings.USE_LOCAL_BACKGROUND_REMOVAL:
        notes.append("Local background removal is disabled for production stability; original photo was kept.")
        return _paste_on_background(image, background_color)

    fast_background = _replace_uniform_edge_background(image, background_color, notes)
    if fast_background is not None:
        return fast_background

    if not settings.USE_REMBG_BACKGROUND_REMOVAL:
        try:
            return _remove_background_with_grabcut(image, notes, background_color)
        except Exception:
            notes.append("OpenCV background replacement failed; trying fast edge replacement fallback.")
            fast_background = _replace_uniform_edge_background(image, background_color, notes)
            if fast_background is not None:
                return fast_background
            return _paste_on_background(image, background_color)

    try:
        from rembg import remove
    except Exception:
        notes.append("rembg is not installed; used OpenCV person segmentation fallback.")
        try:
            return _remove_background_with_grabcut(image, notes, background_color)
        except Exception:
            notes.append("OpenCV background replacement failed safely; original photo was kept.")
            return _paste_on_background(image, background_color)

    try:
        result = remove(image)
        if not isinstance(result, Image.Image):
            result = Image.open(BytesIO(result))
    except Exception:
        notes.append("rembg failed; used OpenCV person segmentation fallback.")
        try:
            return _remove_background_with_grabcut(image, notes, background_color)
        except Exception:
            notes.append("OpenCV background replacement failed safely; original photo was kept.")
            return _paste_on_background(image, background_color)

    result = ImageOps.exif_transpose(result).convert("RGBA")
    canvas = Image.new("RGBA", result.size, background_color)
    canvas.alpha_composite(result)
    notes.append(f"Background removed with rembg and replaced with {background_color}.")
    return canvas.convert("RGB")


def _remove_background_with_grabcut(image: Image.Image, notes: list[str], background_color: str) -> Image.Image:
    try:
        import cv2
        import numpy as np
    except Exception:
        notes.append("OpenCV is not available; background replacement was skipped.")
        return _paste_on_background(image, background_color)

    rgb = image.convert("RGB")
    array = np.array(rgb)
    height, width = array.shape[:2]
    rect = _grabcut_subject_rect(array, cv2)

    mask = np.zeros((height, width), np.uint8)
    bg_model = np.zeros((1, 65), np.float64)
    fg_model = np.zeros((1, 65), np.float64)

    try:
        cv2.grabCut(array, mask, rect, bg_model, fg_model, 2, cv2.GC_INIT_WITH_RECT)
    except Exception:
        notes.append("OpenCV GrabCut failed; background replacement was skipped.")
        return _paste_on_background(image, background_color)

    subject_mask = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype("uint8")
    subject_mask = _refine_subject_mask(subject_mask, cv2, np)
    if not _has_usable_subject_mask(subject_mask, np):
        notes.append("OpenCV GrabCut produced an unusable subject mask; original photo was kept.")
        return _paste_on_background(image, background_color)

    from PIL import ImageFilter

    subject = Image.fromarray(array).convert("RGBA")
    alpha = Image.fromarray(subject_mask, mode="L").filter(ImageFilter.GaussianBlur(radius=0.7))
    subject.putalpha(alpha)

    canvas = Image.new("RGBA", rgb.size, background_color)
    canvas.alpha_composite(subject)
    notes.append(f"Background replaced with OpenCV GrabCut and set to {background_color}.")
    return canvas.convert("RGB")


def _replace_uniform_edge_background(image: Image.Image, background_color: str, notes: list[str]) -> Image.Image | None:
    image = image.convert("RGB")
    pixels = image.load()
    width, height = image.size
    edge_color = _estimate_edge_color(image)
    target = _hex_to_rgb(background_color)
    queue: deque[tuple[int, int]] = deque()
    seen: set[tuple[int, int]] = set()
    threshold = 25

    def try_enqueue(x: int, y: int):
        if (x, y) in seen:
            return
        if _rgb_distance(pixels[x, y], edge_color) > threshold:
            return
        seen.add((x, y))
        queue.append((x, y))

    for x in range(width):
        try_enqueue(x, 0)
        try_enqueue(x, height - 1)
    for y in range(height):
        try_enqueue(0, y)
        try_enqueue(width - 1, y)

    while queue:
        x, y = queue.popleft()
        if x > 0:
            try_enqueue(x - 1, y)
        if x < width - 1:
            try_enqueue(x + 1, y)
        if y > 0:
            try_enqueue(x, y - 1)
        if y < height - 1:
            try_enqueue(x, y + 1)

    if len(seen) < image.size[0] * image.size[1] * 0.12:
        return None

    for x, y in seen:
        pixels[x, y] = target
    notes.append(f"Fast edge-connected background replacement set {len(seen)} pixels to {background_color}.")
    return image


def _grabcut_subject_rect(array, cv2) -> tuple[int, int, int, int]:
    height, width = array.shape[:2]
    gray = cv2.cvtColor(array, cv2.COLOR_RGB2GRAY)
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.08, minNeighbors=5, minSize=(60, 60))

    if len(faces) > 0:
        x, y, w, h = max(faces, key=lambda rect: rect[2] * rect[3])
        left = max(1, int(x - w * 1.35))
        top = max(1, int(y - h * 1.45))
        right = min(width - 2, int(x + w * 2.35))
        bottom = min(height - 2, int(y + h * 4.40))
    else:
        left = int(width * 0.08)
        top = int(height * 0.02)
        right = int(width * 0.92)
        bottom = int(height * 0.98)

    rect_width = max(2, right - left)
    rect_height = max(2, bottom - top)
    return left, top, rect_width, rect_height


def _refine_subject_mask(mask, cv2, np):
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return mask

    largest = max(contours, key=cv2.contourArea)
    refined = np.zeros_like(mask)
    cv2.drawContours(refined, [largest], -1, 255, thickness=cv2.FILLED)
    refined = cv2.dilate(refined, kernel, iterations=1)
    return refined


def _has_usable_subject_mask(mask, np) -> bool:
    subject_ratio = float(np.count_nonzero(mask)) / float(mask.size)
    return 0.08 <= subject_ratio <= 0.88


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
        zoom_side = base_side * 0.74 * (TARGET_HEAD_RATIO / head_ratio)
        left = (width - zoom_side) / 2 - (offset_x / OUTPUT_SIZE) * zoom_side
        top = max(0, (height - zoom_side) * 0.30) - (offset_y / OUTPUT_SIZE) * zoom_side
        crop = _safe_square_crop(image, left, top, zoom_side, background_color)
        notes.append(f"Output resized to 600x600 JPEG at 300 DPI with fallback zoom target {head_ratio:.0%}.")
        return crop.resize((OUTPUT_SIZE, OUTPUT_SIZE), Image.Resampling.LANCZOS)

    min_side_for_face = face.head_height / 0.69
    max_side_for_face = face.head_height / 0.50
    crop_side = min(max(face.head_height / head_ratio, min_side_for_face), max_side_for_face)

    left = face.center_x - crop_side / 2 - (offset_x / OUTPUT_SIZE) * crop_side
    top = face.eye_y - TARGET_EYE_Y_RATIO * crop_side - (offset_y / OUTPUT_SIZE) * crop_side

    crop = _safe_square_crop(image, left, top, crop_side, background_color)
    final = crop.resize((OUTPUT_SIZE, OUTPUT_SIZE), Image.Resampling.LANCZOS)
    effective_eye_y = TARGET_EYE_Y_RATIO + (offset_y / OUTPUT_SIZE)
    notes.append(f"Cropped to 600x600 with head height targeted at {head_ratio:.0%}, eye-line near {effective_eye_y:.0%} from the top, and manual offset x={offset_x:.0f}px y={offset_y:.0f}px.")
    return final


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def _replace_edge_background_safely(image: Image.Image, background_color: str, notes: list[str]) -> Image.Image:
    image = image.convert("RGB")
    pixels = image.load()
    width, height = image.size
    target = _hex_to_rgb(background_color)
    edge_color = _estimate_edge_color(image)
    queue: deque[tuple[int, int]] = deque()
    seen: set[tuple[int, int]] = set()

    def try_enqueue(x: int, y: int):
        if (x, y) in seen or _is_subject_protected_zone(x, y, width, height):
            return
        if not _is_background_candidate(pixels[x, y], edge_color):
            return
        seen.add((x, y))
        queue.append((x, y))

    for x in range(width):
        try_enqueue(x, 0)
        try_enqueue(x, height - 1)
    for y in range(height):
        try_enqueue(0, y)
        try_enqueue(width - 1, y)

    while queue:
        x, y = queue.popleft()
        pixels[x, y] = target
        if x > 0:
            try_enqueue(x - 1, y)
        if x < width - 1:
            try_enqueue(x + 1, y)
        if y > 0:
            try_enqueue(x, y - 1)
        if y < height - 1:
            try_enqueue(x, y + 1)

    if seen:
        notes.append(f"Safely replaced {len(seen)} edge-connected background pixels with {background_color}.")
    else:
        notes.append("No safe edge-connected background area was detected; original background was kept.")
    return image


def _estimate_edge_color(image: Image.Image) -> tuple[int, int, int]:
    pixels = image.load()
    width, height = image.size
    step = max(1, min(width, height) // 24)
    samples = []

    for x in range(0, width, step):
        samples.append(pixels[x, 0])
        samples.append(pixels[x, height - 1])
    for y in range(0, height, step):
        samples.append(pixels[0, y])
        samples.append(pixels[width - 1, y])

    neutral_samples = [pixel for pixel in samples if _is_neutral_light_pixel(pixel)]
    if len(neutral_samples) >= 6:
        samples = neutral_samples

    return tuple(sorted(channel)[len(channel) // 2] for channel in zip(*samples))


def _is_background_candidate(pixel: tuple[int, int, int], edge_color: tuple[int, int, int]) -> bool:
    return _is_neutral_light_pixel(pixel) and _rgb_distance(pixel, edge_color) <= 72


def _is_neutral_light_pixel(pixel: tuple[int, int, int]) -> bool:
    r, g, b = pixel
    brightness = (r + g + b) / 3
    chroma = max(r, g, b) - min(r, g, b)
    return brightness >= 135 and chroma <= 70


def _rgb_distance(first: tuple[int, int, int], second: tuple[int, int, int]) -> float:
    return sum((a - b) ** 2 for a, b in zip(first, second)) ** 0.5


def _is_subject_protected_zone(x: int, y: int, width: int, height: int) -> bool:
    center_x = width / 2
    normalized_y = y / height

    head_center_y = height * 0.40
    head_radius_x = width * 0.34
    head_radius_y = height * 0.37
    in_head_zone = ((x - center_x) / head_radius_x) ** 2 + ((y - head_center_y) / head_radius_y) ** 2 <= 1.0
    if in_head_zone:
        return True

    if normalized_y >= 0.50:
        shoulder_half_width = min(width * 0.49, width * 0.20 + (normalized_y - 0.50) * width * 0.95)
        return abs(x - center_x) <= shoulder_half_width

    return False


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


def _add_output_border(image: Image.Image) -> Image.Image:
    image = image.convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, image.width - 1, image.height - 1), outline="#FFFFFF", width=1)
    return image


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
