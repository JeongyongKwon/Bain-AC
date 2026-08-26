#!/usr/bin/env python3
"""Few-shot LLM 데이터 처리 난이도 비교 실험 (runner).

동일한 Gemini 멀티모달 모델로 두 데이터셋(의료영상 / 염기서열)을 처리하면서
few-shot 예시 수(0/1/4/16)를 늘릴 때, 정답에 도달하기까지 필요한
Agent loop 횟수와 소요 시간이 얼마나 줄어드는지 측정한다.

Agent loop 는 고정된 task 를 정답이 나올 때까지 반복하는 것 뿐이다.
(prompt/shot/hint/model/data 를 loop 중에 바꾸지 않는다.)

정답 판정은 Judge LLM 없이, normalization 후 rule-based 비교로만 한다.

의존성: 표준 라이브러리만 사용한다. (Pillow 가 설치되어 있으면 이미지 축소에 사용)
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# NIH ChestX-ray14 의 고정 label set (14 findings + No Finding)
CHEST_LABELS = [
    "Atelectasis", "Cardiomegaly", "Consolidation", "Edema", "Effusion",
    "Emphysema", "Fibrosis", "Hernia", "Infiltration", "Mass", "Nodule",
    "Pleural_Thickening", "Pneumonia", "Pneumothorax", "No Finding",
]

CSV_FIELDS = [
    "dataset", "task_type", "model", "shot_count", "seed", "sample_id",
    "loop_index", "predicted", "gt", "correct", "latency_ms",
    "input_tokens", "output_tokens", "elapsed_s",
]

IMAGE_MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp",
}


# --------------------------------------------------------------------------
# normalization / rule-based evaluation
# --------------------------------------------------------------------------

_MARKDOWN = re.compile(r"[*`#>\[\]]+")
_ANSWER_PREFIX = re.compile(
    r"^(answer|answers|label|labels|prediction|predictions|output|finding|findings)\s*[:\-]\s*",
    re.IGNORECASE,
)
_CODE_FENCE = re.compile(r"^```[a-zA-Z0-9]*\s*|\s*```$")


def normalize_label(raw: str) -> str:
    """개별 label 의 형식적 차이만 제거한다. 의미 기반 매칭은 하지 않는다."""
    s = raw.replace("_", " ")          # Pleural_Thickening == Pleural Thickening
    s = _MARKDOWN.sub("", s)
    s = s.strip().strip("\"'").strip()
    s = re.sub(r"^[\s\-•.]+", "", s)   # 리스트 bullet / 앞쪽 punctuation
    s = re.sub(r"[\s.!;:]+$", "", s)        # 불필요한 끝 punctuation
    s = re.sub(r"\s+", " ", s)
    return s.lower().strip()


def normalize_answer(text: str) -> frozenset:
    """모델 응답 문자열을 비교 가능한 label 집합으로 바꾼다."""
    t = (text or "").strip()
    t = _CODE_FENCE.sub("", t).strip()
    t = _ANSWER_PREFIX.sub("", t).strip()
    labels = {normalize_label(p) for p in re.split(r"[,\n;|/]", t)}
    return frozenset(l for l in labels if l)


def render_labels(labels) -> str:
    return ", ".join(sorted(labels))


# --------------------------------------------------------------------------
# datasets
# --------------------------------------------------------------------------

class Sample:
    """한 건의 평가 대상. kind 는 'image' 또는 'text'."""

    __slots__ = ("sample_id", "kind", "payload", "gt")

    def __init__(self, sample_id, kind, payload, gt):
        self.sample_id = sample_id
        self.kind = kind
        self.payload = payload          # image: Path / text: str
        self.gt = frozenset(gt)         # normalized label 집합


class Dataset:
    def __init__(self, name, task_type, labels, shot_pool, eval_samples, instruction):
        self.name = name
        self.task_type = task_type
        self.labels = labels
        self.shot_pool = shot_pool
        self.eval_samples = eval_samples
        self.instruction = instruction


def _index_images(root: Path) -> dict:
    """data-dir 아래의 모든 이미지 파일을 파일명 -> 경로 로 인덱싱한다."""
    index = {}
    for path in root.rglob("*"):
        if path.suffix.lower() in IMAGE_MIME and path.is_file():
            index.setdefault(path.name, path)
    return index


def load_chestxray(args, rng) -> Dataset:
    root = Path(args.data_dir).expanduser()
    meta = root / args.chest_csv if not os.path.isabs(args.chest_csv) else Path(args.chest_csv)
    if not meta.exists():
        sys.exit(f"[error] ChestX-ray14 메타데이터를 찾을 수 없다: {meta}")

    images = _index_images(root)
    if not images:
        sys.exit(f"[error] {root} 아래에서 이미지 파일을 찾지 못했다.")

    rows = []
    with open(meta, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            name = row.get("Image Index") or row.get("image_index")
            path = images.get(name)
            if path is None:
                continue
            gt = {normalize_label(x) for x in (row.get("Finding Labels") or "").split("|")}
            gt = {g for g in gt if g}
            if not gt:
                continue
            if args.drop_no_finding and gt == {"no finding"}:
                continue
            rows.append((row.get("Patient ID") or name, name, path, gt))

    if not rows:
        sys.exit("[error] 메타데이터와 매칭되는 이미지가 없다.")

    # 환자 단위로 few-shot pool 과 eval pool 을 분리한다 (leakage 방지).
    by_patient = {}
    for r in rows:
        by_patient.setdefault(r[0], []).append(r)
    patients = sorted(by_patient)
    rng.shuffle(patients)

    need = args.pool_size
    pool_rows, pool_patients = [], set()
    for pid in patients:
        if len(pool_rows) >= need:
            break
        pool_patients.add(pid)
        pool_rows.extend(by_patient[pid])

    eval_rows = [r for r in rows if r[0] not in pool_patients]
    rng.shuffle(pool_rows)
    rng.shuffle(eval_rows)

    to_sample = lambda r: Sample(r[1], "image", r[2], r[3])
    shot_pool = [to_sample(r) for r in pool_rows[: args.pool_size]]
    eval_samples = [to_sample(r) for r in eval_rows[: args.samples]]

    if len(shot_pool) < max(args.shots) or not eval_samples:
        sys.exit(f"[error] 데이터가 부족하다: shot_pool={len(shot_pool)} "
                 f"(필요 {max(args.shots)}), eval={len(eval_samples)}")

    instruction = (
        "You are a chest X-ray finding classifier for the NIH ChestX-ray14 dataset.\n"
        "Look at the frontal chest X-ray image and report every finding label that applies.\n"
        "Allowed labels (use these exact strings):\n"
        + "\n".join(f"- {l}" for l in CHEST_LABELS) + "\n"
        "Rules:\n"
        "- Output ONLY the labels, comma-separated, on a single line.\n"
        "- If there is no finding, output exactly: No Finding\n"
        "- Never output an explanation, a sentence, or markdown."
    )
    return Dataset("chestxray", "multilabel_classification", CHEST_LABELS,
                   shot_pool, eval_samples, instruction)


def load_sequence(args, rng) -> Dataset:
    path = Path(args.seq_csv).expanduser()
    if not path.exists():
        sys.exit(f"[error] 염기서열 CSV 를 찾을 수 없다: {path}")

    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for col in (args.seq_col, args.seq_label_col):
            if col not in (reader.fieldnames or []):
                sys.exit(f"[error] '{col}' 컬럼이 {path} 에 없다. 있는 컬럼: {reader.fieldnames}")
        for i, row in enumerate(reader):
            seq = (row[args.seq_col] or "").strip().upper()
            gt = {normalize_label(x) for x in re.split(r"[,|]", row[args.seq_label_col] or "")}
            gt = {g for g in gt if g}
            if not seq or not gt:
                continue
            if args.seq_max_len and len(seq) > args.seq_max_len:
                seq = seq[: args.seq_max_len]
            sid = (row.get(args.seq_id_col) if args.seq_id_col else None) or f"seq_{i:06d}"
            rows.append(Sample(sid, "text", seq, gt))

    if not rows:
        sys.exit("[error] 염기서열 CSV 에서 유효한 행을 읽지 못했다.")

    labels = sorted({l for s in rows for l in s.gt})
    rng.shuffle(rows)

    pool_rows, eval_rows = rows[: args.pool_size], rows[args.pool_size:]
    single_label = all(len(s.gt) == 1 for s in rows)
    shot_pool = _stratified_pool(pool_rows, args.pool_size, labels, rng) if single_label \
        else pool_rows
    eval_samples = eval_rows[: args.samples]

    if len(shot_pool) < max(args.shots) or not eval_samples:
        sys.exit(f"[error] 데이터가 부족하다: shot_pool={len(shot_pool)} "
                 f"(필요 {max(args.shots)}), eval={len(eval_samples)}")

    instruction = (
        "You are a nucleotide sequence classifier.\n"
        "You are given a DNA sequence written in the A/C/G/T alphabet. Classify it.\n"
        "Allowed labels (use these exact strings):\n"
        + "\n".join(f"- {l}" for l in labels) + "\n"
        "Rules:\n"
        "- Output ONLY the label(s), comma-separated, on a single line.\n"
        "- Never output an explanation, a sentence, or markdown."
    )
    task_type = "singlelabel_classification" if single_label else "multilabel_classification"
    return Dataset("sequence", task_type, labels, shot_pool, eval_samples, instruction)


def _stratified_pool(rows, k, labels, rng):
    """label 을 round-robin 으로 골라 shot pool 을 만든다.

    1-shot / 4-shot / 16-shot 이 서로의 prefix 가 되도록 순서를 고정하되,
    앞쪽에서부터 label 이 골고루 등장하게 한다.
    """
    buckets = {l: [] for l in labels}
    for s in rows:
        buckets[next(iter(s.gt))].append(s)
    for b in buckets.values():
        rng.shuffle(b)
    order, picked = list(labels), []
    rng.shuffle(order)
    while len(picked) < k:
        progressed = False
        for l in order:
            if buckets[l]:
                picked.append(buckets[l].pop())
                progressed = True
                if len(picked) == k:
                    break
        if not progressed:
            break
    return picked


# --------------------------------------------------------------------------
# prompt 구성 (Gemini REST contents 포맷)
# --------------------------------------------------------------------------

def _image_part(path: Path, max_side: int) -> dict:
    data = path.read_bytes()
    mime = IMAGE_MIME.get(path.suffix.lower(), "image/png")
    if max_side:
        data, mime = _maybe_downscale(data, mime, max_side)
    return {"inlineData": {"mimeType": mime, "data": base64.b64encode(data).decode()}}


def _maybe_downscale(data: bytes, mime: str, max_side: int):
    """Pillow 가 있으면 긴 변을 max_side 로 줄인다. 없으면 원본을 그대로 쓴다."""
    try:
        import io
        from PIL import Image
    except ImportError:
        return data, mime
    try:
        img = Image.open(io.BytesIO(data))
        if max(img.size) <= max_side:
            return data, mime
        img.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        img.convert("L" if img.mode in ("L", "1") else "RGB").save(buf, format="PNG")
        return buf.getvalue(), "image/png"
    except Exception:
        return data, mime


def sample_parts(sample: Sample, max_side: int) -> list:
    if sample.kind == "image":
        return [_image_part(sample.payload, max_side)]
    return [{"text": f"Sequence:\n{sample.payload}"}]


def build_fewshot_contents(shots, max_side: int) -> list:
    """few-shot 예시를 user/model 멀티턴으로 만든다. (조건당 한 번만 만든다)"""
    contents = []
    for s in shots:
        contents.append({"role": "user", "parts": sample_parts(s, max_side)})
        contents.append({"role": "model", "parts": [{"text": render_labels(s.gt)}]})
    return contents


# --------------------------------------------------------------------------
# Gemini 호출
# --------------------------------------------------------------------------

class CallResult:
    __slots__ = ("text", "input_tokens", "output_tokens", "latency_ms", "error")

    def __init__(self, text="", input_tokens="", output_tokens="", latency_ms=0.0, error=""):
        self.text = text
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.latency_ms = latency_ms
        self.error = error


def _flatten(text: str, limit: int) -> str:
    """CSV 한 칸에 들어가도록 에러 메시지를 한 줄로 줄인다."""
    return re.sub(r"\s+", " ", text).strip()[:limit]


def call_gemini(args, contents, instruction) -> CallResult:
    if args.mock:
        return _mock_call(args)

    body = {
        "contents": contents,
        "systemInstruction": {"parts": [{"text": instruction}]},
        "generationConfig": {
            "temperature": args.temperature,
            "maxOutputTokens": args.max_output_tokens,
        },
    }
    if args.thinking_budget is not None:
        body["generationConfig"]["thinkingConfig"] = {"thinkingBudget": args.thinking_budget}

    payload = json.dumps(body).encode("utf-8")
    url = API_URL.format(model=args.model)
    headers = {"Content-Type": "application/json", "x-goog-api-key": args.api_key}

    last_error = ""
    for attempt in range(args.max_retries + 1):
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=args.timeout) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
            latency_ms = (time.perf_counter() - started) * 1000.0
            return _parse_response(raw, latency_ms)
        except urllib.error.HTTPError as exc:
            detail = _flatten(exc.read().decode("utf-8", "replace"), 200)
            last_error = f"HTTP {exc.code}: {detail}"
            retryable = exc.code in (408, 429, 500, 502, 503, 504)
        except Exception as exc:                     # timeout / 네트워크 오류
            last_error = _flatten(f"{type(exc).__name__}: {exc}", 200)
            retryable = True
        if not retryable or attempt == args.max_retries:
            break
        time.sleep(2 ** attempt)                     # transport 재시도는 loop 로 세지 않는다

    return CallResult(latency_ms=0.0, error=last_error)


def _parse_response(raw: dict, latency_ms: float) -> CallResult:
    usage = raw.get("usageMetadata", {})
    in_tok = usage.get("promptTokenCount", "")
    out_tok = usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0)
    candidates = raw.get("candidates") or []
    if not candidates:
        reason = (raw.get("promptFeedback") or {}).get("blockReason", "no candidate")
        return CallResult("", in_tok, out_tok, latency_ms, f"blocked: {reason}")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts)
    error = "" if text.strip() else f"empty text (finishReason={candidates[0].get('finishReason')})"
    return CallResult(text, in_tok, out_tok, latency_ms, error)


def _mock_call(args) -> CallResult:
    """파이프라인 점검용. label set 에서 균일 랜덤으로 뽑으므로 shot 효과를 흉내내지 않는다."""
    time.sleep(0.01)
    pool = args._mock_labels
    n = random.randint(1, 2)
    return CallResult(", ".join(random.sample(pool, min(n, len(pool)))), 0, 0, 10.0, "")


# --------------------------------------------------------------------------
# Agent loop
# --------------------------------------------------------------------------

def run_condition(args, dataset, shot_count, writer, fh, counter, total):
    args._mock_labels = [normalize_label(l) for l in dataset.labels]
    prefix = build_fewshot_contents(dataset.shot_pool[:shot_count], args.image_max_side)

    for sample in dataset.eval_samples:
        counter[0] += 1
        key = (dataset.name, args.model_label, str(shot_count), str(args.seed), sample.sample_id)
        if key in args._done:
            print(f"[{counter[0]}/{total}] skip (resume) dataset={dataset.name} "
                  f"shot={shot_count} sample={sample.sample_id}")
            continue

        contents = prefix + [{"role": "user", "parts": sample_parts(sample, args.image_max_side)}]
        elapsed_s = 0.0

        for loop_index in range(1, args.max_loops + 1):
            result = call_gemini(args, contents, dataset.instruction)
            elapsed_s += result.latency_ms / 1000.0

            if result.error and not result.text.strip():
                predicted, correct = f"ERROR: {result.error}", False
            else:
                pred = normalize_answer(result.text)
                predicted, correct = render_labels(pred), pred == sample.gt

            writer.writerow({
                "dataset": dataset.name,
                "task_type": dataset.task_type,
                "model": args.model_label,
                "shot_count": shot_count,
                "seed": args.seed,
                "sample_id": sample.sample_id,
                "loop_index": loop_index,
                "predicted": predicted,
                "gt": render_labels(sample.gt),
                "correct": correct,
                "latency_ms": round(result.latency_ms, 1),
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "elapsed_s": round(elapsed_s, 3),
            })
            fh.flush()                              # 중간에 죽어도 여기까지는 남는다

            print(f"[{counter[0]}/{total}] dataset={dataset.name} shot={shot_count} "
                  f"sample={sample.sample_id} loop={loop_index} correct={correct}"
                  + (f" | {predicted[:60]}" if not correct else ""))

            if correct:
                break
            if args.sleep:
                time.sleep(args.sleep)


def load_done(path: Path, max_loops: int) -> set:
    """이미 종료(정답 도달 또는 max loop 소진)된 (조건, 샘플) 키를 모은다."""
    done = set()
    if not path.exists():
        return done
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            key = (row["dataset"], row["model"], row["shot_count"], row["seed"], row["sample_id"])
            if row["correct"] == "True" or int(row["loop_index"]) >= max_loops:
                done.add(key)
    return done


# --------------------------------------------------------------------------

def load_dotenv(path: str) -> str:
    """.env 파일이 있으면 환경변수로 읽어들인다.

    이미 셸에 설정된 환경변수는 덮어쓰지 않는다 (셸 > .env 우선순위).
    실행 디렉터리에 없으면 run.py 옆도 찾아본다.
    """
    candidates = [Path(path), Path(__file__).resolve().parent / path]
    for candidate in candidates:
        if not candidate.is_file():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            line = line[7:] if line.startswith("export ") else line
            key, sep, value = line.partition("=")
            if sep:
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
        return str(candidate)
    return ""


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dataset", nargs="+", required=True, choices=["chestxray", "sequence"],
                   help="실행할 데이터셋")
    p.add_argument("--model", default="gemini-2.5-flash", help="Gemini 멀티모달 모델 이름")
    p.add_argument("--shots", type=int, nargs="+", default=[0, 1, 4, 16], help="few-shot 예시 개수")
    p.add_argument("--samples", type=int, default=25, help="데이터셋당 평가 샘플 수")
    p.add_argument("--max-loops", type=int, default=5, help="샘플당 최대 Agent loop 횟수")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--pool-size", type=int, default=16,
                   help="few-shot 예시를 뽑아 둘 held-out pool 크기. "
                        "--shots 를 나눠 실행해도 eval 샘플이 같도록 고정값을 쓴다")
    p.add_argument("--out", default="results.csv")
    p.add_argument("--resume", action="store_true", help="results.csv 에 이미 끝난 샘플은 건너뛴다")

    p.add_argument("--data-dir", help="ChestX-ray14 루트 (메타데이터 + 이미지)")
    p.add_argument("--chest-csv", default="Data_Entry_2017.csv")
    p.add_argument("--drop-no-finding", action="store_true", help="'No Finding' 샘플 제외")
    p.add_argument("--image-max-side", type=int, default=512,
                   help="이미지 긴 변 축소 (Pillow 있을 때만 적용, 0=원본)")

    p.add_argument("--seq-csv", help="염기서열 CSV 경로")
    p.add_argument("--seq-col", default="sequence")
    p.add_argument("--seq-label-col", default="label")
    p.add_argument("--seq-id-col", default=None)
    p.add_argument("--seq-max-len", type=int, default=0, help="염기서열 최대 길이 (0=자르지 않음)")

    p.add_argument("--temperature", type=float, default=1.0,
                   help="0 이면 매 loop 가 같은 응답이 되어 loop 가 의미를 잃는다")
    p.add_argument("--max-output-tokens", type=int, default=256)
    p.add_argument("--thinking-budget", type=int, default=None,
                   help="Gemini 2.5 계열 thinking 토큰 예산 (0=비활성)")
    p.add_argument("--timeout", type=float, default=120.0)
    p.add_argument("--max-retries", type=int, default=3, help="전송 실패 재시도 (loop 로 세지 않음)")
    p.add_argument("--sleep", type=float, default=0.0, help="호출 사이 대기 (rate limit 용)")
    p.add_argument("--mock", action="store_true", help="API 없이 파이프라인만 점검 (결과는 무의미)")
    p.add_argument("--env-file", default=".env", help="API 키를 읽을 .env 경로")

    args = p.parse_args(argv)
    if max(args.shots) > args.pool_size:
        p.error(f"--pool-size({args.pool_size}) 가 최대 shot({max(args.shots)}) 보다 작다")
    if "chestxray" in args.dataset and not args.data_dir:
        p.error("--dataset chestxray 에는 --data-dir 이 필요하다")
    if "sequence" in args.dataset and not args.seq_csv:
        p.error("--dataset sequence 에는 --seq-csv 가 필요하다")
    args.model_label = ("mock:" if args.mock else "") + args.model
    args.env_file_used = load_dotenv(args.env_file)
    args.api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    if not args.mock and not args.api_key:
        p.error("API 키가 없다. 다음 중 하나로 넣어라:\n"
                "  export GEMINI_API_KEY=...            (셸 환경변수)\n"
                f"  echo 'GEMINI_API_KEY=...' > {args.env_file}   (.env 파일, git 에 커밋되지 않음)")
    return args


def main(argv=None):
    args = parse_args(argv)
    args.shots = sorted(set(args.shots))
    random.seed(args.seed)

    # 데이터셋마다 독립적인 RNG 를 쓴다.
    # -> 어떤 데이터셋을 함께 실행하든 같은 seed 면 같은 샘플이 뽑힌다.
    datasets = []
    if "chestxray" in args.dataset:
        datasets.append(load_chestxray(args, random.Random(f"{args.seed}:chestxray")))
    if "sequence" in args.dataset:
        datasets.append(load_sequence(args, random.Random(f"{args.seed}:sequence")))

    out_path = Path(args.out)
    args._done = load_done(out_path, args.max_loops) if args.resume else set()

    total = sum(len(d.eval_samples) for d in datasets) * len(args.shots)
    if args.env_file_used:
        print(f"env loaded from {args.env_file_used}")
    print(f"model={args.model} shots={args.shots} max_loops={args.max_loops} "
          f"seed={args.seed} conditions={total}")
    for d in datasets:
        print(f"  - {d.name}: eval={len(d.eval_samples)} shot_pool={len(d.shot_pool)} "
              f"labels={len(d.labels)} task={d.task_type}")

    is_new = not out_path.exists() or out_path.stat().st_size == 0
    counter = [0]
    started = time.perf_counter()
    with open(out_path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        if is_new:
            writer.writeheader()
            fh.flush()
        try:
            for dataset in datasets:
                for shot in args.shots:
                    run_condition(args, dataset, shot, writer, fh, counter, total)
        except KeyboardInterrupt:
            print("\n[interrupted] 지금까지의 결과는 CSV 에 남아 있다.")

    print(f"done in {time.perf_counter() - started:.1f}s -> {out_path}")


if __name__ == "__main__":
    main()
