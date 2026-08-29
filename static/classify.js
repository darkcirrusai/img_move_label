// Model-assisted classification UI.
//
// A module (cutter_wear / wear_type) is a classification model served by the
// dg-models-orchestrator. The model suggests a label with per-class scores;
// clicking a label moves the image into sorted_files/<module>/<label>/ and
// advances to the next image. The prediction is only a suggestion — nothing
// is saved until the user clicks.

const el = (id) => document.getElementById(id);

const state = {
    images: [],       // [{name, url}]
    counts: {},       // {label: n} for the active module
    current: null,
    prediction: null, // {label, confidence, all_scores}
    predictSeq: 0,    // guards against out-of-order prediction responses
};

let toastTimer = null;
function toast(msg, isError = false) {
    const t = el("toast");
    t.textContent = msg;
    t.classList.toggle("error", !!isError);
    t.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove("show"), 2600);
}

function activeModule() {
    return el("module-select").value;
}

// ---------------------------------------------------------------------------
// State loading / image list
// ---------------------------------------------------------------------------
async function loadState(keepCurrent = false) {
    const res = await fetch(`/api/classify/state?module=${encodeURIComponent(activeModule())}`);
    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        toast(err.detail || "Failed to load state", true);
        return;
    }
    const data = await res.json();
    state.images = data.images;
    state.counts = data.counts;
    renderCounts();
    renderImageList();
    el("progress").textContent = `${data.remaining} remaining`;

    const stillThere = keepCurrent && state.current &&
        state.images.some((i) => i.name === state.current.name);
    if (!stillThere) {
        selectImage(state.images.length ? state.images[0] : null);
    }
}

function renderImageList() {
    const filter = el("image-filter").value.trim().toLowerCase();
    const list = el("image-list");
    list.innerHTML = "";
    state.images
        .filter((img) => !filter || img.name.toLowerCase().includes(filter))
        .forEach((img) => {
            const li = document.createElement("li");
            li.textContent = img.name;
            if (state.current && state.current.name === img.name) {
                li.classList.add("active");
            }
            li.addEventListener("click", () => selectImage(img));
            list.appendChild(li);
        });
}

function renderCounts() {
    const table = el("counts-table");
    table.innerHTML = "";
    const labels = Object.keys(state.counts).sort();
    if (!labels.length) {
        table.innerHTML = "<tr><td class='hint-text'>Nothing sorted yet.</td></tr>";
        return;
    }
    labels.forEach((label) => {
        const tr = document.createElement("tr");
        const name = document.createElement("td");
        name.textContent = label;
        const count = document.createElement("td");
        count.textContent = state.counts[label];
        tr.appendChild(name);
        tr.appendChild(count);
        table.appendChild(tr);
    });
}

function selectImage(img) {
    state.current = img;
    state.prediction = null;
    state.predictSeq++;
    el("current-image").textContent = img ? img.name : "—";
    el("source-image").src = img ? img.url : "";
    renderImageList();
    renderPrediction();
    if (img && el("auto-predict").checked) predict();
}

function nextImage(delta) {
    if (!state.current || !state.images.length) return;
    const idx = state.images.findIndex((i) => i.name === state.current.name);
    const nextIdx = (idx + delta + state.images.length) % state.images.length;
    selectImage(state.images[nextIdx]);
}

// ---------------------------------------------------------------------------
// Prediction
// ---------------------------------------------------------------------------
async function predict() {
    if (!state.current) return;
    const seq = ++state.predictSeq;
    const btn = el("predict-btn");
    btn.disabled = true;
    el("prediction-title").textContent = "Prediction — asking model…";
    try {
        const res = await fetch("/api/classify/predict", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ image: state.current.name, module: activeModule() }),
        });
        if (seq !== state.predictSeq) return; // user moved on
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            toast(err.detail || "Prediction failed", true);
            el("prediction-title").textContent = "Prediction — failed";
            return;
        }
        state.prediction = await res.json();
        if (seq !== state.predictSeq) return;
        renderPrediction();
    } catch (exc) {
        if (seq === state.predictSeq) {
            toast("Prediction failed: " + exc, true);
            el("prediction-title").textContent = "Prediction — failed";
        }
    } finally {
        btn.disabled = false;
    }
}

function renderPrediction() {
    const rows = el("score-rows");
    rows.innerHTML = "";
    if (!state.prediction) {
        el("prediction-title").textContent = "Prediction";
        return;
    }
    const p = state.prediction;
    el("prediction-title").textContent =
        `Prediction: ${p.label} (${(p.confidence * 100).toFixed(1)}%)`;

    Object.entries(p.all_scores)
        .sort((a, b) => b[1] - a[1])
        .forEach(([label, score]) => {
            const row = document.createElement("div");
            row.className = "score-row";

            const btn = document.createElement("button");
            btn.className = "label-btn" + (label === p.label ? " top" : "");
            btn.textContent = label;
            btn.title = `Move image to sorted_files/${activeModule()}/${label}/`;
            btn.addEventListener("click", () => assign(label));
            row.appendChild(btn);

            const track = document.createElement("div");
            track.className = "score-bar-track";
            const bar = document.createElement("div");
            bar.className = "score-bar";
            bar.style.width = `${Math.max(1, score * 100)}%`;
            track.appendChild(bar);
            row.appendChild(track);

            const val = document.createElement("span");
            val.className = "score-val";
            val.textContent = `${(score * 100).toFixed(1)}%`;
            row.appendChild(val);

            rows.appendChild(row);
        });
}

// ---------------------------------------------------------------------------
// Assignment
// ---------------------------------------------------------------------------
async function assign(label) {
    if (!state.current) return;
    const res = await fetch("/api/classify/assign", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            image: state.current.name,
            module: activeModule(),
            label,
        }),
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        toast(err.detail || "Assign failed", true);
        return;
    }
    const data = await res.json();
    toast(`Moved to ${data.module}/${data.label}`);
    state.current = null;
    await loadState();
}

// ---------------------------------------------------------------------------
// Events
// ---------------------------------------------------------------------------
el("predict-btn").addEventListener("click", predict);
el("prev-btn").addEventListener("click", () => nextImage(-1));
el("next-btn").addEventListener("click", () => nextImage(1));
el("image-filter").addEventListener("input", renderImageList);
el("module-select").addEventListener("change", () => loadState(true).then(() => {
    state.prediction = null;
    renderPrediction();
    if (state.current && el("auto-predict").checked) predict();
}));
el("custom-assign-btn").addEventListener("click", () => {
    const label = el("custom-label").value.trim();
    if (!label) { toast("Enter a label first", true); return; }
    assign(label);
});
el("custom-label").addEventListener("keydown", (e) => {
    if (e.key === "Enter") el("custom-assign-btn").click();
});

window.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
    if (e.key === "ArrowRight") nextImage(1);
    else if (e.key === "ArrowLeft") nextImage(-1);
});

el("upload-input").addEventListener("change", async function () {
    const form = new FormData();
    for (const file of this.files) form.append("files", file);
    const status = el("upload-status");
    status.textContent = "Uploading…";
    try {
        const res = await fetch("/upload", { method: "POST", body: form });
        const data = await res.json();
        if (res.ok) {
            status.textContent = `✓ Uploaded ${data.uploaded.length} file(s).`;
            await loadState(true);
        } else {
            status.textContent = `Error: ${data.detail}`;
        }
    } catch (e) { status.textContent = "Upload failed."; }
});

// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------
loadState();
