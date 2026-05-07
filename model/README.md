# Model Directory

Model binaries are intentionally not tracked in Git. The runtime expects the
files below to be present (locally trained or supplied separately).

## Expected files

- `helmet-detector.pt` — default closed-set YOLOv8s detector for
  construction-site helmet compliance. Default class layout: `helmet`,
  `no_helmet` (two classes). Train your own with the scripts under
  `scripts/`, or drop in a pretrained checkpoint with the same layout.
- `yolov8s-worldv2.pt` — open-vocabulary detector used for prompt-based
  search and pre-annotation.
- `yolo26n.pt`, `yolo26s.pt` — compact / small base models for training
  experiments.
- `det_10g.onnx` — face detection model.
- `w600k_r50.onnx` — face recognition model.
- `mobileclip_blt.ts`, `mobileclip2_b.ts`, `ViT-B-32.pt` — optional
  prompt / text assets.

## Train the helmet detector

The repository includes two helper scripts so you can produce
`helmet-detector.pt` from scratch in roughly two commands.

### 1. Prepare the dataset

```bash
# Option A — Roboflow Universe (default). The recommended public dataset
# is "Hard Hat Workers" by joseph-nelson (CC BY 4.0).
export ROBOFLOW_API_KEY=<your-roboflow-key>
python scripts/prepare_helmet_dataset.py --source roboflow

# Option B — bring your own YOLO-format dataset
python scripts/prepare_helmet_dataset.py --source local --local-path /path/to/dataset
```

The script writes `datasets/helmet/` with a YOLOv8-compatible layout and
generates `data.yaml`. By default upstream classes are merged into
`[helmet, no_helmet]` so the model has a clear binary signal; pass
`--keep-original-classes` to preserve the upstream layout.

### 2. Train

```bash
pip install ultralytics  # if not already installed
python scripts/train_helmet_model.py --epochs 50 --imgsz 640 --batch 16
```

The script fine-tunes `yolov8s.pt` (auto-downloaded) on `datasets/helmet/`,
saves training artifacts under `runs/train/helmet/` (loss curves,
confusion matrix, best/last weights), and copies the best checkpoint to
`model/helmet-detector.pt` automatically.

Pass `--device cpu` for CPU-only environments. Expect roughly 15–60
minutes on a single mid-range GPU at the default settings.

## Dataset license & attribution

The default Roboflow project ("Hard Hat Workers") is distributed under
**CC BY 4.0**. If you publish a derived model or video tutorial:

- Retain the upstream attribution to the dataset author.
- Link back to the Roboflow Universe project page.
- Keep the CC BY 4.0 notice in your project's documentation.

Real model weights, raw datasets, and credentials must stay outside the
public repository. They should be supplied only inside the target runtime
environment (or trained locally).
