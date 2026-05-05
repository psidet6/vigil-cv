from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from shared.config.config import FACE_BLUR_THRESH, FACE_MODEL_DET, FACE_MODEL_REC, OPENCV_NUM_THREADS, logger


if OPENCV_NUM_THREADS > 0:
    try:
        cv2.setNumThreads(OPENCV_NUM_THREADS)
        logger.info("Configured OpenCV CPU threads: %s", OPENCV_NUM_THREADS)
    except Exception as exc:
        logger.warning("failed to configure OpenCV CPU threads: %s", exc)


DET_GALLERY_SIZE = 640
DET_PROBE_SIZE = 1920
DET_PROBE_SIZE_HQ = 3840
DET_CONF_THRESH = 0.5
DET_PROBE_CONF = 0.4
DET_NMS_THRESH = 0.4
DET_MIN_FACE_PX = 40

REC_INPUT_SIZE = (112, 112)
BBOX_PAD_RATIO = 0.20

_MODELS_LOCK = threading.Lock()
_MODELS: tuple["FaceDetector", "FaceRecognizer"] | None = None


def _get_onnxruntime():
    try:
        import onnxruntime as ort  # type: ignore
    except ImportError as exc:
        raise RuntimeError("onnxruntime is not installed; face identity features are unavailable") from exc
    return ort


def _onnxruntime_available() -> bool:
    try:
        import onnxruntime  # noqa: F401
        return True
    except ImportError:
        return False


def _patch_onnx_dynamic_outputs(model_path: Path) -> str:
    patched_path = model_path.with_name(model_path.stem + "_dyn.onnx")
    if patched_path.exists():
        return str(patched_path)

    try:
        import onnx
    except ImportError:
        logger.warning("onnx is not installed; using original face model: %s", model_path)
        return str(model_path)

    model = onnx.load(str(model_path))
    patched = 0
    for output in model.graph.output:
        tensor_type = output.type.tensor_type
        if tensor_type.HasField("shape"):
            for dim in tensor_type.shape.dim:
                if dim.dim_value > 0:
                    dim.ClearField("dim_value")
                    dim.dim_param = "dyn"
                    patched += 1

    onnx.save(model, str(patched_path))
    logger.info("Patched %d face-model output dims to dynamic: %s", patched, patched_path)
    return str(patched_path)


class FaceDetector:
    def __init__(self, model_path: str | Path):
        model_path = Path(model_path)
        if not model_path.exists():
            raise FileNotFoundError(f"face detection model not found: {model_path}")
        load_path = _patch_onnx_dynamic_outputs(model_path)
        ort = _get_onnxruntime()
        self.session = ort.InferenceSession(load_path, providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name

    def preprocess(self, img: np.ndarray, max_size: int = DET_GALLERY_SIZE) -> tuple[np.ndarray, float]:
        h, w = img.shape[:2]
        scale = max_size / max(h, w)
        new_h, new_w = int(h * scale), int(w * scale)
        resized = cv2.resize(img, (new_w, new_h))
        pad_h = ((new_h + 31) // 32) * 32
        pad_w = ((new_w + 31) // 32) * 32
        canvas = np.zeros((pad_h, pad_w, 3), dtype=np.float32)
        canvas[:new_h, :new_w] = resized
        canvas = (canvas - 127.5) / 128.0
        tensor = canvas.transpose(2, 0, 1)[np.newaxis].astype(np.float32)
        return tensor, scale

    def detect(self, img: np.ndarray, max_size: int = DET_GALLERY_SIZE) -> list[dict]:
        tensor, scale = self.preprocess(img, max_size)
        outputs = self.session.run(None, {self.input_name: tensor})
        results = []
        strides = [8, 16, 32]
        num_levels = len(strides)
        has_kps = len(outputs) == num_levels * 3
        tensor_h, tensor_w = tensor.shape[2], tensor.shape[3]

        for i, stride in enumerate(strides):
            scores = outputs[i].flatten()
            bboxes = outputs[i + num_levels]
            kps = outputs[i + num_levels * 2] if has_kps else None

            fh = tensor_h // stride
            fw = tensor_w // stride
            anchor_centers = np.stack(np.mgrid[:fh, :fw][::-1], axis=-1).reshape(-1, 2).astype(np.float32)
            anchor_centers = np.repeat(anchor_centers * stride, 2, axis=0)

            mask = scores >= DET_CONF_THRESH
            if not mask.any():
                continue

            filtered_scores = scores[mask]
            filtered_anchors = anchor_centers[mask]
            filtered_bboxes = bboxes[mask]

            x1 = (filtered_anchors[:, 0] - filtered_bboxes[:, 0] * stride) / scale
            y1 = (filtered_anchors[:, 1] - filtered_bboxes[:, 1] * stride) / scale
            x2 = (filtered_anchors[:, 0] + filtered_bboxes[:, 2] * stride) / scale
            y2 = (filtered_anchors[:, 1] + filtered_bboxes[:, 3] * stride) / scale

            for j in range(len(filtered_scores)):
                det = {
                    "bbox": [float(x1[j]), float(y1[j]), float(x2[j]), float(y2[j])],
                    "score": float(filtered_scores[j]),
                    "kps": None,
                }
                if kps is not None:
                    pts = kps[mask][j].reshape(5, 2)
                    anchor = filtered_anchors[j]
                    det["kps"] = (anchor + pts * stride) / scale
                results.append(det)

        if not results:
            return []

        boxes = np.array([item["bbox"] for item in results], dtype=np.float32)
        scores = np.array([item["score"] for item in results], dtype=np.float32)
        keep = self._nms(boxes, scores, DET_NMS_THRESH)
        return [results[index] for index in keep]

    @staticmethod
    def _nms(boxes: np.ndarray, scores: np.ndarray, iou_thresh: float) -> list[int]:
        x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
        areas = (x2 - x1) * (y2 - y1)
        order = scores.argsort()[::-1]
        keep: list[int] = []
        while order.size > 0:
            i = order[0]
            keep.append(int(i))
            inter_x1 = np.maximum(x1[i], x1[order[1:]])
            inter_y1 = np.maximum(y1[i], y1[order[1:]])
            inter_x2 = np.minimum(x2[i], x2[order[1:]])
            inter_y2 = np.minimum(y2[i], y2[order[1:]])
            inter = np.maximum(0, inter_x2 - inter_x1) * np.maximum(0, inter_y2 - inter_y1)
            iou = inter / (areas[i] + areas[order[1:]] - inter)
            order = order[1:][iou <= iou_thresh]
        return keep


class FaceRecognizer:
    ARCFACE_REF = np.array(
        [
            [38.2946, 51.6963],
            [73.5318, 51.5014],
            [56.0252, 71.7366],
            [41.5493, 92.3655],
            [70.7299, 92.2041],
        ],
        dtype=np.float32,
    )

    def __init__(self, model_path: str | Path):
        model_path = Path(model_path)
        if not model_path.exists():
            raise FileNotFoundError(f"face recognition model not found: {model_path}")
        load_path = _patch_onnx_dynamic_outputs(model_path)
        ort = _get_onnxruntime()
        self.session = ort.InferenceSession(load_path, providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name

    def align_and_crop(self, img: np.ndarray, kps: np.ndarray) -> np.ndarray:
        matrix, _ = cv2.estimateAffinePartial2D(kps, self.ARCFACE_REF, method=cv2.LMEDS)
        return cv2.warpAffine(img, matrix, REC_INPUT_SIZE, borderValue=0)

    def get_embedding(self, face_img: np.ndarray) -> np.ndarray:
        blob = (face_img.astype(np.float32) - 127.5) / 128.0
        blob = blob.transpose(2, 0, 1)[np.newaxis]
        output = self.session.run(None, {self.input_name: blob})[0][0]
        norm = np.linalg.norm(output)
        return output / norm if norm > 0 else output


def face_models_ready() -> bool:
    return _onnxruntime_available() and os.path.isfile(FACE_MODEL_DET) and os.path.isfile(FACE_MODEL_REC)


def get_face_models() -> tuple[FaceDetector, FaceRecognizer]:
    global _MODELS
    with _MODELS_LOCK:
        if _MODELS is None:
            _MODELS = (FaceDetector(FACE_MODEL_DET), FaceRecognizer(FACE_MODEL_REC))
        return _MODELS


def load_image(path: str) -> Optional[np.ndarray]:
    if not path or not os.path.exists(path):
        return None

    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        try:
            raw = Path(path).read_bytes()
            arr = np.frombuffer(raw, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
        except Exception:
            return None

    if img is None:
        return None
    if len(img.shape) == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    elif len(img.shape) == 3 and img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    if img.dtype == np.uint16:
        img = (img / 256).astype(np.uint8)
    return img


def enhance_image(img: np.ndarray) -> np.ndarray:
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    lab[:, :, 0] = clahe.apply(lab[:, :, 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def blur_score(face_img: np.ndarray) -> float:
    gray = cv2.cvtColor(face_img, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def crop_face_bbox(img: np.ndarray, bbox: list[float], pad_ratio: float = BBOX_PAD_RATIO) -> np.ndarray:
    h, w = img.shape[:2]
    x1, y1, x2, y2 = [float(value) for value in bbox]
    bw, bh = x2 - x1, y2 - y1
    x1 = max(0, int(x1 - bw * pad_ratio))
    y1 = max(0, int(y1 - bh * pad_ratio))
    x2 = min(w, int(x2 + bw * pad_ratio))
    y2 = min(h, int(y2 + bh * pad_ratio))
    return cv2.resize(img[y1:y2, x1:x2], REC_INPUT_SIZE)


def extract_probe_embeddings(
    img: np.ndarray,
    detector: FaceDetector,
    recognizer: FaceRecognizer,
    use_enhance: bool = True,
    max_size: int = DET_PROBE_SIZE,
    conf_thresh: float = DET_PROBE_CONF,
    min_face_px: int = DET_MIN_FACE_PX,
) -> list[tuple[np.ndarray, dict]]:
    working = enhance_image(img) if use_enhance else img
    h, w = working.shape[:2]
    effective_max = DET_PROBE_SIZE_HQ if max_size == DET_PROBE_SIZE and max(h, w) > 2000 else max_size
    detections = detector.detect(working, effective_max)
    if not detections:
        return []

    valid_dets = []
    for det in detections:
        x1, y1, x2, y2 = det["bbox"]
        face_w = x2 - x1
        face_h = y2 - y1
        if det["score"] < conf_thresh:
            continue
        if face_w < min_face_px or face_h < min_face_px:
            continue
        valid_dets.append(det)

    if not valid_dets:
        return []

    results = []
    total_faces = len(valid_dets)
    for idx, det in enumerate(valid_dets):
        x1, y1, x2, y2 = det["bbox"]
        info = {
            "face_idx": idx,
            "face_count": total_faces,
            "bbox": det["bbox"],
            "face_size": (round(x2 - x1), round(y2 - y1)),
            "det_score": round(det["score"], 4),
            "used_align": det["kps"] is not None,
            "error": None,
        }
        face_crop = recognizer.align_and_crop(working, det["kps"]) if det["kps"] is not None else crop_face_bbox(working, det["bbox"])
        bscore = blur_score(face_crop)
        info["blur_score"] = round(bscore, 2)
        info["quality"] = "low_quality" if bscore < FACE_BLUR_THRESH else "ok"
        emb = recognizer.get_embedding(face_crop)
        results.append((emb, info))
    return results


def extract_best_face_embedding(
    img: np.ndarray,
    detector: FaceDetector,
    recognizer: FaceRecognizer,
    use_enhance: bool = True,
) -> tuple[Optional[np.ndarray], dict]:
    faces = extract_probe_embeddings(img, detector, recognizer, use_enhance=use_enhance, max_size=DET_GALLERY_SIZE, conf_thresh=DET_CONF_THRESH)
    if not faces:
        return None, {"error": "no face detected", "face_count": 0}

    def area(item: tuple[np.ndarray, dict]) -> float:
        bbox = item[1]["bbox"]
        return (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])

    best = max(faces, key=area)
    return best[0], best[1]
