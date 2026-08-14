"""Bring-up probe for Jetson + Kinect + GT511C3 (and R307 fallback).

Run on the edge board after wiring::

    driveauth-probe-hw
    # or: python -m hardware.probe_hw

Exits 0 when at least one critical path answers; non-zero if everything fails.
Does not enroll or mutate the template store.
"""

from __future__ import annotations

import argparse
import logging


def _ok(label: str, detail: str = "") -> None:
    suffix = f" — {detail}" if detail else ""
    print(f"[OK]   {label}{suffix}")


def _fail(label: str, detail: str = "") -> None:
    suffix = f" — {detail}" if detail else ""
    print(f"[FAIL] {label}{suffix}")


def _skip(label: str, detail: str = "") -> None:
    suffix = f" — {detail}" if detail else ""
    print(f"[SKIP] {label}{suffix}")


def probe_finger(port: str | None) -> bool:
    from hardware.finger_uart import open_default_sensor

    try:
        sensor, kind = open_default_sensor(
            port=port,
            allow_manual_fallback=False,
        )
    except RuntimeError as exc:
        _fail("fingerprint UART", str(exc))
        return False
    try:
        _ok("fingerprint UART", f"kind={kind} port={getattr(sensor, 'port', '?')}")
        if kind in ("gt511", "pyfingerprint"):
            print("       Place finger on platen for a 1-shot capture test…")
            img = sensor.capture_image()
            if img and len(img) == 65536:
                _ok("fingerprint capture", f"{len(img)} bytes")
            else:
                _fail("fingerprint capture", "empty or wrong size (finger on sensor?)")
                return False
        return True
    finally:
        try:
            sensor.close()
        except Exception:
            pass


def probe_kinect() -> bool:
    from hardware.kinect_capture import KinectCapture, freenect_available

    if not freenect_available():
        _skip("Kinect freenect", "import freenect failed — install libfreenect + bindings")
        return False
    cap = KinectCapture()
    if not cap.start():
        _fail("Kinect", "start() failed (USB claim / power?)")
        return False
    try:
        rgb = cap.capture_bgr()
        depth = cap.capture_depth()
        if rgb is None:
            _fail("Kinect RGB", "no frame")
            return False
        _ok("Kinect RGB", f"crop shape={getattr(rgb, 'shape', None)}")
        if depth is None:
            _fail("Kinect depth", "no frame")
            return False
        _ok("Kinect depth", f"shape={depth.shape} dtype={depth.dtype}")
        return True
    finally:
        cap.stop()


def probe_opencv_cam(index: int) -> bool:
    try:
        import cv2  # type: ignore
    except ImportError:
        _skip("OpenCV camera", "opencv-python not installed")
        return False
    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        _fail("OpenCV camera", f"index {index} open failed")
        return False
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        _fail("OpenCV camera", f"index {index} read failed")
        return False
    _ok("OpenCV camera", f"index={index} shape={frame.shape}")
    return True


def probe_mic() -> bool:
    from hardware.kinect_capture import SoundDeviceAudioBackend

    backend = SoundDeviceAudioBackend()
    if not backend.open(16_000, 1):
        _fail("mic (sounddevice)", "open failed — check DRIVEAUTH_MIC_DEVICE")
        return False
    try:
        buf = backend.read(16_000)  # 1 s
        if buf is None or buf.size == 0:
            _fail("mic", "empty buffer")
            return False
        _ok("mic", f"samples={buf.size} peak={float(abs(buf).max()):.4f}")
        return True
    finally:
        backend.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="DriveAuth Edge hardware probe")
    parser.add_argument("--port", default=None, help="UART port override")
    parser.add_argument("--camera", type=int, default=0, help="OpenCV camera index")
    parser.add_argument("--skip-finger", action="store_true")
    parser.add_argument("--skip-kinect", action="store_true")
    parser.add_argument("--skip-mic", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    print("DriveAuth Edge — hardware probe")
    print("=" * 40)
    results: list[bool] = []

    if not args.skip_finger:
        # Allow fallback logging to show clearly; probe_finger disables fallback.
        results.append(probe_finger(args.port))
    if not args.skip_kinect:
        kinect_ok = probe_kinect()
        results.append(kinect_ok)
        if not kinect_ok:
            results.append(probe_opencv_cam(args.camera))
    if not args.skip_mic:
        results.append(probe_mic())

    print("=" * 40)
    if any(results):
        print("Probe finished — at least one path OK.")
        raise SystemExit(0)
    print("Probe finished — no sensors answered.")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
