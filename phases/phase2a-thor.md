# Phase 2a on Thor — from scratch

End-to-end: empty (or cleaned) Thor board → ECAPA + MobileFaceNet enrolled →
latency profile in **`phases/phase2a-thor.txt`**.

SSH examples use the existing tunnel host; swap host/port/user if yours differ:

```text
ssh -p 10617 acf-thor@fw1.sshreachme-trial.com
```

Mac baseline for comparison: [`phase2a-mac.txt`](phase2a-mac.txt).

---

## 0. From your Mac — prepare what Thor needs

On the Mac repo (`staged_driveauth-edge`):

```bash
cd /path/to/staged_driveauth-edge

# Confirm you have enroll media (wav + jpg)
ls data/driver1/voice/enroll/*.wav | head
ls data/driver1/face/enroll/*.jpg | head

# Confirm Mac store works (optional sanity)
ls driveauth_store_phase2a/models/
ls driveauth_store_phase2a/voices/ driveauth_store_phase2a/faces/
```

You will either:

- **A)** sync the whole repo + Mac `driveauth_store_phase2a` (fastest), or  
- **B)** sync repo + `data/` only and rebuild the store on Thor (safer if arch differs).

**Recommended for from-scratch:** **B** (rebuild on Thor).

---

## 1. SSH into Thor

```bash
ssh -p 10617 acf-thor@fw1.sshreachme-trial.com
uname -a          # expect aarch64 / tegra
nvidia-smi        # expect NVIDIA Thor (or Jetson GPU)
python3 --version # 3.10+ OK (Mac used 3.11; Thor often 3.12)
```

If `nvidia-smi` fails, fix the driver/JetPack stack before continuing.

---

## 2. Copy the project onto Thor (from Mac)

**In a Mac terminal** (not on Thor):

```bash
# MUST be the repo root (not ~). Confirm first:
cd /Users/par_04/code_playground/projects/staged_driveauth-edge
pwd
ls README.md scripts/phase2a_bench.py   # both must exist

# Repo + Phase 3 enroll media; skip .venv / caches / huge unrelated dumps
rsync -avz -e 'ssh -p 10617' \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.git' \
  --exclude '.pytest_cache' \
  --exclude 'driveauth_store_phase2a' \
  --exclude 'docs/demo.gif' \
  ./ acf-thor@fw1.sshreachme-trial.com:~/staged_driveauth-edge/
```

If you accidentally rsynced from `~`, wipe Thor’s copy and re-run from the repo:

```bash
ssh -p 10617 acf-thor@fw1.sshreachme-trial.com 'rm -rf ~/staged_driveauth-edge'
```

Confirm enroll files arrived (on Thor):

```bash
cd ~/staged_driveauth-edge
ls data/driver1/voice/enroll/*.wav | wc -l
ls data/driver1/face/enroll/*.jpg | wc -l
# want ≥5 each
```

---

## 3. Python venv + dependencies (on Thor)

```bash
cd ~/staged_driveauth-edge

python3 -m venv .venv
source .venv/bin/activate
pip install -U pip wheel setuptools

# Core + dashboard + ORT + ECAPA + face
pip install -e ".[dev,dashboard,onnx,voice,face]"
```

### 3a. Check PyTorch sees GPU

```bash
python - <<'PY'
import torch
print("torch", torch.__version__)
print("cuda_available", torch.cuda.is_available())
if torch.cuda.is_available():
    print("device", torch.cuda.get_device_name(0))
PY
```

- If `cuda_available` is **False**, install a **JetPack-matched** PyTorch wheel from NVIDIA’s docs (do not grab a random `pip install torch` CUDA wheel for x86). ECAPA will still run on CPU, but slower.

### 3b. Check ONNX Runtime providers (face)

```bash
python - <<'PY'
import onnxruntime as ort
print("ORT", ort.__version__)
print("providers", ort.get_available_providers())
PY
```

| Providers | Meaning |
|-----------|---------|
| includes `CUDAExecutionProvider` | ✅ preferred for face ONNX |
| only `CPUExecutionProvider` (+ Azure) | OK for a profile, but note “CPU EP” in the log |

**If CUDA EP missing but `nvidia-smi` works:**

```bash
pip uninstall -y onnxruntime onnxruntime-gpu
# then install the JetPack / Thor GPU wheel from NVIDIA docs, e.g. often:
#   pip install onnxruntime-gpu
# or a .whl URL from your JetPack release notes — match CUDA version
python -c "import onnxruntime as ort; print(ort.get_available_providers())"
```

---

## 4. Environment variables (on Thor)

```bash
cd ~/staged_driveauth-edge
source .venv/bin/activate

export DRIVEAUTH_USE_MOCK=0
export DRIVEAUTH_FINGERPRINT_AVAILABLE=0
export DRIVEAUTH_STORE_DIR="$PWD/driveauth_store_phase2a"
mkdir -p "$DRIVEAUTH_STORE_DIR"
```

Put these in `~/.bashrc` if you want them every session.

---

## 5. Download pretrained models (on Thor)

```bash
python scripts/phase2a_setup.py --store "$DRIVEAUTH_STORE_DIR"
```

Expect:

- `driveauth_store_phase2a/models/ecapa_voxceleb/…`
- `driveauth_store_phase2a/models/mobilefacenet.onnx` (or next to store)

Needs network on Thor. If downloads fail, copy from Mac:

```bash
# Mac → Thor (example)
scp -P 10617 -r driveauth_store_phase2a/models \
  acf-thor@fw1.sshreachme-trial.com:~/staged_driveauth-edge/driveauth_store_phase2a/
```

---

## 6. Enroll voice + face (on Thor)

```bash
python scripts/phase2a_enroll.py \
  --store "$DRIVEAUTH_STORE_DIR" \
  --data ./data/driver1
```

Expect enrolled templates under:

- `driveauth_store_phase2a/voices/`
- `driveauth_store_phase2a/faces/`

---

## 7. Smoke demo — must ACCEPT (on Thor)

```bash
python scripts/phase2a_demo.py \
  --store "$DRIVEAUTH_STORE_DIR" \
  --face-image data/driver1/face/enroll/enroll_01.jpg
```

Pass when you see:

```text
Matchers:
  voice: VoiceMatcher ready=True
  face: FaceMatcher ready=True
…
Decision:   ACCEPT
```

If not ready / mock matchers: fix install (`.[voice,face]`) and re-run setup/enroll.

---

## 8. Latency bench → write profile (on Thor)

```bash
python scripts/phase2a_bench.py \
  --store "$DRIVEAUTH_STORE_DIR" \
  --out phases/phase2a-thor.txt \
  --device cuda \
  --n 30
```

Pass when:

- Status line shows **PASS** (`REAL_AUTH_P95_MS=200`)
- `phases/phase2a-thor.txt` exists
- Log shows `ECAPA torch device: cuda` if GPU torch works (else `cpu` — still record it)
- ORT providers line shows CUDA if you got GPU ORT

---

## 9. Copy result back to Mac

**On Mac:**

```bash
cd /path/to/staged_driveauth-edge

scp -P 10617 \
  acf-thor@fw1.sshreachme-trial.com:~/staged_driveauth-edge/phases/phase2a-thor.txt \
  ./phases/phase2a-thor.txt

# compare
grep -E 'p50=|p95=|Status|providers|torch device' \
  phases/phase2a-mac.txt phases/phase2a-thor.txt
```

Then check off TODO: *Thor latency profile*.

---

## 10. Optional — dashboard from Mac browser

**Thor:**

```bash
source .venv/bin/activate
export DRIVEAUTH_USE_MOCK=0
export DRIVEAUTH_STORE_DIR="$PWD/driveauth_store_phase2a"
export DRIVEAUTH_DASHBOARD_HOST=0.0.0.0
export DRIVEAUTH_DASHBOARD_PORT=8765
driveauth-dashboard
```

**Mac (separate terminal):**

```bash
ssh -p 10617 -L 8765:127.0.0.1:8765 acf-thor@fw1.sshreachme-trial.com
# open http://127.0.0.1:8765
```

---

## One-shot checklist

| # | Where | Command / action | Done? |
|---|-------|------------------|-------|
| 0 | Mac | enroll wav/jpg present | ☐ |
| 1 | Mac→Thor | `rsync` repo + `data/` | ☐ |
| 2 | Thor | `nvidia-smi` OK | ☐ |
| 3 | Thor | venv + `pip install -e ".[dev,dashboard,onnx,voice,face]"` | ☐ |
| 3a | Thor | `torch.cuda.is_available()` (prefer True) | ☐ |
| 3b | Thor | ORT lists CUDA EP (prefer) | ☐ |
| 4 | Thor | export `DRIVEAUTH_*` | ☐ |
| 5 | Thor | `phase2a_setup.py` | ☐ |
| 6 | Thor | `phase2a_enroll.py` | ☐ |
| 7 | Thor | `phase2a_demo.py` → ACCEPT | ☐ |
| 8 | Thor | `phase2a_bench.py` → PASS ≤200 ms p95 | ☐ |
| 9 | Mac | `scp` `phase2a-thor.txt` home | ☐ |

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `MockVoiceMatcher` / not ready | `pip install -e ".[voice,face]"`; re-run setup + enroll |
| No enroll wav/jpg | rsync `data/driver1` again; or enroll `--synthetic` only for smoke (not for real profile) |
| `torch.cuda.is_available() False` | Install NVIDIA JetPack PyTorch wheel for this board |
| ORT CPU-only | Uninstall `onnxruntime`; install JetPack `onnxruntime-gpu` wheel |
| `cudaErrorNoKernelImageForDevice` on face | GPU ORT wheel SM ≠ this Thor. Force CPU: `export DRIVEAUTH_ORT_PROVIDERS=CPUExecutionProvider` (ECAPA can stay on CUDA). Or rebuild ORT for this board’s `compute_cap` |
| DRM / device discovery warnings | Harmless if smoke/bench still runs; often seen on Tegra |
| Demo ACCEPT but bench FAIL p95 | Note hardware; check thermal/throttling; increase `n` after warmup already in script |
| SSH / rsync refused | Renew sshreachme trial / confirm port `10617` / user `acf-thor` |
| Out of disk | `df -h`; delete old `.venv` rebuilds; don’t copy Mac `docs/demo.gif` |

---

## Fast path if store already on Mac

Skip steps 5–6 by syncing the store too:

```bash
# Mac
rsync -avz -e 'ssh -p 10617' \
  driveauth_store_phase2a/ \
  acf-thor@fw1.sshreachme-trial.com:~/staged_driveauth-edge/driveauth_store_phase2a/
```

Then continue from step 7 (still do step 3 deps on Thor).

---

## Face on CUDA (SM110) — required for “all on CUDA”

Thor reports **`compute_cap 11.0`**. Wheels built for SM121 will load CUDA EP then
crash with `cudaErrorNoKernelImageForDevice`. You must **build ORT for SM110**.

### On Thor (project venv)

```bash
cd ~/Parth/staged_driveauth-edge   # or your path
source .venv/bin/activate

# sync latest scripts from Mac first if needed, then:
bash scripts/build_ort_cuda_thor.sh
# ~1–3 hours; if OOM:  ORT_PARALLEL=4 bash scripts/build_ort_cuda_thor.sh
```

Success when smoke prints `CUDA EP OK` and `MobileFaceNet CUDA smoke OK`.

### Re-bench with face on CUDA

```bash
unset DRIVEAUTH_ORT_PROVIDERS          # do NOT force CPU
export DRIVEAUTH_USE_MOCK=0
export DRIVEAUTH_FINGERPRINT_AVAILABLE=0
export DRIVEAUTH_STORE_DIR="$PWD/driveauth_store_phase2a"

python scripts/phase2a_bench.py \
  --store "$DRIVEAUTH_STORE_DIR" \
  --out phases/phase2a-thor.txt \
  --device cuda --n 30
```

Expect in `phase2a-thor.txt`:

```text
ORT … providers=[…, 'CUDAExecutionProvider', …]
ECAPA torch device: cuda
```

and face latency without `no kernel image` errors.

### Copy to Mac

```bash
scp -P 10617 \
  acf-thor@fw1.sshreachme-trial.com:/home/acf-thor/Parth/staged_driveauth-edge/phases/phase2a-thor.txt \
  ./phases/phase2a-thor.txt
```
