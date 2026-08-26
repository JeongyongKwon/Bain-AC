# Few-shot LLM 데이터 처리 난이도 비교 실험

동일한 Gemini 멀티모달 모델로 **의료영상**과 **염기서열** 두 데이터셋을 처리하면서,
few-shot 예시 수를 `0 / 1 / 4 / 16` 으로 늘릴 때
**정답에 도달하기까지 필요한 Agent loop 횟수와 소요 시간**이 얼마나 줄어드는지 측정한다.

메인 지표는 **평균 loop count**, latency 와 token 은 처리 비용을 설명하는 보조 지표다.

| | 데이터셋 A | 데이터셋 B |
|---|---|---|
| 데이터 | NIH ChestX-ray14 | 염기서열 (task/데이터셋 지정) |
| 입력 | 이미지 | 텍스트 |
| task | multilabel classification | classification |
| 모델 | 동일한 Gemini 멀티모달 모델 | 동일한 Gemini 멀티모달 모델 |

---

## 파일 구조

```
README.md      이 문서
run.py         실험 러너 (데이터 로딩 → few-shot 구성 → Gemini 호출 → Agent loop → CSV append)
results.csv    호출 단위 raw execution log (별도 log 파일은 만들지 않는다)
plot.py        results.csv 집계 → chart.png
chart.png      결과 그래프 (plot.py 실행 시 생성)
```

`run.py` 는 표준 라이브러리만 사용한다. (Pillow 가 설치되어 있으면 이미지 축소에만 사용)
`plot.py` 는 `matplotlib` 이 필요하다.

```bash
pip install matplotlib          # plot.py 용
pip install pillow              # (선택) 이미지 축소로 업로드 용량 절감
export GEMINI_API_KEY=...       # 또는 GOOGLE_API_KEY
```

---

## 데이터 준비

### A. NIH ChestX-ray14

`--data-dir` 아래에 메타데이터 CSV 와 이미지가 있으면 된다. 이미지는 하위 폴더를 재귀 탐색한다.

```
chestxray14/
  Data_Entry_2017.csv          # "Image Index", "Finding Labels", "Patient ID" 컬럼 사용
  images_001/images/*.png
  images_002/images/*.png
  ...
```

few-shot pool 과 평가 샘플은 **환자 단위로 분리**해 leakage 를 막는다.

### B. 염기서열

task/데이터셋이 확정되면 아래 형태의 CSV 로만 맞춰 주면 그대로 돌아간다.

```csv
id,sequence,label
s0,ACGTACGTTTGA...,promoter
s1,GGCATTACGCAT...,non_promoter
```

```bash
--seq-csv data/seq.csv --seq-col sequence --seq-label-col label --seq-id-col id
```

- 컬럼명은 위 옵션으로 바꿀 수 있다.
- label 이 여러 개면 `,` 또는 `|` 로 구분한다 (multilabel 로 자동 인식).
- 단일 label 데이터면 few-shot 예시를 label round-robin 으로 뽑아 shot 수가 적을 때도 label 이 골고루 들어간다.
- `--seq-max-len` 으로 서열을 자를 수 있다 (기본 0 = 자르지 않음).

---

## 실행

```bash
# 두 데이터셋을 한 번에
python run.py \
  --dataset chestxray sequence \
  --model gemini-2.5-flash \
  --data-dir data/chestxray14 \
  --seq-csv data/seq.csv --seq-id-col id \
  --shots 0 1 4 16 \
  --samples 50 \
  --max-loops 5 \
  --seed 0 \
  --out results.csv

python plot.py --results results.csv --out chart.png
```

주요 옵션

| 옵션 | 설명 |
|---|---|
| `--model` | Gemini 멀티모달 모델 이름 (두 데이터셋에 동일 적용) |
| `--shots` | few-shot 예시 개수 목록 (기본 `0 1 4 16`) |
| `--samples` | 데이터셋당 평가 샘플 수 |
| `--max-loops` | 샘플당 최대 Agent loop 횟수 |
| `--pool-size` | few-shot 예시를 뽑아 두는 held-out pool 크기 (기본 16) |
| `--temperature` | 기본 1.0 |
| `--thinking-budget` | Gemini 2.5 계열의 thinking 토큰 예산 (`0` 이면 비활성) |
| `--sleep` | 호출 간 대기 (rate limit 대응) |
| `--resume` | `results.csv` 에서 이미 끝난 (조건, 샘플) 은 건너뛴다 |
| `--mock` | API 없이 파이프라인만 점검 (결과는 무의미, `model` 컬럼에 `mock:` prefix) |

동일 `--seed` 면 어떤 데이터셋/shot 조합을 실행하든 **같은 평가 샘플**이 뽑힌다.
(데이터셋별 독립 RNG + 고정 `--pool-size`) 그래서 shot 조건을 나눠 돌려도 비교가 성립한다.

few-shot 예시는 `1-shot ⊂ 4-shot ⊂ 16-shot` 이 되도록 같은 pool 의 prefix 를 쓴다.
조건 사이에서 **바뀌는 것은 shot 수뿐이다.**

---

## Agent 구조

```
Sample → Few-shot Prompt → Gemini Multimodal API → Response
       → Normalize → Rule-based Evaluator → 정답?
            ├─ YES → 종료
            └─ NO  → 동일 조건으로 다시 호출 (반복)
```

loop 안에서 **하지 않는 것**: prompt 수정 ❌ / shot 변경 ❌ / 힌트 추가 ❌ / 모델 변경 ❌ / 데이터 변경 ❌
고정된 task 를 정답이 나올 때까지 반복할 뿐이다. 이전 loop 의 오답도 프롬프트에 넣지 않는다.

- `--temperature 0` 이면 매 loop 가 같은 응답이 되어 loop 가 의미를 잃는다. 기본값 1.0 을 권장한다.
- HTTP 429/5xx/타임아웃에 대한 전송 재시도는 **loop 로 세지 않는다** (`--max-retries`).
  재시도까지 실패하면 그 호출은 오답 loop 1회로 기록되고 `predicted` 에 `ERROR: ...` 가 남는다.

---

## 정답 판정

Judge LLM 을 쓰지 않는다. 응답을 normalization 한 뒤 코드로 GT 와 비교한다 (집합 일치).

**허용되는 형식적 차이**

| 입력 | 정규화 결과 |
|---|---|
| `Pneumonia, Effusion` | `effusion, pneumonia` |
| `pneumonia, effusion` | `effusion, pneumonia` |
| `Pneumonia,  Effusion.` | `effusion, pneumonia` |
| `**Pneumonia**, Effusion` | `effusion, pneumonia` |
| `Answer: Pneumonia, Effusion` | `effusion, pneumonia` |
| `- Pneumonia\n- Effusion` | `effusion, pneumonia` |
| `Pleural_Thickening` / `Pleural Thickening` | `pleural thickening` |

대소문자, whitespace, comma spacing, 끝 punctuation, markdown/코드펜스, `Answer:` 류 prefix,
label 순서, underscore/space 차이만 흡수한다.

**허용하지 않음**: 의미가 비슷하다는 이유로 다른 label 을 정답 처리하지 않는다.
(`Pleural Effusion` ≠ `Effusion`, label 누락/추가는 오답)

---

## results.csv

API 호출이 끝날 때마다 즉시 append + flush 한다. 중간에 프로세스가 죽어도 그때까지의 실행이 남는다.
이 파일이 raw execution log 역할을 한다.

| 컬럼 | 의미 |
|---|---|
| `dataset` | `chestxray` / `sequence` |
| `task_type` | `multilabel_classification` / `singlelabel_classification` |
| `model` | 사용한 모델 이름 (`--mock` 이면 `mock:` prefix) |
| `shot_count` | few-shot 예시 개수 |
| `seed` | 샘플링 seed |
| `sample_id` | 이미지 파일명 또는 서열 ID |
| `loop_index` | 이 샘플의 몇 번째 loop 인가 (1부터) |
| `predicted` | 정규화된 예측 label 집합 (실패 시 `ERROR: ...`) |
| `gt` | 정규화된 정답 label 집합 |
| `correct` | `True` / `False` |
| `latency_ms` | 이번 호출 1회의 응답 시간 |
| `input_tokens` | 응답 `usageMetadata.promptTokenCount` (추정하지 않음) |
| `output_tokens` | `candidatesTokenCount + thoughtsTokenCount` (추정하지 않음) |
| `elapsed_s` | 이 샘플에서 여기까지 누적된 응답 시간 합 (throttle sleep 제외) |

터미널 출력

```
[12/100] dataset=chestxray shot=4 sample=00003011_000.png loop=2 correct=False | pneumonia
```

`[n/총 조건수]` 는 (데이터셋 × shot × 샘플) 조건 진행도다.

---

## 지표

`plot.py` 가 (dataset, shot_count) 단위로 집계한다.

1. **Average loop count** — 메인 지표. 샘플별 `max(loop_index)` 의 평균.
   최대 loop 안에 못 맞춘 샘플은 `max_loops` 로 잘린 값(censored)이 들어가므로 success rate 와 함께 읽어야 한다.
2. **Total latency** — 샘플별 `latency_ms` 합의 평균 (초).
3. **Input tokens** — 샘플별 input token 합의 평균. 정답 1건을 얻는 데 든 입력 비용이다.
4. **Success rate** — 최대 loop 안에 정답에 도달한 샘플 비율.

`chart.png` 는 2×2 패널이고, 좌상단이 메인 그래프(Shot vs Avg Loop Count)다.
두 데이터셋을 같은 축에 그려서 **few-shot 이 어느 데이터 유형의 처리 난도를 더 크게 낮추는지** 본다.

집계 표는 실행 시 터미널에도 출력된다.

```
dataset      shot    n  avg_loop  latency_s    in_tok  out_tok  success%
------------------------------------------------------------------------
chestxray       0   50      3.42       8.11      1420       24      62.0
chestxray       4   50      2.10       5.02      6180       21      88.0
...
```
