# Image Labelling / Sorting App

A lightweight FastAPI app that helps you build image datasets three ways:

1. **Classification** – move images into labelled folders (the original flow).
2. **Model-assisted classification** – the `cutter_wear` and `wear_type`
   models suggest a label per image; the label you click decides which folder
   the image is sorted into.
3. **Object Detection** – draw bounding boxes on images, optionally pre-filled
   by the `cutter_detect` or `blade_crop` models, then export to COCO /
   Pascal VOC / YOLO or to a Vertex AI object-detection CSV.

All model inference goes through the
[dg-models-orchestrator](https://github.com/darkcirrusai/dg-models-orchestrator)
— this app never talks to the TFServing containers directly. Configure it with
the `ORCHESTRATOR_URL` and `ORCHESTRATOR_API_KEY` environment variables (or
`orchestrator_url` / `orchestrator_api_key` in `detect_config.json`). The
orchestrator returns raw TFServing predictions; parsing lives in
`orchestrator_client.py`.

## Environment
Python 3.8+, FastAPI 0.86.0

Install dependencies:

```bash
pip install -r requirements.txt
```

Run:

```bash
python app.py
# → http://127.0.0.1:8000
```

Place images into `source_files/`. Annotations are stored as JSON under
`annotations/` and generated exports land in `exports/`.

## Classification (existing flow)

Open <http://127.0.0.1:8000/>, enter a category in the right-hand form, and the
image is moved into `sorted_files/<category>/`.

## Model-assisted classification

Open <http://127.0.0.1:8000/classify> and pick a module:

| Module | Orchestrator endpoint | What it classifies |
|--------|----------------------|--------------------|
| `cutter_wear` | `/cutter-wear` | Wear level of a cutter |
| `wear_type` | `/cutter-class` | Wear/cutter type |

Each image is sent to the orchestrator (automatically, or via **✨ Predict**)
and the per-class scores are shown as clickable buttons. Clicking a label —
the suggested one, another class, or a custom label — moves the image into
`sorted_files/<module>/<label>/` and advances to the next image. The model
only suggests; nothing is saved until you click.

## Object Detection

Open <http://127.0.0.1:8000/detect>.

* **Draw** boxes by clicking and dragging on the image.
* **Select** a box by clicking it. Delete it with <kbd>Delete</kbd> / the ✕
  button, or double-click to rename.
* **Change the active label** with the `Label:` field — new boxes inherit it.
* **Navigate** between images with <kbd>←</kbd>/<kbd>→</kbd> or the
  Prev/Next buttons. Save with <kbd>Ctrl/⌘</kbd>+<kbd>S</kbd> or the 💾 button.

### Auto-annotation

The `✨ Auto-annotate` button asks the orchestrator for boxes. Pick the model
in the toolbar:

* **Cutter detection** (`/cutter-detect`) — combines both detection models,
  labels boxes `cutter` / `lost` / `nozzle` / `ring_out`, and drops duplicate
  detections (same label, IOU > 0.5, higher score wins). If one of the two
  models fails, the other's detections are still used and a warning is shown.
* **Blade crop** (`/blade-crop`) — returns `blade` boxes.

Detections are split by confidence:

* **Boxes** (score ≥ *Threshold*, default 50%) are added to the annotation
  set. **Click a model detection to reject it** — it turns grey with a cross
  and is dropped on save; click it again (or use ↩ in the box list) to
  restore it.
* **Candidates** (*Cand. ≥* ≤ score < *Threshold*, default 20–50%) are drawn
  as dashed amber boxes. **Click a candidate to accept it** into the
  annotation set; unaccepted candidates are simply ignored — they are stored
  alongside the annotation so they survive navigation, but never appear in
  any export.

Hand-drawn boxes work exactly as before: click-and-drag to draw, click to
select, <kbd>Delete</kbd> to remove, double-click to rename.

Unsaved changes are **auto-saved when you navigate** to another image
(sidebar click, Prev/Next, arrow keys) — you can always come back and fix an
image later.

### Image orientation

EXIF orientation is respected end to end: the app reports the *displayed*
dimensions, and images carrying a non-default orientation tag are transposed
before being sent for inference, so detection boxes line up with what the
browser shows.

### Crop & rotate

The toolbar's **⟲ 90° / ⟳ 90°** buttons rotate the image; **✂ Crop** lets
you drag a region and apply it (<kbd>Esc</kbd> cancels). Edits are saved as a
copy in the same folder (`<base>_edited.jpg`; editing an already-edited image
overwrites it in place), with EXIF orientation baked in. Saved boxes and
candidates are remapped onto the edited image (boxes falling outside a crop
are dropped). The original file stays on disk, but is excluded from the image
lists unless it has saved boxes of its own.

### Exports

In the right-hand panel:

* **COCO JSON** – downloads a single `coco_annotations.json` with the usual
  `images`/`annotations`/`categories` blocks.
* **Pascal VOC (zip)** – one XML per image inside `Annotations/`, plus
  `labels.txt`.
* **YOLO txt (zip)** – normalized `cx cy w h` one-txt-per-image, plus
  `classes.txt`.

### Vertex AI dataset CSV

Enter your GCS bucket name (and optional prefix) and click **Generate Vertex
CSV**. The app emits a CSV matching the [Vertex AI object-detection import
format](https://cloud.google.com/vertex-ai/docs/image-data/object-detection/prepare-data):

```
TRAIN,gs://bucket/prefix/img_001.jpg,cat,0.10,0.12,,,0.82,0.76,,
```

The CSV is downloaded in the browser and persisted to `exports/` on disk.
Upload your images to `gs://<bucket>/<prefix>/` and upload the CSV to the same
or a different bucket, then point a Vertex AI Image Object Detection dataset
at its `gs://` URI.

## File layout

```
source_files/       # drop images here
sorted_files/       # classifier moves images here by label
                    #   (model-assisted flow uses sorted_files/<module>/<label>/)
annotations/        # per-image JSON: {image, boxes: [...], candidates: [...]}
exports/            # generated export files (Vertex CSVs, etc.)
detect_config.json  # optional: {"orchestrator_url": "...", "orchestrator_api_key": "..."}
```

## Future Developments
* Make new folders if one does not exist for a category.
* Update list dynamically.
* Fix empty folder issue.
* Add pictures in explanation.
* Direct upload of images / CSV to GCS from the UI.
