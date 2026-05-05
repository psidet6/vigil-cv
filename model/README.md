# Model Directory

Model binaries are intentionally not tracked in Git.

Expected runtime filenames:

- `special_event_detector.pt`: optional custom detector for demo-specific classes
- `yolov8s-worldv2.pt`: default open-vocabulary detection model
- `yolo26n.pt`: compact base model for training experiments
- `yolo26s.pt`: small base model for balanced training experiments
- `det_10g.onnx`: face detection model
- `w600k_r50.onnx`: face recognition model
- `mobileclip_blt.ts`, `mobileclip2_b.ts`, `ViT-B-32.pt`: optional prompt/text assets

Keep real model weights outside public commits and provide them only in the
target runtime environment.
