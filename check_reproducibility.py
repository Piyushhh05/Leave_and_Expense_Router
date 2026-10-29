"""
check_reproducibility.py - STEP 10: same seed -> same data.

    python check_reproducibility.py

Generates the dataset twice into temporary folders with the same seed and compares
row counts and SHA-256 checksums of every CSV. Also generates once with a different
seed to show that the checksums really do change (so the test can fail).
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
SEED = 20261022


def generate(out_dir, seed):
    subprocess.run([sys.executable, "-B", "-m", "generator.generate_data", "--seed", str(seed), "--out", out_dir],
                   cwd=ROOT, check=True, capture_output=True)
    with open(os.path.join(out_dir, "manifest.json"), encoding="utf-8") as f:
        return json.load(f)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        run1 = generate(os.path.join(tmp, "run1"), SEED)
        run2 = generate(os.path.join(tmp, "run2"), SEED)
        other = generate(os.path.join(tmp, "other"), SEED + 1)

    print(f"{'table':22s} {'rows run1':>9s} {'rows run2':>9s}  checksum run1 / run2")
    all_same = True
    for table in run1["row_counts"]:
        same = (run1["row_counts"][table] == run2["row_counts"][table]
                and run1["sha256"][table + ".csv"] == run2["sha256"][table + ".csv"])
        all_same &= same
        print(f"{table:22s} {run1['row_counts'][table]:9d} {run2['row_counts'][table]:9d}  "
              f"{run1['sha256'][table + '.csv'][:12]} / {run2['sha256'][table + '.csv'][:12]}  {'SAME' if same else 'DIFFERENT'}")

    differs = sum(run1["sha256"][t + ".csv"] != other["sha256"][t + ".csv"] for t in run1["row_counts"])
    print(f"\nSame seed twice  : {'IDENTICAL' if all_same else 'DIFFERENT (problem!)'}")
    print(f"Different seed   : {differs} of {len(run1['row_counts'])} files differ (proves the check can fail)")

    # also compare with the dataset that is checked into ./data
    shipped = os.path.join(ROOT, "data", "manifest.json")
    if os.path.exists(shipped):
        with open(shipped, encoding="utf-8") as f:
            shipped_manifest = json.load(f)
        same_as_shipped = shipped_manifest["sha256"] == run1["sha256"]
        print(f"Matches ./data   : {'YES' if same_as_shipped else 'NO (regenerate ./data)'}")
        all_same &= same_as_shipped
    sys.exit(0 if all_same and differs > 0 else 1)


if __name__ == "__main__":
    main()
