// Object detection labeling UI.
//
// State model
//   state.images     : [{name, url, annotated}]
//   state.current    : image object we're labeling
//   state.boxes      : [{label, x, y, width, height, score?, rejected?}]
//                      in image pixel space. A box with a score is a model
//                      detection: clicking it toggles rejected (rejected
//                      boxes are not saved). Boxes without a score are
//                      hand-drawn: clicking selects them.
//   state.candidates : [{label, x, y, width, height, score}] low-confidence
//                      model detections (candidate band, default 20-50%).
//                      Clicking one accepts it into state.boxes; unaccepted
//                      candidates are ignored by every export.
//   state.selected   : index of selected box or -1
//   state.imgW/H     : natural dimensions of the current image
//
// The canvas is drawn on top of the image; we maintain an image -> canvas
// scale factor so that boxes are stored in image pixel coordinates (which is
// what all the export formats want).

const el = (id) => document.getElementById(id);

const state = {
    images: [],
    current: null,
    boxes: [],
    candidates: [],
    selected: -1,
    imgW: 0,
    imgH: 0,
    scale: 1,
    labelColors: new Map(),
    dirty: false,
};

const PALETTE = [
    "#ef4444", "#f97316", "#eab308", "#22c55e", "#06b6d4",
    "#3b82f6", "#8b5cf6", "#ec4899", "#14b8a6", "#f59e0b",
];

function colorFor(label) {
    if (!state.labelColors.has(label)) {
        const idx = state.labelColors.size % PALETTE.length;
        state.labelColors.set(label, PALETTE[idx]);
    }
    return state.labelColors.get(label);
}

// ---------------------------------------------------------------------------
// Toast
// ---------------------------------------------------------------------------
let toastTimer = null;
function toast(msg, isError = false) {
    const t = el("toast");
    t.textContent = msg;
    t.classList.toggle("error", !!isError);
    t.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove("show"), 2200);
}

// ---------------------------------------------------------------------------
// Image list / navigation
// ---------------------------------------------------------------------------
async function loadImages() {
    const res = await fetch("/api/detect/images");
    const data = await res.json();
    state.images = data.images;
    renderImageList();
    if (state.images.length && !state.current) {
        selectImage(state.images[0]);
    }
}

function renderImageList() {
    const filter = el("image-filter").value.trim().toLowerCase();
    const annotatedFilter = el("annotated-filter") ? el("annotated-filter").value : "all";
    const list = el("image-list");
    list.innerHTML = "";
    state.images
        .filter((img) => !filter || img.name.toLowerCase().includes(filter))
        .filter((img) => {
            if (annotatedFilter === "labelled") return img.annotated;
            if (annotatedFilter === "unlabelled") return !img.annotated;
            return true;
        })
        .forEach((img) => {
            const li = document.createElement("li");
            li.textContent = img.name;
            if (img.annotated) {
                const b = document.createElement("span");
                b.className = "badge";
                b.textContent = "✓";
                li.appendChild(b);
            }
            if (state.current && state.current.name === img.name) {
                li.classList.add("active");
            }
            li.addEventListener("click", async () => {
                await autoSaveIfDirty();
                selectImage(img);
            });
            list.appendChild(li);
        });
    updateProgress();
}

function updateProgress() {
    const annotated = state.images.filter((i) => i.annotated).length;
    el("progress").textContent = `${annotated} / ${state.images.length} annotated`;
}

async function selectImage(img) {
    state.current = img;
    state.boxes = [];
    state.candidates = [];
    state.selected = -1;
    state.dirty = false;
    if (cropMode) setCropMode(false);
    el("current-image").textContent = img.name;

    // Load annotation
    const res = await fetch(`/api/detect/annotation/${encodeURIComponent(img.name)}`);
    const data = await res.json();
    state.boxes = (data.boxes || []).map((b) => ({ ...b }));
    state.candidates = (data.candidates || []).map((b) => ({ ...b }));
    state.imgW = data.image_width || 0;
    state.imgH = data.image_height || 0;

    await loadImageElement(img.url);
    renderImageList();
    await refreshLabelSuggestions();
    drawBoxes();
    renderBoxList();
}

function loadImageElement(url) {
    return new Promise((resolve, reject) => {
        const im = el("source-image");
        im.onload = () => {
            state.imgW = im.naturalWidth;
            state.imgH = im.naturalHeight;
            sizeCanvas();
            resolve();
        };
        im.onerror = reject;
        im.src = url;
    });
}

function sizeCanvas() {
    const canvas = el("draw-canvas");
    const im = el("source-image");
    const rect = im.getBoundingClientRect();
    canvas.width = rect.width;
    canvas.height = rect.height;
    canvas.style.width = rect.width + "px";
    canvas.style.height = rect.height + "px";
    // Position the canvas exactly over the image within canvas-host.
    const host = el("canvas-host").getBoundingClientRect();
    canvas.style.left = (rect.left - host.left) + "px";
    canvas.style.top = (rect.top - host.top) + "px";
    state.scale = rect.width / state.imgW;
}

window.addEventListener("resize", () => {
    if (state.current) {
        sizeCanvas();
        drawBoxes();
    }
});

// ---------------------------------------------------------------------------
// Drawing / canvas interaction
// ---------------------------------------------------------------------------
const canvas = () => el("draw-canvas");
function ctx() { return canvas().getContext("2d"); }

function toCanvas(x) { return x * state.scale; }
function toImage(x) { return x / state.scale; }

function drawBoxes() {
    const c = canvas();
    const g = ctx();
    g.clearRect(0, 0, c.width, c.height);

    // Candidates first, dashed, so accepted boxes draw on top of them.
    state.candidates.forEach((box) => {
        const x = toCanvas(box.x), y = toCanvas(box.y);
        const w = toCanvas(box.width), h = toCanvas(box.height);
        g.lineWidth = 2;
        g.setLineDash([6, 4]);
        g.strokeStyle = "#f59e0b";
        g.fillStyle = "#f59e0b18";
        g.fillRect(x, y, w, h);
        g.strokeRect(x, y, w, h);
        g.setLineDash([]);

        const label = `? ${box.label} ${(box.score * 100).toFixed(0)}%`;
        g.font = "12px sans-serif";
        const metrics = g.measureText(label);
        g.fillStyle = "#f59e0b";
        g.fillRect(x, y - 16, metrics.width + 8, 16);
        g.fillStyle = "#fff";
        g.fillText(label, x + 4, y - 4);
    });

    state.boxes.forEach((box, idx) => {
        const selected = idx === state.selected;
        const rejected = !!box.rejected;
        const color = rejected ? "#9ca3af" : colorFor(box.label);
        g.lineWidth = selected ? 3 : 2;
        g.strokeStyle = color;
        g.fillStyle = rejected ? "#9ca3af10" : color + "22";
        const x = toCanvas(box.x), y = toCanvas(box.y);
        const w = toCanvas(box.width), h = toCanvas(box.height);
        if (rejected) g.setLineDash([3, 3]);
        g.fillRect(x, y, w, h);
        g.strokeRect(x, y, w, h);
        g.setLineDash([]);

        const label = (rejected ? "✕ " : "") + box.label +
            (box.score != null ? ` ${(box.score * 100).toFixed(0)}%` : "");
        g.font = "12px sans-serif";
        const metrics = g.measureText(label);
        const labelH = 16;
        g.fillStyle = color;
        g.fillRect(x, y - labelH, metrics.width + 8, labelH);
        g.fillStyle = "#fff";
        g.fillText(label, x + 4, y - 4);
        if (rejected) {
            g.strokeStyle = color;
            g.lineWidth = 1.5;
            g.beginPath();
            g.moveTo(x, y); g.lineTo(x + w, y + h);
            g.moveTo(x + w, y); g.lineTo(x, y + h);
            g.stroke();
        }
    });

    // Crop overlay: dim everything outside the selected region.
    if (cropMode && state.cropRect) {
        const x = toCanvas(state.cropRect.x), y = toCanvas(state.cropRect.y);
        const w = toCanvas(state.cropRect.width), h = toCanvas(state.cropRect.height);
        g.fillStyle = "rgba(15, 23, 42, 0.55)";
        g.fillRect(0, 0, c.width, y);
        g.fillRect(0, y + h, c.width, c.height - y - h);
        g.fillRect(0, y, x, h);
        g.fillRect(x + w, y, c.width - x - w, h);
        g.strokeStyle = "#fff";
        g.setLineDash([6, 4]);
        g.lineWidth = 2;
        g.strokeRect(x, y, w, h);
        g.setLineDash([]);
    }

    updateColorSwatch();
}

function updateColorSwatch() {
    el("color-swatch").style.background = colorFor(el("active-label").value || "object");
}

// Drawing state
let dragging = false;
let dragStart = null;
let dragBox = null;  // the in-progress box in image coordinates

// Crop state (crop mode repurposes the drag gesture to pick a region)
let cropMode = false;
let cropDragging = false;
let cropStart = null;

function canvasPoint(evt) {
    const rect = canvas().getBoundingClientRect();
    return {
        x: evt.clientX - rect.left,
        y: evt.clientY - rect.top,
    };
}

function hitTest(pt) {
    for (let i = state.boxes.length - 1; i >= 0; i--) {
        const b = state.boxes[i];
        const x = toCanvas(b.x), y = toCanvas(b.y);
        const w = toCanvas(b.width), h = toCanvas(b.height);
        if (pt.x >= x && pt.x <= x + w && pt.y >= y && pt.y <= y + h) return i;
    }
    return -1;
}

function hitTestCandidates(pt) {
    for (let i = state.candidates.length - 1; i >= 0; i--) {
        const b = state.candidates[i];
        const x = toCanvas(b.x), y = toCanvas(b.y);
        const w = toCanvas(b.width), h = toCanvas(b.height);
        if (pt.x >= x && pt.x <= x + w && pt.y >= y && pt.y <= y + h) return i;
    }
    return -1;
}

function acceptCandidate(idx) {
    const cand = state.candidates.splice(idx, 1)[0];
    state.boxes.push({ ...cand });
    state.selected = state.boxes.length - 1;
    state.dirty = true;
    drawBoxes();
    renderBoxList();
    toast(`Accepted candidate "${cand.label}"`);
}

function toggleReject(idx) {
    const box = state.boxes[idx];
    box.rejected = !box.rejected;
    state.selected = box.rejected ? -1 : idx;
    state.dirty = true;
    drawBoxes();
    renderBoxList();
}

canvas().addEventListener("mousedown", (e) => {
    const pt = canvasPoint(e);
    if (cropMode) {
        cropDragging = true;
        cropStart = pt;
        state.cropRect = null;
        drawBoxes();
        return;
    }
    const hit = hitTest(pt);
    if (hit !== -1) {
        const box = state.boxes[hit];
        if (box.score != null) {
            // Model detection: a click rejects it (clicking again restores).
            toggleReject(hit);
        } else {
            state.selected = hit;
            drawBoxes();
            renderBoxList();
        }
        return;
    }
    const candHit = hitTestCandidates(pt);
    if (candHit !== -1) {
        acceptCandidate(candHit);
        return;
    }
    dragging = true;
    dragStart = pt;
    dragBox = { x: toImage(pt.x), y: toImage(pt.y), width: 0, height: 0 };
    state.selected = -1;
});

canvas().addEventListener("mousemove", (e) => {
    if (cropDragging) {
        const pt = canvasPoint(e);
        const x1 = Math.min(cropStart.x, pt.x), y1 = Math.min(cropStart.y, pt.y);
        const x2 = Math.max(cropStart.x, pt.x), y2 = Math.max(cropStart.y, pt.y);
        state.cropRect = {
            x: toImage(x1),
            y: toImage(y1),
            width: toImage(x2 - x1),
            height: toImage(y2 - y1),
        };
        drawBoxes();
        return;
    }
    if (!dragging) return;
    const pt = canvasPoint(e);
    const x1 = Math.min(dragStart.x, pt.x);
    const y1 = Math.min(dragStart.y, pt.y);
    const x2 = Math.max(dragStart.x, pt.x);
    const y2 = Math.max(dragStart.y, pt.y);
    dragBox = {
        x: toImage(x1),
        y: toImage(y1),
        width: toImage(x2 - x1),
        height: toImage(y2 - y1),
    };
    drawBoxes();
    // Draw the in-progress box on top
    const g = ctx();
    g.strokeStyle = "#fff";
    g.setLineDash([4, 4]);
    g.lineWidth = 2;
    g.strokeRect(x1, y1, x2 - x1, y2 - y1);
    g.setLineDash([]);
});

window.addEventListener("mouseup", (e) => {
    if (cropDragging) {
        cropDragging = false;
        if (!state.cropRect || state.cropRect.width < 8 || state.cropRect.height < 8) {
            state.cropRect = null;
        }
        updateCropButtons();
        drawBoxes();
        return;
    }
    if (!dragging) return;
    dragging = false;
    if (dragBox && dragBox.width > 3 && dragBox.height > 3) {
        const label = el("active-label").value.trim() || "object";
        state.boxes.push({ ...dragBox, label });
        state.selected = state.boxes.length - 1;
        state.dirty = true;
    }
    dragBox = null;
    drawBoxes();
    renderBoxList();
});

canvas().addEventListener("dblclick", (e) => {
    if (cropMode) return;
    const pt = canvasPoint(e);
    const hit = hitTest(pt);
    if (hit === -1) return;
    const next = prompt("Rename label", state.boxes[hit].label);
    if (next !== null && next.trim()) {
        state.boxes[hit].label = next.trim();
        state.dirty = true;
        drawBoxes();
        renderBoxList();
    }
});

window.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
    if (e.key === "Escape" && cropMode) {
        setCropMode(false);
        return;
    }
    if ((e.key === "Delete" || e.key === "Backspace") && state.selected !== -1) {
        state.boxes.splice(state.selected, 1);
        state.selected = -1;
        state.dirty = true;
        drawBoxes();
        renderBoxList();
        e.preventDefault();
    } else if (e.key === "ArrowRight") {
        nextImage(1);
    } else if (e.key === "ArrowLeft") {
        nextImage(-1);
    } else if (e.key === "s" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        saveAnnotation();
    }
});

// ---------------------------------------------------------------------------
// Boxes list
// ---------------------------------------------------------------------------
function renderBoxList() {
    const list = el("box-list");
    list.innerHTML = "";
    const active = state.boxes.filter((b) => !b.rejected).length;
    el("box-count").textContent = `(${active})`;
    state.boxes.forEach((box, idx) => {
        const li = document.createElement("li");
        if (idx === state.selected) li.classList.add("selected");
        if (box.rejected) li.classList.add("rejected");

        const swatch = document.createElement("span");
        swatch.className = "swatch";
        swatch.style.background = box.rejected ? "#9ca3af" : colorFor(box.label);
        li.appendChild(swatch);

        const input = document.createElement("input");
        input.type = "text";
        input.value = box.label;
        input.disabled = !!box.rejected;
        input.addEventListener("change", () => {
            box.label = input.value.trim() || "object";
            state.dirty = true;
            drawBoxes();
        });
        li.appendChild(input);

        if (box.score != null) {
            const score = document.createElement("span");
            score.textContent = `${(box.score * 100).toFixed(0)}%`;
            score.style.fontSize = "11px";
            score.style.color = "#6b7280";
            li.appendChild(score);
        }

        if (box.score != null) {
            const rejectBtn = document.createElement("button");
            rejectBtn.className = "remove";
            rejectBtn.textContent = box.rejected ? "↩" : "⊘";
            rejectBtn.title = box.rejected ? "Restore detection" : "Reject detection (not saved)";
            rejectBtn.addEventListener("click", () => toggleReject(idx));
            li.appendChild(rejectBtn);
        }

        const remove = document.createElement("button");
        remove.className = "remove";
        remove.textContent = "✕";
        remove.title = "Delete box";
        remove.addEventListener("click", () => {
            state.boxes.splice(idx, 1);
            state.selected = -1;
            state.dirty = true;
            drawBoxes();
            renderBoxList();
        });
        li.appendChild(remove);

        li.addEventListener("click", (e) => {
            if (e.target.tagName === "BUTTON" || e.target === input) return;
            state.selected = idx;
            drawBoxes();
            renderBoxList();
        });

        list.appendChild(li);
    });

    renderCandidateList();
}

function renderCandidateList() {
    const list = el("candidate-list");
    list.innerHTML = "";
    el("candidate-count").textContent = `(${state.candidates.length})`;
    state.candidates.forEach((cand, idx) => {
        const li = document.createElement("li");
        li.classList.add("candidate");

        const swatch = document.createElement("span");
        swatch.className = "swatch";
        swatch.style.background = "#f59e0b";
        li.appendChild(swatch);

        const name = document.createElement("span");
        name.textContent = cand.label;
        name.style.flex = "1";
        li.appendChild(name);

        const score = document.createElement("span");
        score.textContent = `${(cand.score * 100).toFixed(0)}%`;
        score.style.fontSize = "11px";
        score.style.color = "#92400e";
        li.appendChild(score);

        const accept = document.createElement("button");
        accept.className = "accept";
        accept.textContent = "✓";
        accept.title = "Accept into annotation set";
        accept.addEventListener("click", () => acceptCandidate(idx));
        li.appendChild(accept);

        const dismiss = document.createElement("button");
        dismiss.className = "remove";
        dismiss.textContent = "✕";
        dismiss.title = "Dismiss candidate";
        dismiss.addEventListener("click", () => {
            state.candidates.splice(idx, 1);
            state.dirty = true;
            drawBoxes();
            renderBoxList();
        });
        li.appendChild(dismiss);

        li.addEventListener("click", (e) => {
            if (e.target.tagName === "BUTTON") return;
            acceptCandidate(idx);
        });

        list.appendChild(li);
    });
}

// ---------------------------------------------------------------------------
// Label suggestions
// ---------------------------------------------------------------------------
async function refreshLabelSuggestions() {
    try {
        const res = await fetch("/api/detect/labels");
        const data = await res.json();
        const dl = el("label-suggestions");
        dl.innerHTML = "";
        data.labels.forEach((l) => {
            const opt = document.createElement("option");
            opt.value = l;
            dl.appendChild(opt);
        });
    } catch (_) { /* ignore */ }
}

el("active-label").addEventListener("input", updateColorSwatch);

// ---------------------------------------------------------------------------
// Save / clear / navigation
// ---------------------------------------------------------------------------
async function saveAnnotation(silent = false) {
    if (!state.current) return;
    // Rejected detections are dropped; unaccepted candidates are stored
    // separately so they persist but never reach an export.
    const payload = {
        image: state.current.name,
        boxes: state.boxes
            .filter((b) => !b.rejected)
            .map(({ rejected, ...b }) => b),
        candidates: state.candidates,
        image_width: state.imgW,
        image_height: state.imgH,
    };
    const res = await fetch("/api/detect/annotation", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });
    if (!res.ok) {
        toast("Save failed", true);
        return;
    }
    const data = await res.json();
    state.dirty = false;
    state.current.annotated = true;
    if (!silent) toast(`Saved ${data.saved} boxes`);
    renderImageList();
    refreshLabelSuggestions();
}

async function autoSaveIfDirty() {
    if (state.dirty && state.current) await saveAnnotation(true);
}

function clearAll() {
    if (!state.boxes.length && !state.candidates.length) return;
    state.boxes = [];
    state.candidates = [];
    state.selected = -1;
    state.dirty = true;
    drawBoxes();
    renderBoxList();
}

async function nextImage(delta) {
    if (!state.current) return;
    const name = state.current.name;
    await autoSaveIfDirty();
    const idx = state.images.findIndex((i) => i.name === name);
    const nextIdx = (idx + delta + state.images.length) % state.images.length;
    selectImage(state.images[nextIdx]);
}

el("save-btn").addEventListener("click", saveAnnotation);
el("clear-btn").addEventListener("click", clearAll);
el("prev-btn").addEventListener("click", () => nextImage(-1));
el("next-btn").addEventListener("click", () => nextImage(1));
el("image-filter").addEventListener("input", renderImageList);
el("annotated-filter").addEventListener("change", renderImageList);

// ---------------------------------------------------------------------------
// Auto-annotation
// ---------------------------------------------------------------------------
el("auto-annotate-btn").addEventListener("click", async () => {
    if (!state.current) return;
    const btn = el("auto-annotate-btn");
    const prev = btn.textContent;
    btn.textContent = "Working…";
    btn.disabled = true;
    try {
        const res = await fetch("/api/detect/auto", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                image: state.current.name,
                module: el("auto-module").value,
                threshold: parseFloat(el("auto-threshold").value) || 0.5,
                candidate_threshold: parseFloat(el("candidate-threshold").value) || 0.2,
            }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            toast(err.detail || "Auto-annotate failed", true);
            return;
        }
        const data = await res.json();
        // Merge suggested boxes with existing ones so the user can edit;
        // candidates from this run replace the previous candidate set.
        data.boxes.forEach((b) => state.boxes.push(b));
        state.candidates = data.candidates || [];
        state.dirty = true;
        drawBoxes();
        renderBoxList();
        const msg = `Added ${data.boxes.length} boxes, ${state.candidates.length} candidates`;
        toast(data.warning ? `${msg} — ${data.warning}` : msg, !!data.warning);
    } catch (exc) {
        toast("Auto-annotate failed: " + exc, true);
    } finally {
        btn.textContent = prev;
        btn.disabled = false;
    }
});

// ---------------------------------------------------------------------------
// Image editing (crop / rotate)
//
// Edits are applied server-side and saved as an edited copy in the same
// folder; the original stays on disk but leaves the image list unless it has
// saved boxes. Saved boxes/candidates are remapped onto the edited image.
// ---------------------------------------------------------------------------
function setCropMode(on) {
    cropMode = on;
    cropDragging = false;
    state.cropRect = null;
    el("crop-btn").classList.toggle("primary", on);
    updateCropButtons();
    drawBoxes();
}

function updateCropButtons() {
    el("crop-apply-btn").hidden = !(cropMode && state.cropRect);
    el("crop-cancel-btn").hidden = !cropMode;
}

async function applyEdit(edit) {
    if (!state.current) return;
    await autoSaveIfDirty();
    const res = await fetch("/api/detect/edit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ image: state.current.name, ...edit }),
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        toast(err.detail || "Edit failed", true);
        return;
    }
    const data = await res.json();
    setCropMode(false);
    await loadImages();
    const img = state.images.find((i) => i.name === data.image);
    if (img) await selectImage(img);
    toast(`Saved edited image ${data.image}`);
}

el("rotate-cw-btn").addEventListener("click", () => applyEdit({ rotate: 90 }));
el("rotate-ccw-btn").addEventListener("click", () => applyEdit({ rotate: -90 }));
el("crop-btn").addEventListener("click", () => setCropMode(!cropMode));
el("crop-cancel-btn").addEventListener("click", () => setCropMode(false));
el("crop-apply-btn").addEventListener("click", () => {
    if (!state.cropRect) return;
    applyEdit({ crop: state.cropRect });
});

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------
document.querySelectorAll("[data-export]").forEach((btn) => {
    btn.addEventListener("click", () => {
        const fmt = btn.getAttribute("data-export");
        window.location.href = `/api/detect/export/${fmt}`;
    });
});

el("gcp-export-btn").addEventListener("click", async () => {
    const bucket = el("gcp-bucket").value.trim();
    if (!bucket) {
        toast("Bucket name is required", true);
        return;
    }
    const body = {
        bucket,
        prefix: el("gcp-prefix").value.trim(),
        split: el("gcp-split").checked,
        train_fraction: parseFloat(el("gcp-train").value) || 0.8,
        validation_fraction: parseFloat(el("gcp-val").value) || 0.1,
    };
    const res = await fetch("/api/detect/export/gcp", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        toast(err.detail || "Export failed", true);
        return;
    }
    const data = await res.json();
    const result = el("gcp-result");
    result.textContent = [
        `Wrote ${data.rows} rows to ${data.saved_to}`,
        `Sets: ${JSON.stringify(data.images)}`,
        "",
        data.instructions,
        "",
        data.csv.split("\n").slice(0, 5).join("\n") +
            (data.csv.split("\n").length > 5 ? "\n…" : ""),
    ].join("\n");

    // Trigger a download of the generated CSV file.
    const blob = new Blob([data.csv], { type: "text/csv" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = data.filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
});

// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------
loadImages().then(refreshLabelSuggestions);
updateColorSwatch();
