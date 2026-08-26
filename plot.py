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


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        # loop_index=0 은 모델 응답을 못 받은 API 실패다. 오답이 아니므로 제외한다.
        return [r for r in csv.DictReader(fh) if int(r["loop_index"]) != 0]


def detect_mode(rows):
    """escalate 모드는 샘플당 loop_index=1 행이 정확히 하나다.

    grid 모드는 shot 조건마다 loop 이 1부터 다시 시작하므로 여러 개가 나온다.
    """
    firsts = defaultdict(int)
    for r in rows:
        if int(r["loop_index"]) == 1:
            firsts[(r["dataset"], r["seed"], r["sample_id"])] += 1
    return "grid" if any(v > 1 for v in firsts.values()) else "escalate"


def escalate_summary(rows):
    """샘플별로 사다리를 몇 칸 올라갔고 어디서 풀렸는지 정리한다."""
    per_sample = {}
    for r in rows:
        key = (r["dataset"], r["seed"], r["sample_id"])
        rec = per_sample.setdefault(key, {"rungs": 0, "solved_at": None, "gt": r["gt"],
                                          "latency_s": 0.0, "input_tokens": 0})
        rec["rungs"] = max(rec["rungs"], int(r["loop_index"]))
        rec["latency_s"] += float(r["latency_ms"] or 0) / 1000.0
        rec["input_tokens"] += int(r["input_tokens"] or 0)
        if r["correct"] == "True" and rec["solved_at"] is None:
            rec["solved_at"] = int(r["shot_count"])
    grouped = defaultdict(list)
    for (dataset, _seed, _sid), rec in per_sample.items():
        grouped[dataset].append(rec)
    return grouped


def constant_baseline(recs) -> float:
    """항상 같은 답만 뱉는 예측기의 정확도(%).

    평가셋에서 가장 흔한 정답을 계속 찍었을 때의 성적이다.
    실제 성적이 이 선 근처면 모델이 과제를 푼 게 아니라 한쪽으로 쏠린 것이다.
    """
    counts = defaultdict(int)
    for r in recs:
        counts[r["gt"]] += 1
    return 100.0 * max(counts.values()) / len(recs)


def draw_escalate(grouped, ladder, out_path, title):
    datasets = sorted(grouped)
    x = list(range(len(ladder)))
    fig, axes = plt.subplots(2, 2, figsize=(12, 8.5))
    ax = axes[0][0]

    for i, dataset in enumerate(datasets):
        recs = grouped[dataset]
        ys = [100.0 * sum(1 for r in recs
                          if r["solved_at"] is not None and r["solved_at"] <= shot) / len(recs)
              for shot in ladder]
        ax.plot(x, ys, marker=MARKERS[i % len(MARKERS)], color=COLORS[i % len(COLORS)],
                linewidth=2.2, markersize=7, label=f"{dataset} (n={len(recs)})")
        for xi, yi in zip(x, ys):
            ax.annotate(f"{yi:.0f}%", (xi, yi), textcoords="offset points",
                        xytext=(0, 8), ha="center", fontsize=8,
                        color=COLORS[i % len(COLORS)])
    for i, dataset in enumerate(datasets):
        base = constant_baseline(grouped[dataset])
        ax.axhline(base, color=COLORS[i % len(COLORS)], linestyle=":", linewidth=1.4, alpha=0.7)
        ax.annotate(f"{dataset} constant-predictor baseline {base:.0f}%",
                    (len(ladder) - 1, base), textcoords="offset points", xytext=(-4, -12),
                    ha="right", fontsize=7.5, color=COLORS[i % len(COLORS)])

    ax.set_xticks(x); ax.set_xticklabels([str(s) for s in ladder])
    ax.set_xlabel("few-shot examples the agent had escalated to")
    ax.set_ylabel("samples solved so far (%)")
    ax.set_title("[MAIN] How far up the ladder each dataset needs to go",
                 fontsize=11, fontweight="bold")
    ax.set_ylim(-5, 105); ax.grid(alpha=0.3, linestyle="--"); ax.legend(fontsize=9)

    bars = [
        (axes[0][1], "escalation steps used", lambda r: r["rungs"], "steps"),
        (axes[1][0], "total latency per sample", lambda r: r["latency_s"], "seconds"),
        (axes[1][1], "input tokens per sample", lambda r: r["input_tokens"], "tokens"),
    ]
    for ax, subtitle, pick, unit in bars:
        vals = [mean([pick(r) for r in grouped[d]]) for d in datasets]
        ax.bar(range(len(datasets)), vals,
               color=[COLORS[i % len(COLORS)] for i in range(len(datasets))], width=0.5)
        for i, v in enumerate(vals):
            ax.annotate(f"{v:,.1f}", (i, v), textcoords="offset points",
                        xytext=(0, 4), ha="center", fontsize=9)
        ax.set_xticks(range(len(datasets))); ax.set_xticklabels(datasets)
        ax.set_ylabel(unit); ax.set_title(f"Average {subtitle}", fontsize=11)
        ax.grid(alpha=0.3, linestyle="--", axis="y")

    fig.suptitle(title, fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(out_path, dpi=160)
    print(f"\nsaved -> {out_path}")


def print_escalate_table(grouped, ladder):
    header = (f"{'dataset':<12}{'n':>5}{'steps':>8}{'solved%':>9}{'baseline%':>11}"
              f"{'latency_s':>11}{'in_tok':>9}")
    print(header); print("-" * len(header))
    for dataset in sorted(grouped):
        recs = grouped[dataset]
        solved = 100.0 * sum(1 for r in recs if r["solved_at"] is not None) / len(recs)
        base = constant_baseline(recs)
        print(f"{dataset:<12}{len(recs):>5}{mean([r['rungs'] for r in recs]):>8.2f}"
              f"{solved:>9.1f}{base:>11.1f}"
              f"{mean([r['latency_s'] for r in recs]):>11.2f}"
              f"{mean([r['input_tokens'] for r in recs]):>9.0f}")
        zero = [r for r in recs if r["solved_at"] == ladder[0]]
        print(f"{'':12}  {ladder[0]}-shot 만으로 푼 비율 {100.0*len(zero)/len(recs):>5.1f}% "
              f"vs 상수 예측기 {base:.1f}%  -> 차이 {100.0*len(zero)/len(recs)-base:+.1f}%p")
        counts = {shot: sum(1 for r in recs if r["solved_at"] == shot) for shot in ladder}
        unsolved = sum(1 for r in recs if r["solved_at"] is None)
        detail = "  ".join(f"{shot}-shot:{counts[shot]}" for shot in ladder)
        print(f"{'':12}  풀린 지점 -> {detail}  못 품:{unsolved}")


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

    rows = read_rows(args.results)
    if not rows:
        raise SystemExit(f"[error] {args.results} 에 집계할 행이 없다.")

    if detect_mode(rows) == "escalate":
        ladder = sorted({int(r["shot_count"]) for r in rows})
        grouped = escalate_summary(rows)
        print_escalate_table(grouped, ladder)
        draw_escalate(grouped, ladder, args.out, args.title)
        return

    grouped = load_samples(args.results)
    table = aggregate(grouped)
    datasets = sorted({d for d, _ in table})
    shots = sorted({s for _, s in table})

    print_table(table, datasets, shots)
    draw(table, datasets, shots, args.out, args.title)


if __name__ == "__main__":
    main()
