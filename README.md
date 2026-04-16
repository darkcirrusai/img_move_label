# Image Labelling / Sorting App

A lightweight FastAPI app that helps you build image datasets two ways:

1. **Classification** – move images into labelled folders (the original flow).
2. **Object Detection** – draw bounding boxes on images, optionally pre-filled
   by an external model, then export to COCO / Pascal VOC / YOLO or to a Vertex
   AI object-detection CSV.

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

## Object Detection

Open <http://127.0.0.1:8000/detect>.

* **Draw** boxes by clicking and dragging on the image.
* **Select** a box by clicking it. Delete it with <kbd>Delete</kbd> / the ✕
  button, or double-click to rename.
* **Change the active label** with the `Label:` field — new boxes inherit it.
* **Navigate** between images with <kbd>←</kbd>/<kbd>→</kbd> or the
  Prev/Next buttons. Save with <kbd>Ctrl/⌘</kbd>+<kbd>S</kbd> or the 💾 button.

### Auto-annotation

The `✨ Auto-annotate` button asks a model for boxes, which are merged with any
you have already drawn so you can edit them before saving.

Two backends are supported:

1. **Remote model endpoint.** Enter the URL in the right-hand panel (or put it
   in `detect_config.json` as `{ "auto_endpoint": "https://…/predict" }`). The
   server will POST the image as a `multipart/form-data` `file` field and
   expects JSON like:

   ```json
   {"boxes": [
     {"label": "cat", "x": 10, "y": 12, "width": 80, "height": 120, "score": 0.91}
   ]}
   ```

   `xmin/ymin/xmax/ymax` coordinates are also accepted.

2. **Local torchvision Faster R-CNN.** If no endpoint is configured and
   `torchvision` is installed, the bundled COCO-pretrained Faster R-CNN is
   used. Install with `pip install torch torchvision` (kept optional because
   it’s large).

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
annotations/        # per-image JSON: {image, boxes: [{label,x,y,width,height,score?}]}
exports/            # generated export files (Vertex CSVs, etc.)
detect_config.json  # optional: {"auto_endpoint": "..."} for auto-annotation
```

## Future Developments
* Make new folders if one does not exist for a category.
* Update list dynamically.
* Fix empty folder issue.
* Add pictures in explanation.
* Direct upload of images / CSV to GCS from the UI.
