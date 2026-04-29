// Stockpilot training annotator — vanilla JS, single-file, ~400 lines.
// Renders an image with current annotations + AI suggestions on a canvas.
// User can draw, edit, label, delete boxes; saves back to the server.
(function () {
  "use strict";

  const root = document.getElementById("annotator");
  if (!root) return;

  const canvas = document.getElementById("ann-canvas");
  const ctx = canvas.getContext("2d");
  const loadingOverlay = document.getElementById("ann-loading");
  const statusEl = document.getElementById("ann-status");
  const classInput = document.getElementById("ann-class-input");
  const saveButton = document.getElementById("ann-save");
  const clearButton = document.getElementById("ann-clear");

  const imageURL = root.dataset.imageUrl;
  const annotationsURL = root.dataset.annotationsUrl;
  const suggestionsURL = root.dataset.suggestionsUrl;
  const csrf = root.dataset.csrf;
  let suggestionsStatus = root.dataset.suggestionsStatus;

  const PALETTE = [
    "#34d399", "#fbbf24", "#f87171", "#60a5fa", "#a78bfa",
    "#22d3ee", "#fb7185", "#facc15", "#4ade80", "#c084fc",
  ];

  // Box state: { label, x, y, w, h, source: "user"|"yolo"|"sam" }
  // Coords are NORMALIZED [0,1] relative to the image. Display layer scales.
  /** @type {{label:string|null,x:number,y:number,w:number,h:number,source:string,confidence?:number}[]} */
  let annotations = [];
  /** @type {typeof annotations} */
  let suggestions = [];
  let selectedIdx = -1; // index into `annotations`
  let dirty = false;

  let img = new Image();
  let imgLoaded = false;

  // Drag state
  let dragMode = null; // null | "draw" | "move" | "resize-nw" | "resize-ne" | "resize-sw" | "resize-se"
  let dragStart = null; // {x, y} normalized
  let dragOriginalBox = null;

  // ----- Initialization ------------------------------------------------------

  loadInitialState();

  function loadInitialState() {
    fetch(annotationsURL, { headers: { Accept: "application/json" } })
      .then((r) => r.json())
      .then((data) => {
        annotations = data.annotations.map((a) => ({ ...a, source: "user" }));
        return loadImage();
      })
      .then(() => {
        loadingOverlay.style.display = "none";
        draw();
        pollSuggestions();
      });
  }

  function loadImage() {
    return new Promise((resolve, reject) => {
      img.onload = () => {
        imgLoaded = true;
        sizeCanvas();
        resolve();
      };
      img.onerror = reject;
      img.src = imageURL;
    });
  }

  function sizeCanvas() {
    if (!imgLoaded) return;
    const containerWidth = root.clientWidth;
    const ratio = img.naturalHeight / img.naturalWidth;
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    canvas.style.width = containerWidth + "px";
    canvas.style.height = containerWidth * ratio + "px";
  }

  window.addEventListener("resize", () => {
    sizeCanvas();
    draw();
  });

  // ----- Suggestion polling --------------------------------------------------

  function pollSuggestions() {
    fetch(suggestionsURL, { headers: { Accept: "application/json" } })
      .then((r) => r.json())
      .then((data) => {
        suggestionsStatus = data.status;
        suggestions = (data.suggestions || []).map((s) => ({
          x: s.x_center - s.width / 2,
          y: s.y_center - s.height / 2,
          w: s.width,
          h: s.height,
          label: s.label,
          confidence: s.confidence,
          source: s.source,
        }));
        if (data.status === "running" || data.status === "pending") {
          setStatus("AI suggestions: running…");
          setTimeout(pollSuggestions, 4000);
        } else if (data.status === "failed") {
          setStatus("AI suggestions failed (annotate manually)", "rose");
        } else {
          setStatus(suggestions.length + " AI suggestion(s) ready");
        }
        draw();
      })
      .catch(() => setTimeout(pollSuggestions, 8000));
  }

  // ----- Drawing -------------------------------------------------------------

  function draw() {
    if (!imgLoaded) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

    // Suggestions first (drawn underneath)
    suggestions.forEach((s) => {
      const isYolo = s.source === "yolo";
      ctx.save();
      ctx.setLineDash([8, 4]);
      ctx.lineWidth = 2;
      ctx.strokeStyle = isYolo ? "#60a5fa" : "#94a3b8";
      ctx.fillStyle = isYolo ? "rgba(96,165,250,0.12)" : "rgba(148,163,184,0.10)";
      const [px, py, pw, ph] = pxBox(s);
      ctx.fillRect(px, py, pw, ph);
      ctx.strokeRect(px, py, pw, ph);
      const label = s.label || "(unlabeled)";
      drawLabel(px, py, label, isYolo ? "#60a5fa" : "#94a3b8");
      ctx.restore();
    });

    // Annotations on top
    annotations.forEach((a, i) => {
      const color = colorForLabel(a.label);
      ctx.save();
      ctx.lineWidth = i === selectedIdx ? 4 : 3;
      ctx.strokeStyle = color;
      ctx.fillStyle = hexToRgba(color, 0.18);
      const [px, py, pw, ph] = pxBox(a);
      ctx.fillRect(px, py, pw, ph);
      ctx.strokeRect(px, py, pw, ph);
      drawLabel(px, py, a.label || "?", color);

      if (i === selectedIdx) {
        // Resize handles
        const handle = (hx, hy) => {
          ctx.fillStyle = color;
          ctx.fillRect(hx - 6, hy - 6, 12, 12);
        };
        handle(px, py);
        handle(px + pw, py);
        handle(px, py + ph);
        handle(px + pw, py + ph);
      }
      ctx.restore();
    });
  }

  function drawLabel(px, py, text, color) {
    ctx.save();
    ctx.font = "16px ui-sans-serif, system-ui, sans-serif";
    const m = ctx.measureText(text);
    const padX = 6, padY = 4;
    const tw = m.width + 2 * padX;
    const th = 22;
    ctx.fillStyle = color;
    ctx.fillRect(px, py - th, tw, th);
    ctx.fillStyle = "#0f172a";
    ctx.fillText(text, px + padX, py - padY);
    ctx.restore();
  }

  function colorForLabel(label) {
    if (!label) return "#94a3b8";
    let hash = 0;
    for (let i = 0; i < label.length; i++) {
      hash = (hash * 31 + label.charCodeAt(i)) & 0xffffffff;
    }
    return PALETTE[Math.abs(hash) % PALETTE.length];
  }

  function hexToRgba(hex, alpha) {
    const n = parseInt(hex.slice(1), 16);
    const r = (n >> 16) & 0xff, g = (n >> 8) & 0xff, b = n & 0xff;
    return `rgba(${r},${g},${b},${alpha})`;
  }

  function pxBox(b) {
    return [b.x * canvas.width, b.y * canvas.height, b.w * canvas.width, b.h * canvas.height];
  }

  // ----- Pointer events ------------------------------------------------------

  function eventToNorm(e) {
    const rect = canvas.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    const y = (e.clientY - rect.top) / rect.height;
    return { x: clamp(x), y: clamp(y) };
  }

  function clamp(v) {
    return Math.max(0, Math.min(1, v));
  }

  function hitTestAnnotations(p) {
    for (let i = annotations.length - 1; i >= 0; i--) {
      const a = annotations[i];
      if (p.x >= a.x && p.x <= a.x + a.w && p.y >= a.y && p.y <= a.y + a.h) return i;
    }
    return -1;
  }

  function hitTestSuggestion(p) {
    for (let i = suggestions.length - 1; i >= 0; i--) {
      const s = suggestions[i];
      if (p.x >= s.x && p.x <= s.x + s.w && p.y >= s.y && p.y <= s.y + s.h) return i;
    }
    return -1;
  }

  function handleAt(p) {
    if (selectedIdx < 0) return null;
    const a = annotations[selectedIdx];
    const tol = 0.02; // ~2% in normalized space
    const corners = {
      "resize-nw": { x: a.x, y: a.y },
      "resize-ne": { x: a.x + a.w, y: a.y },
      "resize-sw": { x: a.x, y: a.y + a.h },
      "resize-se": { x: a.x + a.w, y: a.y + a.h },
    };
    for (const [mode, c] of Object.entries(corners)) {
      if (Math.abs(p.x - c.x) < tol && Math.abs(p.y - c.y) < tol) return mode;
    }
    return null;
  }

  canvas.addEventListener("pointerdown", (e) => {
    canvas.setPointerCapture(e.pointerId);
    const p = eventToNorm(e);

    const handle = handleAt(p);
    if (handle) {
      dragMode = handle;
      dragStart = p;
      dragOriginalBox = { ...annotations[selectedIdx] };
      return;
    }

    const annHit = hitTestAnnotations(p);
    if (annHit >= 0) {
      selectedIdx = annHit;
      dragMode = "move";
      dragStart = p;
      dragOriginalBox = { ...annotations[selectedIdx] };
      classInput.value = annotations[selectedIdx].label || "";
      draw();
      return;
    }

    const sugHit = hitTestSuggestion(p);
    if (sugHit >= 0) {
      acceptSuggestion(sugHit);
      return;
    }

    // Draw new
    const label = (classInput.value || "").trim();
    if (!label) {
      setStatus("Type a class label first, then drag to draw a box.", "amber");
      return;
    }
    dragMode = "draw";
    dragStart = p;
    annotations.push({ label, x: p.x, y: p.y, w: 0, h: 0, source: "user" });
    selectedIdx = annotations.length - 1;
    dragOriginalBox = { ...annotations[selectedIdx] };
    draw();
  });

  canvas.addEventListener("pointermove", (e) => {
    if (!dragMode) return;
    const p = eventToNorm(e);
    const dx = p.x - dragStart.x;
    const dy = p.y - dragStart.y;
    const a = annotations[selectedIdx];
    const o = dragOriginalBox;

    if (dragMode === "draw") {
      a.x = Math.min(dragStart.x, p.x);
      a.y = Math.min(dragStart.y, p.y);
      a.w = Math.abs(p.x - dragStart.x);
      a.h = Math.abs(p.y - dragStart.y);
    } else if (dragMode === "move") {
      a.x = clamp(o.x + dx);
      a.y = clamp(o.y + dy);
    } else if (dragMode.startsWith("resize-")) {
      const corner = dragMode.split("-")[1];
      let x1 = o.x, y1 = o.y, x2 = o.x + o.w, y2 = o.y + o.h;
      if (corner.includes("w")) x1 = clamp(p.x);
      if (corner.includes("e")) x2 = clamp(p.x);
      if (corner.includes("n")) y1 = clamp(p.y);
      if (corner.includes("s")) y2 = clamp(p.y);
      a.x = Math.min(x1, x2);
      a.y = Math.min(y1, y2);
      a.w = Math.abs(x2 - x1);
      a.h = Math.abs(y2 - y1);
    }
    dirty = true;
    draw();
  });

  canvas.addEventListener("pointerup", () => {
    if (dragMode) {
      // Drop zero-size boxes from "draw" mode
      const a = annotations[selectedIdx];
      if (a && (a.w < 0.01 || a.h < 0.01)) {
        annotations.splice(selectedIdx, 1);
        selectedIdx = -1;
      }
      dragMode = null;
      dragStart = null;
      dragOriginalBox = null;
      draw();
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.target === classInput) {
      if (e.key === "Enter" && selectedIdx >= 0) {
        const label = classInput.value.trim();
        if (label) {
          annotations[selectedIdx].label = label;
          dirty = true;
          draw();
        }
      }
      return;
    }
    if (e.key === "Backspace" || e.key === "Delete") {
      if (selectedIdx >= 0) {
        annotations.splice(selectedIdx, 1);
        selectedIdx = -1;
        dirty = true;
        draw();
      }
    }
  });

  function acceptSuggestion(idx) {
    const s = suggestions[idx];
    let label = s.label;
    if (!label) {
      const typed = classInput.value.trim();
      if (!typed) {
        setStatus("Type a class label first, then click the unlabeled suggestion.", "amber");
        return;
      }
      label = typed;
    }
    annotations.push({ label, x: s.x, y: s.y, w: s.w, h: s.h, source: "user" });
    suggestions.splice(idx, 1);
    selectedIdx = annotations.length - 1;
    dirty = true;
    draw();
  }

  // ----- Save / clear --------------------------------------------------------

  saveButton.addEventListener("click", () => save(true));
  clearButton.addEventListener("click", () => {
    if (!confirm("Remove all boxes? AI suggestions will be re-shown.")) return;
    annotations = [];
    selectedIdx = -1;
    dirty = true;
    draw();
  });

  // Auto-save every 10s when dirty
  setInterval(() => { if (dirty) save(false); }, 10_000);

  function save(notifyOk) {
    if (!dirty && !notifyOk) return;
    setStatus("Saving…");
    fetch(annotationsURL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrf,
      },
      body: JSON.stringify({
        annotations: annotations.map((a) => ({
          label: a.label,
          x_center: a.x + a.w / 2,
          y_center: a.y + a.h / 2,
          width: a.w,
          height: a.h,
        })),
      }),
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.error) {
          setStatus("Save failed: " + data.error, "rose");
          return;
        }
        dirty = false;
        setStatus("Saved · " + annotations.length + " box(es)", "emerald");
      })
      .catch((err) => setStatus("Save failed: " + err, "rose"));
  }

  function setStatus(text, color) {
    statusEl.textContent = text;
    statusEl.className = "text-xs " +
      (color === "rose" ? "text-rose-400"
        : color === "amber" ? "text-amber-400"
          : color === "emerald" ? "text-emerald-400"
            : "text-slate-400");
  }
})();
