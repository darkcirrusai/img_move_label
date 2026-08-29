"""Client for the dg-models-orchestrator service.

All model inference from this app goes through the orchestrator instead of
hitting the TFServing containers directly. The orchestrator is a thin proxy:
it returns *raw* TFServing predictions and leaves result processing to the
client (this module).

Response envelopes (checked here — errors are reported in-band with HTTP 200):

- ``POST /cutter-detect``  -> ``{"status", "model_v1", "model_v2", "error"}``
  ``model_v1``/``model_v2`` hold the raw TFServing response of each of the two
  detection models. If one model fails its dict is empty and the reason is in
  ``error`` while ``status`` stays ``"success"``; if both fail ``status`` is
  ``"error"``.
- ``POST /blade-crop``, ``POST /cutter-wear``, ``POST /cutter-class``
  -> ``{"status", "predictions", "error"}`` where ``predictions`` is the raw
  TFServing predictions array.

Detection predictions use the AutoML/TF Object Detection export format:
``detection_boxes`` (normalized ``[ymin, xmin, ymax, xmax]``) plus either
``detection_multiclass_scores`` (per-class scores, index 0 = background) or
``detection_scores`` + ``detection_classes``/``detection_classes_as_text``.

Classification predictions carry parallel ``labels``/``scores`` arrays (with
fallbacks for other common export key names).
"""

import base64
import json
import os
from typing import Any, Dict, List, Optional, Tuple

import requests

DEFAULT_ORCHESTRATOR_URL = "http://localhost:8010"
REQUEST_TIMEOUT = 60
CONFIG_PATH = "detect_config.json"

# Class-index mapping for the cutter_detect models. Index 0 is background.
# This matches utils/process_multi_cutters.process_cutter_data (1=nozzle,
# 2=lost, 3=cutter, 4=ring_out).
CUTTER_CLASS_LABELS = {1: "nozzle", 2: "lost", 3: "cutter", 4: "ring_out"}

# Classification modules exposed by the app -> orchestrator endpoint.
# "wear_type" is served by the orchestrator's /cutter-class route (the
# wear_class TFServing model behind it classifies the wear type of a cutter).
CLASSIFY_MODULES = {
    "cutter_wear": "/cutter-wear",
    "wear_type": "/cutter-class",
}

# Detection modules exposed by the app -> orchestrator endpoint.
DETECT_MODULES = {
    "cutter_detect": "/cutter-detect",
    "blade_crop": "/blade-crop",
}


class OrchestratorError(RuntimeError):
    """Raised when the orchestrator is unreachable or reports an error."""


def _file_config() -> Dict[str, Any]:
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def orchestrator_url() -> str:
    cfg = _file_config()
    return (
        os.getenv("ORCHESTRATOR_URL")
        or cfg.get("orchestrator_url")
        or DEFAULT_ORCHESTRATOR_URL
    ).rstrip("/")


def _api_key() -> Optional[str]:
    return os.getenv("ORCHESTRATOR_API_KEY") or _file_config().get("orchestrator_api_key")


def _post(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = orchestrator_url() + path
    headers = {"Content-Type": "application/json"}
    key = _api_key()
    if key:
        headers["X-API-Key"] = key
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        raise OrchestratorError(f"orchestrator unreachable at {url}: {exc}") from exc
    if resp.status_code == 401:
        raise OrchestratorError("orchestrator rejected the API key (set ORCHESTRATOR_API_KEY)")
    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        raise OrchestratorError(f"orchestrator returned HTTP {resp.status_code}: {exc}") from exc
    try:
        return resp.json()
    except ValueError as exc:
        raise OrchestratorError("orchestrator returned a non-JSON response") from exc


def encode_image(image_path: str) -> str:
    with open(image_path, "rb") as fh:
        return base64.b64encode(fh.read()).decode("utf-8")


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------
def detect(
    module: str,
    image_path: str,
    image_key: str,
    img_w: int,
    img_h: int,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Run a detection module and return (detections, warning).

    Detections are dicts with pixel-space ``x``/``y``/``width``/``height``
    plus ``label`` and ``score``, unfiltered by confidence — the caller
    decides which are annotations and which are candidates.
    """
    if module not in DETECT_MODULES:
        raise OrchestratorError(f"unknown detection module: {module}")

    payload = {"image": encode_image(image_path), "key": image_key}
    data = _post(DETECT_MODULES[module], payload)

    status = data.get("status")
    if status != "success":
        raise OrchestratorError(data.get("error") or f"orchestrator status: {status}")

    if module == "cutter_detect":
        # Dual-model envelope; "error" may note a partial (one-model) failure.
        warning = data.get("error")
        predictions = []
        for model_key in ("model_v1", "model_v2"):
            raw = data.get(model_key) or {}
            predictions.extend(raw.get("predictions") or [])
        detections = []
        for pred in predictions:
            detections.extend(_parse_detection_prediction(pred, CUTTER_CLASS_LABELS))
        detections = _dedupe(detections)
    else:  # blade_crop
        warning = data.get("error")
        detections = []
        for pred in data.get("predictions") or []:
            detections.extend(_parse_detection_prediction(pred, default_label="blade"))
        detections = _dedupe(detections)

    return [_to_pixel_box(d, img_w, img_h) for d in detections], warning


def _parse_detection_prediction(
    pred: Dict[str, Any],
    class_labels: Optional[Dict[int, str]] = None,
    default_label: str = "object",
) -> List[Dict[str, Any]]:
    """Parse one raw TFServing detection prediction into labelled boxes."""
    boxes = pred.get("detection_boxes") or []
    multiclass = pred.get("detection_multiclass_scores")
    detections: List[Dict[str, Any]] = []

    if multiclass:
        for bbox, scores in zip(boxes, multiclass):
            # index 0 is background; take the best real class
            best_idx, best_score = -1, 0.0
            for idx in range(1, len(scores)):
                if float(scores[idx]) > best_score:
                    best_idx, best_score = idx, float(scores[idx])
            if best_idx == -1:
                continue
            if class_labels:
                label = class_labels.get(best_idx, f"class_{best_idx}")
            else:
                label = default_label
            detections.append({"box": [float(v) for v in bbox],
                               "label": label, "score": best_score})
        return detections

    scores = pred.get("detection_scores") or []
    classes_text = pred.get("detection_classes_as_text") or []
    classes = pred.get("detection_classes") or []
    for i, bbox in enumerate(boxes):
        score = float(scores[i]) if i < len(scores) else 0.0
        if i < len(classes_text) and classes_text[i]:
            label = str(classes_text[i])
        elif i < len(classes):
            idx = int(float(classes[i]))
            label = (class_labels or {}).get(idx, default_label)
        else:
            label = default_label
        detections.append({"box": [float(v) for v in bbox],
                           "label": label, "score": score})
    return detections


def _iou(a: List[float], b: List[float]) -> float:
    y_a, x_a = max(a[0], b[0]), max(a[1], b[1])
    y_b, x_b = min(a[2], b[2]), min(a[3], b[3])
    inter = max(y_b - y_a, 0.0) * max(x_b - x_a, 0.0)
    if inter <= 0:
        return 0.0
    area_a = abs((a[2] - a[0]) * (a[3] - a[1]))
    area_b = abs((b[2] - b[0]) * (b[3] - b[1]))
    return inter / float(area_a + area_b - inter)


def _dedupe(detections: List[Dict[str, Any]], iou_thresh: float = 0.5) -> List[Dict[str, Any]]:
    """Drop overlapping same-label detections, keeping the higher score."""
    kept: List[Dict[str, Any]] = []
    for det in sorted(detections, key=lambda d: d["score"], reverse=True):
        duplicate = any(
            k["label"] == det["label"] and _iou(k["box"], det["box"]) > iou_thresh
            for k in kept
        )
        if not duplicate:
            kept.append(det)
    return kept


def _to_pixel_box(det: Dict[str, Any], img_w: int, img_h: int) -> Dict[str, Any]:
    ymin, xmin, ymax, xmax = det["box"]
    return {
        "label": det["label"],
        "x": xmin * img_w,
        "y": ymin * img_h,
        "width": (xmax - xmin) * img_w,
        "height": (ymax - ymin) * img_h,
        "score": det["score"],
    }


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------
def classify(module: str, image_path: str, image_key: str) -> Dict[str, Any]:
    """Run a classification module and return {label, confidence, all_scores}."""
    if module not in CLASSIFY_MODULES:
        raise OrchestratorError(f"unknown classification module: {module}")

    payload = {"image": encode_image(image_path), "key": image_key}
    data = _post(CLASSIFY_MODULES[module], payload)

    if data.get("status") != "success":
        raise OrchestratorError(data.get("error") or f"orchestrator status: {data.get('status')}")

    predictions = data.get("predictions") or []
    if not predictions:
        raise OrchestratorError("orchestrator returned no predictions")
    return _parse_classification_prediction(predictions[0])


def _parse_classification_prediction(pred: Dict[str, Any]) -> Dict[str, Any]:
    labels = pred.get("labels") or pred.get("classes") or pred.get("display_names")
    scores = pred.get("scores") or pred.get("probabilities") or pred.get("confidences")

    if scores is None:
        raise OrchestratorError(
            f"unrecognized classification prediction format (keys: {sorted(pred.keys())})")

    scores = [float(s) for s in scores]
    if labels is None:
        labels = [f"class_{i}" for i in range(len(scores))]
    labels = [str(l) for l in labels]

    all_scores = dict(zip(labels, scores))
    if not all_scores:
        raise OrchestratorError("classification prediction contained no scores")
    best_label = max(all_scores, key=all_scores.get)
    return {
        "label": best_label,
        "confidence": all_scores[best_label],
        "all_scores": all_scores,
    }
