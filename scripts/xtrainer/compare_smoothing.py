"""Compare legacy smoothing on a recorded sequential control trace; no hardware imports."""
import argparse
import json
from pathlib import Path
import numpy as np

JOINTS = np.r_[0:6, 7:13]


def smooth_chunk(actions, strength=.5):
    result = np.asarray(actions, dtype=np.float64).copy()
    if len(result) >= 3:
        result[1:-1, JOINTS] = ((1-strength)*result[1:-1, JOINTS]
            + strength*.5*(result[:-2, JOINTS]+result[2:, JOINTS]))
    return result


def metrics(actions, hz):
    joints = np.asarray(actions)[:, JOINTS]
    result = {}
    for order, name in [(1, "step_rad"), (2, "acceleration_rad_s2")]:
        values = np.abs(np.diff(joints, n=order, axis=0))
        if order == 2:
            values *= hz**2
        result[name] = None if not values.size else {
            "max": float(values.max()), "p95": float(np.percentile(values, 95)),
            "mean": float(values.mean())}
    return result


def compare(path, horizon, hz, strength):
    records = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    steps = [r for r in records if r.get("event") == "control_step"]
    if not steps or any(r.get("rtc") for r in steps):
        raise ValueError("Provide a nonempty sequential (RTC disabled) control trace")
    indices = [r["control_timestep"] for r in steps]
    if indices != list(range(len(indices))):
        raise ValueError("Trace must start at step zero with contiguous control steps")
    raw = np.asarray([r["queued_action"] for r in steps], dtype=np.float64)
    if raw.shape != (len(steps), 14) or not np.isfinite(raw).all():
        raise ValueError("Expected finite 14-D actions")
    filtered = np.concatenate([smooth_chunk(raw[i:i+horizon], strength) for i in range(0,len(raw),horizon)])
    return {"steps": len(steps), "horizon": horizon, "control_hz": hz,
        "raw": metrics(raw,hz), "three_point_smoothed": metrics(filtered,hz),
        "max_position_change_rad": float(np.abs(filtered[:, JOINTS]-raw[:, JOINTS]).max()),
        "note": "Command differences only; not measured robot acceleration. Chunk boundaries use the supplied horizon."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--horizon", type=int, required=True)
    parser.add_argument("--control-hz", type=float, default=33)
    parser.add_argument("--strength", type=float, default=.5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.horizon < 1 or not np.isfinite(args.control_hz) or args.control_hz <= 0 or not 0 <= args.strength <= 1:
        parser.error("Require horizon>0, finite control-hz>0 and strength in [0,1]")
    report = compare(args.trace,args.horizon,args.control_hz,args.strength)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
