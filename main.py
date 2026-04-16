
# 1. Library imports
import csv
import io
import json
import os
import shutil
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote
from xml.dom import minidom

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image
from pydantic import BaseModel

UPLOAD_FOLDER = 'sorted_files'
image_folder = 'source_files'
ANNOTATIONS_DIR = 'annotations'
EXPORTS_DIR = 'exports'
CONFIG_PATH = 'detect_config.json'

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp'}

os.makedirs(image_folder, exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(ANNOTATIONS_DIR, exist_ok=True)
os.makedirs(EXPORTS_DIR, exist_ok=True)

# 2. Create app and model objects
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/source_files", StaticFiles(directory=image_folder), name="source_files")
templates = Jinja2Templates(directory="templates/")


# ---------------------------------------------------------------------------
# Existing classification flow (unchanged behaviour)
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    img_list = _list_images(image_folder)
    pic_rem = len(img_list)
    try:
        next_img = img_list[0]
    except IndexError:
        next_img = 'no images found in the folder'
    return templates.TemplateResponse("welcome.html",
                                      {"request": request, "image": next_img, "pic_rem": pic_rem})


@app.get("/img/{item_id}")
def move(item_id: str, request: Request):
    val = request.query_params
    label = val["label"]
    pic_name = val["name"]

    target_dir = os.path.join(UPLOAD_FOLDER, label)
    os.makedirs(target_dir, exist_ok=True)
    upload_path = os.path.join(target_dir, pic_name)
    image_path = os.path.join(image_folder, pic_name)

    postive_cat = len(os.listdir(os.path.join(UPLOAD_FOLDER, '0'))) if os.path.isdir(
        os.path.join(UPLOAD_FOLDER, '0')) else 0
    negative_cat = len(os.listdir(os.path.join(UPLOAD_FOLDER, '1'))) if os.path.isdir(
        os.path.join(UPLOAD_FOLDER, '1')) else 0

    pic_rem = len(_list_images(image_folder))

    shutil.move(image_path, upload_path)

    img_list = _list_images(image_folder)
    next_img = img_list[0] if img_list else 'no images found in the folder'
    return templates.TemplateResponse("welcome.html",
                                      {"request": request, "image": next_img, "pic_rem": pic_rem,
                                       "pic4": postive_cat, "pic5": negative_cat})


# ---------------------------------------------------------------------------
# Object-detection labelling
# ---------------------------------------------------------------------------
class Box(BaseModel):
    label: str
    x: float  # top-left, absolute pixels in image coordinate space
    y: float
    width: float
    height: float
    score: Optional[float] = None


class AnnotationPayload(BaseModel):
    image: str
    boxes: List[Box]
    image_width: Optional[int] = None
    image_height: Optional[int] = None


class AutoAnnotateRequest(BaseModel):
    image: str
    endpoint: Optional[str] = None
    threshold: float = 0.5


class GCPExportRequest(BaseModel):
    bucket: str
    prefix: str = ""
    split: bool = True
    train_fraction: float = 0.8
    validation_fraction: float = 0.1


def _list_images(folder: str) -> List[str]:
    if not os.path.isdir(folder):
        return []
    return sorted(
        name for name in os.listdir(folder)
        if os.path.splitext(name)[1].lower() in IMAGE_EXTS
    )


def _annotation_path(image_name: str) -> str:
    base = os.path.splitext(image_name)[0]
    return os.path.join(ANNOTATIONS_DIR, f"{base}.json")


def _read_annotation(image_name: str) -> Dict[str, Any]:
    path = _annotation_path(image_name)
    if not os.path.exists(path):
        return {"image": image_name, "boxes": []}
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _image_dimensions(image_name: str) -> (int, int):
    path = os.path.join(image_folder, image_name)
    with Image.open(path) as img:
        return img.size  # (width, height)


@app.get("/detect", response_class=HTMLResponse)
async def detect_page(request: Request):
    images = _list_images(image_folder)
    annotated = sum(
        1 for name in images if os.path.exists(_annotation_path(name))
    )
    return templates.TemplateResponse(
        "detect.html",
        {
            "request": request,
            "images": images,
            "total": len(images),
            "annotated": annotated,
        },
    )


@app.get("/api/detect/images")
def api_list_images():
    images = _list_images(image_folder)
    return {
        "images": [
            {
                "name": name,
                "url": f"/source_files/{quote(name)}",
                "annotated": os.path.exists(_annotation_path(name)),
            }
            for name in images
        ]
    }


@app.get("/api/detect/annotation/{image_name}")
def api_get_annotation(image_name: str):
    if not os.path.exists(os.path.join(image_folder, image_name)):
        raise HTTPException(status_code=404, detail="image not found")
    data = _read_annotation(image_name)
    try:
        width, height = _image_dimensions(image_name)
        data.setdefault("image_width", width)
        data.setdefault("image_height", height)
    except Exception:
        pass
    return data


@app.post("/api/detect/annotation")
def api_save_annotation(payload: AnnotationPayload):
    if not os.path.exists(os.path.join(image_folder, payload.image)):
        raise HTTPException(status_code=404, detail="image not found")
    if payload.image_width is None or payload.image_height is None:
        try:
            payload.image_width, payload.image_height = _image_dimensions(payload.image)
        except Exception:
            pass
    data = {
        "image": payload.image,
        "boxes": [b.dict() for b in payload.boxes],
        "image_width": payload.image_width,
        "image_height": payload.image_height,
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }
    with open(_annotation_path(payload.image), "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    return {"ok": True, "saved": len(payload.boxes)}


@app.delete("/api/detect/annotation/{image_name}")
def api_delete_annotation(image_name: str):
    path = _annotation_path(image_name)
    if os.path.exists(path):
        os.remove(path)
    return {"ok": True}


@app.get("/api/detect/labels")
def api_list_labels():
    """Return the union of labels used across all saved annotations."""
    labels = set()
    if os.path.isdir(ANNOTATIONS_DIR):
        for fname in os.listdir(ANNOTATIONS_DIR):
            if not fname.endswith(".json"):
                continue
            try:
                with open(os.path.join(ANNOTATIONS_DIR, fname), "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                for box in data.get("boxes", []):
                    if box.get("label"):
                        labels.add(box["label"])
            except Exception:
                continue
    return {"labels": sorted(labels)}


# ---------------------------------------------------------------------------
# Auto-annotation via an external model endpoint
# ---------------------------------------------------------------------------
@app.post("/api/detect/auto")
def api_auto_annotate(payload: AutoAnnotateRequest):
    """
    Request boxes from a model. Two options are supported:

    1. A user-provided HTTP endpoint that accepts a multipart image upload and
       returns JSON like {"boxes": [{"label": ..., "x":..,"y":..,"width":..,
       "height":..,"score":..}, ...]} where coordinates are absolute pixels.
    2. A locally-installed torchvision Faster R-CNN model (used when no
       endpoint is provided and torchvision is importable).
    """
    image_path = os.path.join(image_folder, payload.image)
    if not os.path.exists(image_path):
        raise HTTPException(status_code=404, detail="image not found")

    endpoint = payload.endpoint or _load_config().get("auto_endpoint")

    if endpoint:
        try:
            boxes = _remote_detect(image_path, endpoint, payload.threshold)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502,
                                detail=f"remote model failed: {exc}")
    else:
        try:
            boxes = _local_detect(image_path, payload.threshold)
        except ModuleNotFoundError:
            raise HTTPException(
                status_code=503,
                detail=("No auto-detection model available. Install torchvision "
                        "or provide a model endpoint in detect_config.json."),
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500,
                                detail=f"local model failed: {exc}")

    return {"boxes": boxes}


def _remote_detect(image_path: str, endpoint: str, threshold: float) -> List[Dict[str, Any]]:
    import requests  # imported lazily to keep requests optional

    with open(image_path, "rb") as fh:
        files = {"file": (os.path.basename(image_path), fh, "application/octet-stream")}
        resp = requests.post(endpoint, files=files, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    raw_boxes = data.get("boxes", data if isinstance(data, list) else [])
    boxes = []
    for b in raw_boxes:
        score = b.get("score")
        if score is not None and score < threshold:
            continue
        # Accept either x/y/width/height or xmin/ymin/xmax/ymax shapes.
        if "xmin" in b:
            x = float(b["xmin"])
            y = float(b["ymin"])
            w = float(b["xmax"]) - x
            h = float(b["ymax"]) - y
        else:
            x = float(b["x"])
            y = float(b["y"])
            w = float(b["width"])
            h = float(b["height"])
        boxes.append({
            "label": str(b.get("label", "object")),
            "x": x, "y": y, "width": w, "height": h,
            "score": float(score) if score is not None else None,
        })
    return boxes


_LOCAL_MODEL = None
_LOCAL_LABELS = None


def _local_detect(image_path: str, threshold: float) -> List[Dict[str, Any]]:
    global _LOCAL_MODEL, _LOCAL_LABELS
    import torch  # type: ignore
    import torchvision  # type: ignore
    from torchvision.transforms import functional as TF  # type: ignore

    if _LOCAL_MODEL is None:
        weights = torchvision.models.detection.FasterRCNN_ResNet50_FPN_Weights.DEFAULT
        _LOCAL_MODEL = torchvision.models.detection.fasterrcnn_resnet50_fpn(weights=weights)
        _LOCAL_MODEL.eval()
        _LOCAL_LABELS = weights.meta["categories"]

    with Image.open(image_path).convert("RGB") as img:
        tensor = TF.to_tensor(img)
    with torch.no_grad():
        outputs = _LOCAL_MODEL([tensor])[0]

    boxes = []
    for box, score, label_id in zip(outputs["boxes"], outputs["scores"], outputs["labels"]):
        s = float(score)
        if s < threshold:
            continue
        x1, y1, x2, y2 = [float(v) for v in box.tolist()]
        boxes.append({
            "label": _LOCAL_LABELS[int(label_id)],
            "x": x1, "y": y1,
            "width": x2 - x1, "height": y2 - y1,
            "score": s,
        })
    return boxes


def _load_config() -> Dict[str, Any]:
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Dataset export
# ---------------------------------------------------------------------------
def _collect_annotations() -> List[Dict[str, Any]]:
    """Return a list of {image, path, width, height, boxes} for all annotated images."""
    results = []
    for name in _list_images(image_folder):
        ann_path = _annotation_path(name)
        if not os.path.exists(ann_path):
            continue
        with open(ann_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not data.get("boxes"):
            continue
        width = data.get("image_width")
        height = data.get("image_height")
        if not width or not height:
            try:
                width, height = _image_dimensions(name)
            except Exception:
                continue
        results.append({
            "image": name,
            "path": os.path.join(image_folder, name),
            "width": width,
            "height": height,
            "boxes": data["boxes"],
        })
    return results


def _label_index(annotations: List[Dict[str, Any]]) -> List[str]:
    labels = set()
    for item in annotations:
        for box in item["boxes"]:
            labels.add(box["label"])
    return sorted(labels)


@app.get("/api/detect/export/coco")
def export_coco():
    annotations = _collect_annotations()
    if not annotations:
        raise HTTPException(status_code=400, detail="no annotated images to export")

    labels = _label_index(annotations)
    category_index = {name: idx + 1 for idx, name in enumerate(labels)}

    coco = {
        "info": {
            "description": "img_move_label object detection dataset",
            "date_created": datetime.utcnow().isoformat() + "Z",
        },
        "licenses": [],
        "images": [],
        "annotations": [],
        "categories": [
            {"id": cid, "name": name, "supercategory": "none"}
            for name, cid in category_index.items()
        ],
    }

    ann_id = 1
    for img_id, item in enumerate(annotations, start=1):
        coco["images"].append({
            "id": img_id,
            "file_name": item["image"],
            "width": item["width"],
            "height": item["height"],
        })
        for box in item["boxes"]:
            x, y, w, h = float(box["x"]), float(box["y"]), float(box["width"]), float(box["height"])
            coco["annotations"].append({
                "id": ann_id,
                "image_id": img_id,
                "category_id": category_index[box["label"]],
                "bbox": [x, y, w, h],
                "area": w * h,
                "iscrowd": 0,
                "segmentation": [],
            })
            ann_id += 1

    body = json.dumps(coco, indent=2)
    headers = {"Content-Disposition": "attachment; filename=coco_annotations.json"}
    return Response(content=body, media_type="application/json", headers=headers)


@app.get("/api/detect/export/voc")
def export_voc():
    import zipfile

    annotations = _collect_annotations()
    if not annotations:
        raise HTTPException(status_code=400, detail="no annotated images to export")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in annotations:
            xml_bytes = _build_voc_xml(item)
            arcname = os.path.splitext(item["image"])[0] + ".xml"
            zf.writestr(f"Annotations/{arcname}", xml_bytes)
        # labelmap / summary
        zf.writestr("labels.txt", "\n".join(_label_index(annotations)) + "\n")

    buf.seek(0)
    headers = {"Content-Disposition": "attachment; filename=pascal_voc.zip"}
    return Response(content=buf.getvalue(), media_type="application/zip", headers=headers)


def _build_voc_xml(item: Dict[str, Any]) -> bytes:
    root = ET.Element("annotation")
    ET.SubElement(root, "folder").text = image_folder
    ET.SubElement(root, "filename").text = item["image"]
    ET.SubElement(root, "path").text = os.path.abspath(item["path"])

    source = ET.SubElement(root, "source")
    ET.SubElement(source, "database").text = "img_move_label"

    size = ET.SubElement(root, "size")
    ET.SubElement(size, "width").text = str(item["width"])
    ET.SubElement(size, "height").text = str(item["height"])
    ET.SubElement(size, "depth").text = "3"

    ET.SubElement(root, "segmented").text = "0"

    for box in item["boxes"]:
        obj = ET.SubElement(root, "object")
        ET.SubElement(obj, "name").text = box["label"]
        ET.SubElement(obj, "pose").text = "Unspecified"
        ET.SubElement(obj, "truncated").text = "0"
        ET.SubElement(obj, "difficult").text = "0"
        bnd = ET.SubElement(obj, "bndbox")
        x, y = float(box["x"]), float(box["y"])
        w, h = float(box["width"]), float(box["height"])
        ET.SubElement(bnd, "xmin").text = str(int(round(x)))
        ET.SubElement(bnd, "ymin").text = str(int(round(y)))
        ET.SubElement(bnd, "xmax").text = str(int(round(x + w)))
        ET.SubElement(bnd, "ymax").text = str(int(round(y + h)))

    rough = ET.tostring(root, "utf-8")
    return minidom.parseString(rough).toprettyxml(indent="  ").encode("utf-8")


@app.get("/api/detect/export/yolo")
def export_yolo():
    import zipfile

    annotations = _collect_annotations()
    if not annotations:
        raise HTTPException(status_code=400, detail="no annotated images to export")

    labels = _label_index(annotations)
    label_index = {name: idx for idx, name in enumerate(labels)}

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in annotations:
            lines = []
            w_img, h_img = item["width"], item["height"]
            for box in item["boxes"]:
                x = float(box["x"]); y = float(box["y"])
                w = float(box["width"]); h = float(box["height"])
                cx = (x + w / 2) / w_img
                cy = (y + h / 2) / h_img
                nw = w / w_img
                nh = h / h_img
                lines.append(
                    f"{label_index[box['label']]} {cx:.6f} {cy:.6f} {nw:.6f} {nh:.6f}"
                )
            arcname = os.path.splitext(item["image"])[0] + ".txt"
            zf.writestr(f"labels/{arcname}", "\n".join(lines) + "\n")
        zf.writestr("classes.txt", "\n".join(labels) + "\n")

    buf.seek(0)
    headers = {"Content-Disposition": "attachment; filename=yolo_labels.zip"}
    return Response(content=buf.getvalue(), media_type="application/zip", headers=headers)


# ---------------------------------------------------------------------------
# GCP Vertex AI dataset CSV
# ---------------------------------------------------------------------------
@app.post("/api/detect/export/gcp")
def export_gcp_vertex(payload: GCPExportRequest):
    """
    Build the CSV import file Vertex AI expects for object detection datasets.

    Each row is:
        SET,gs://bucket/prefix/image,label,x_min,y_min,,,x_max,y_max,,

    See: https://cloud.google.com/vertex-ai/docs/image-data/object-detection/prepare-data
    """
    annotations = _collect_annotations()
    if not annotations:
        raise HTTPException(status_code=400, detail="no annotated images to export")

    bucket = payload.bucket.strip()
    if not bucket:
        raise HTTPException(status_code=400, detail="bucket is required")
    bucket = bucket.replace("gs://", "").strip("/")
    prefix = payload.prefix.strip("/")

    import random
    random.seed(1337)
    rows = []
    sets_summary = {"TRAIN": 0, "VALIDATION": 0, "TEST": 0, "UNASSIGNED": 0}

    for item in annotations:
        if payload.split:
            r = random.random()
            if r < payload.train_fraction:
                ml_set = "TRAIN"
            elif r < payload.train_fraction + payload.validation_fraction:
                ml_set = "VALIDATION"
            else:
                ml_set = "TEST"
        else:
            ml_set = "UNASSIGNED"

        gcs_path = f"gs://{bucket}/{prefix}/{item['image']}" if prefix else f"gs://{bucket}/{item['image']}"
        w_img, h_img = item["width"], item["height"]

        for box in item["boxes"]:
            x = float(box["x"]); y = float(box["y"])
            w = float(box["width"]); h = float(box["height"])
            xmin = max(0.0, x / w_img)
            ymin = max(0.0, y / h_img)
            xmax = min(1.0, (x + w) / w_img)
            ymax = min(1.0, (y + h) / h_img)
            rows.append([
                ml_set,
                gcs_path,
                box["label"],
                f"{xmin:.6f}", f"{ymin:.6f}",
                "", "",
                f"{xmax:.6f}", f"{ymax:.6f}",
                "", "",
            ])
        sets_summary[ml_set] = sets_summary.get(ml_set, 0) + 1

    out = io.StringIO()
    writer = csv.writer(out)
    for row in rows:
        writer.writerow(row)

    filename = f"vertex_object_detection_{int(time.time())}.csv"
    # Also persist a copy under exports/ so the user has it on disk.
    os.makedirs(EXPORTS_DIR, exist_ok=True)
    saved_path = os.path.join(EXPORTS_DIR, filename)
    with open(saved_path, "w", encoding="utf-8", newline="") as fh:
        fh.write(out.getvalue())

    return {
        "csv": out.getvalue(),
        "filename": filename,
        "saved_to": saved_path,
        "rows": len(rows),
        "images": sets_summary,
        "instructions": (
            "Upload your image files to gs://{0}/{1} and upload this CSV to the same "
            "or a different bucket. In the Vertex AI console, create a new Image object "
            "detection dataset and point the import to the CSV's gs:// URI."
        ).format(bucket, prefix or "<your-prefix>"),
    }


@app.get("/api/detect/export/gcp/latest")
def download_latest_gcp_csv():
    if not os.path.isdir(EXPORTS_DIR):
        raise HTTPException(status_code=404, detail="no exports found")
    csvs = sorted(
        (f for f in os.listdir(EXPORTS_DIR) if f.endswith(".csv")),
        reverse=True,
    )
    if not csvs:
        raise HTTPException(status_code=404, detail="no exports found")
    return FileResponse(
        os.path.join(EXPORTS_DIR, csvs[0]),
        filename=csvs[0],
        media_type="text/csv",
    )
