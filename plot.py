#!/usr/bin/env python3
"""results.csv -> 집계 -> chart.png.

호출 단위로 기록된 raw log 를 (dataset, shot_count) 단위로 집계해서
설계에서 정한 4개 지표를 그린다.

  1순위: Shot count vs Average Loop Count   <- 메인 결과
  2순위: Shot vs Total Latency
  3순위: Shot vs Input Tokens
  4순위: Shot vs Success Rate
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

COLORS = ["#c0392b", "#2471a3", "#1e8449", "#8e44ad"]
MARKERS = ["o", "s", "^", "D"]


def load_samples(path):
    """(dataset, shot) -> 샘플별 요약 dict 로 접는다."""
    per_sample = defaultdict(lambda: {"loops": 0, "latency_s": 0.0,
                                      "input_tokens": 0, "output_tokens": 0,
                                      "success": False})
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            # loop_index=0 은 모델 응답을 못 받은 API 실패(429/타임아웃)다.
            # 오답이 아니므로 집계에서 제외한다.
            if int(row["loop_index"]) == 0:
                continue
            key = (row["dataset"], int(row["shot_count"]), row["seed"], row["sample_id"])
            rec = per_sample[key]
            rec["loops"] = max(rec["loops"], int(row["loop_index"]))
            rec["latency_s"] += float(row["latency_ms"] or 0) / 1000.0
            rec["input_tokens"] += int(row["input_tokens"] or 0)
            rec["output_tokens"] += int(row["output_tokens"] or 0)
            rec["success"] = rec["success"] or row["correct"] == "True"

    grouped = defaultdict(list)
    for (dataset, shot, _seed, _sid), rec in per_sample.items():
        grouped[(dataset, shot)].append(rec)
    return grouped


def mean(values):
    return sum(values) / len(values) if values else float("nan")


def aggregate(grouped):
    table = {}
    for (dataset, shot), recs in grouped.items():
        table[(dataset, shot)] = {
            "n": len(recs),
            "avg_loops": mean([r["loops"] for r in recs]),
            "avg_latency_s": mean([r["latency_s"] for r in recs]),
            "avg_input_tokens": mean([r["input_tokens"] for r in recs]),
            "avg_output_tokens": mean([r["output_tokens"] for r in recs]),
            "success_rate": mean([1.0 if r["success"] else 0.0 for r in recs]) * 100.0,
        }
    return table


def print_table(table, datasets, shots):
    header = f"{'dataset':<12}{'shot':>5}{'n':>5}{'avg_loop':>10}{'latency_s':>11}" \
             f"{'in_tok':>10}{'out_tok':>9}{'success%':>10}"
    print(header)
    print("-" * len(header))
    for dataset in datasets:
        for shot in shots:
            row = table.get((dataset, shot))
            if not row:
                continue
            print(f"{dataset:<12}{shot:>5}{row['n']:>5}{row['avg_loops']:>10.2f}"
                  f"{row['avg_latency_s']:>11.2f}{row['avg_input_tokens']:>10.0f}"
                  f"{row['avg_output_tokens']:>9.0f}{row['success_rate']:>10.1f}")


PANELS = [
    ("avg_loops", "Average loop count to reach the answer", "Avg loop count", True),
    ("avg_latency_s", "Total latency to reach the answer", "Avg total latency (s)", False),
    ("avg_input_tokens", "Input tokens spent per sample", "Avg input tokens", False),
    ("success_rate", "Success rate within max loops", "Success rate (%)", False),
]


def draw(table, datasets, shots, out_path, title):
    x = list(range(len(shots)))
    fig, axes = plt.subplots(2, 2, figsize=(12, 8.5))

    for ax, (metric, subtitle, ylabel, is_main) in zip(axes.ravel(), PANELS):
        for i, dataset in enumerate(datasets):
            ys = [table[(dataset, s)][metric] if (dataset, s) in table else float("nan")
                  for s in shots]
            ax.plot(x, ys, marker=MARKERS[i % len(MARKERS)], color=COLORS[i % len(COLORS)],
                    linewidth=2.2 if is_main else 1.7, markersize=7 if is_main else 5,
                    label=dataset)
            if is_main:
                for xi, yi in zip(x, ys):
                    if yi == yi:
                        ax.annotate(f"{yi:.2f}", (xi, yi), textcoords="offset points",
                                    xytext=(0, 8), ha="center", fontsize=8,
                                    color=COLORS[i % len(COLORS)])
        ax.set_xticks(x)
        ax.set_xticklabels([str(s) for s in shots])
        ax.set_xlabel("few-shot examples")
        ax.set_ylabel(ylabel)
        ax.set_title(("[MAIN] " if is_main else "") + subtitle,
                     fontsize=11, fontweight="bold" if is_main else "normal")
        ax.grid(alpha=0.3, linestyle="--")
        ax.legend(fontsize=9)
        if metric == "success_rate":
            ax.set_ylim(-5, 105)

    fig.suptitle(title, fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(out_path, dpi=160)
    print(f"\nsaved -> {out_path}")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--results", default="results.csv")
    p.add_argument("--out", default="chart.png")
    p.add_argument("--title", default="Few-shot count vs Agent loop cost (same Gemini model)")
    args = p.parse_args()

    grouped = load_samples(args.results)
    if not grouped:
        raise SystemExit(f"[error] {args.results} 에 집계할 행이 없다.")
    table = aggregate(grouped)
    datasets = sorted({d for d, _ in table})
    shots = sorted({s for _, s in table})

    print_table(table, datasets, shots)
    draw(table, datasets, shots, args.out, args.title)


if __name__ == "__main__":
    main()
