# Phase 8 — Publications & demo video

**Status:** 🟡 In progress (2026-07-15)  
**Done means (roadmap):** paper submitted · demo video published

## Venue decision (locked)

| Choice | Decision |
|--------|----------|
| **Primary** | **IEEE IV 2027** (Intelligent Vehicles Symposium) — Perth, 15–18 Jun 2027 |
| Format | Regular paper, ≤6 pages incl. figures/refs (confirm on [ieee-iv.org/2027](https://ieee-iv.org/2027/)) |
| Framing | **Automotive systems** — Trust/Risk/Confidence separation, staged ladder, edge latency, honest eval |
| Why not ITSC 2026 | Regular submission deadline already passed (1 Mar 2026) |
| Backup | ITSC 2027 cycle if IV rejects / schedule slips |
| CCS/NDSS | **Only if** reframed to lead with timing pad, OOD-drift, security floor — not the default path |

### IV 2027 dates (as of July 2026 CFP)

| Milestone | Date |
|-----------|------|
| Portal open | 1 Jul 2026 |
| **Paper deadline** | **15 Nov 2026** |
| Notification | 15 Jan 2027 |
| Camera-ready | 1 Feb 2027 |

Sources: [Contributions](https://ieee-iv.org/2027/contributions/) · [CFP](https://ieee-iv.org/2027/contributions/call-for-papers/)

### When to switch to CCS/NDSS framing

Lead abstract/intro with:

1. Timing side-channel tests (`tests/test_security_sprint1.py`)
2. OOD-refresh gate / drift attack simulation
3. Early-stop vs security-floor ablation (`phases/phase6.md` §A1)

Keep systems architecture as background; expand threat model + adversarial sections.
Do **not** claim production FAR/FRR or certified PAD — see [`docs/security-assumptions.md`](../docs/security-assumptions.md) §6.

## Artifacts

| Path | Role |
|------|------|
| [`docs/paper/whitepaper.md`](../docs/paper/whitepaper.md) | **White paper** (~15–20 pp systems manuscript) |
| [`docs/paper/iv2027-draft.md`](../docs/paper/iv2027-draft.md) | Short conference draft (markdown → IEEE template later) |
| [`docs/paper/demo-video.md`](../docs/paper/demo-video.md) | 5–8 min storyboard + shot list + VO script |
| [`phases/phase6.md`](phase6.md) | Tables to paste / cite (FAR/FRR/EER/ROC, ablations, latency) |
| [`docs/security-assumptions.md`](../docs/security-assumptions.md) | Honesty bar for claims |
| [`docs/demo.gif`](../docs/demo.gif) | Placeholder loop until full video cuts |

## Working title

**DriveAuth Edge: Trust/Risk-Separated Offline Biometric Authorization for In-Vehicle Payments**

## Contribution claims (allowed)

1. Architectural separation of Trust (biometric-only), Risk (txn/vehicle), Confidence (capture quality / OOD) with a deterministic policy engine.
2. Staged Voice→Face→Finger ladder with measurable early-stop vs security-floor trade-off.
3. Edge deployment evidence: Mac + NVIDIA Thor; Phase-2a micro p95 ≈ 7.7 ms (Thor CUDA).
4. Evaluation package: Sprint 6 biometrics/PAD/risk/latency + security tests (timing, OOD-drift) with explicit non-claims for finger HW and synth CAN.

## Non-claims (paper must keep)

See security-assumptions §6. Especially: no production finger FAR/FRR; no synth-CAN behavioral as fleet-ready; Risk AUC on synthetic 50k txn labels; shipping bars may show FRR=1 by design.

## Checklist

### White paper
- [x] Long-form manuscript → [`docs/paper/whitepaper.md`](../docs/paper/whitepaper.md)
- [ ] Authors / affiliations filled
- [ ] PDF layout (or arXiv) · expand bibliography
- [ ] Metrics freeze: re-run `phase6_benchmark.py` before publish
- [ ] Record published URL / DOI below

### Conference paper (IV 2027)
- [x] Venue locked (IV 2027 primary)
- [x] Markdown draft with abstract → conclusion
- [ ] Authors / affiliations / acknowledgments filled
- [ ] Port to IEEE conference template (Word or LaTeX)
- [ ] Figures: architecture diagram, ladder, ROC or bar ablations, latency table
- [ ] Blind-review scrub (if required) · bibtex related work
- [ ] Internal review against security-assumptions §6
- [ ] Submit via IV portal before **15 Nov 2026**
- [ ] Record Papercept / submission ID below

### Demo video
- [x] Storyboard + VO script (`docs/paper/demo-video.md`)
- [ ] Screen capture: dashboard ACCEPT / STEP_UP / REJECT
- [ ] Optional: Thor board + latency overlay
- [ ] Optional: attack vignettes (replay / screen / low scores)
- [ ] Edit 5–8 min cut · export 1080p
- [ ] Publish (YouTube unlisted/public + README link)
- [ ] Record published URL below

### After submit / publish
- [ ] Tick [`TODO.txt`](../TODO.txt) Phase 8
- [ ] Update README status row
- [ ] Link from [`docs/public-posts.md`](../docs/public-posts.md)

## Submission log

| Item | ID / URL | Date |
|------|----------|------|
| White paper PDF / arXiv | | |
| IV 2027 paper | | |
| Demo video | | |

## Re-run data before camera-ready

```bash
python scripts/phase6_benchmark.py
pytest -q
# optional Thor refresh if numbers change:
# scripts/phase2a_bench.py → phases/phase2a-thor.txt
```
