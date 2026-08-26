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
.gitignore     .env / data/ 를 커밋에서 제외
```

데이터셋과 API 키는 레포에 넣지 않는다. 로컬에 `data/` 와 `.env` 로 두면 된다.

`run.py` 는 표준 라이브러리만 사용한다. (Pillow 가 설치되어 있으면 이미지 축소에만 사용)
`plot.py` 는 `matplotlib` 이 필요하다.

```bash
pip install matplotlib          # plot.py 용
pip install pillow              # (선택) 이미지 축소로 업로드 용량 절감
```

---

## API 키 (env)

`GEMINI_API_KEY` (없으면 `GOOGLE_API_KEY`) 하나만 있으면 된다.
[Google AI Studio](https://aistudio.google.com/apikey) 에서 발급한다.

**방법 1 — 셸 환경변수** (그 터미널 세션에서만 유효)

```bash
export GEMINI_API_KEY=AIza...
python run.py --dataset ...
```

**방법 2 — `.env` 파일** (권장. 레포 루트에 두면 `run.py` 가 자동으로 읽는다)

```bash
echo 'GEMINI_API_KEY=AIza...' > .env
```

```
Bain-AC/
  run.py
  .env        <- 여기. .gitignore 에 있어서 커밋되지 않는다
```

- 경로를 바꾸려면 `--env-file path/to/.env`
- 실행 디렉터리에 없으면 `run.py` 옆도 찾아본다
- **셸 환경변수가 `.env` 보다 우선한다** (이미 export 된 값은 덮어쓰지 않는다)
- 키가 없으면 실행 즉시 에러로 알려준다. `--mock` 은 키 없이 돌아간다

---

## 데이터 준비

데이터는 레포에 넣지 않는다 (`data/` 는 `.gitignore` 에 있다). 로컬에 받아서 경로만 넘긴다.

### A. NIH ChestX-ray14

받는 곳 (둘 다 같은 데이터다)

| 출처 | 방법 |
|---|---|
| NIH 공식 (Box) | <https://nihcc.app.box.com/v/ChestXray-NIHCC> — `images_001.tar.gz` ~ `images_012.tar.gz` + `Data_Entry_2017_v2020.csv`. 공식 `batch_download_zips.py` 스크립트도 같이 올라와 있다 |
| Kaggle 미러 | `kaggle datasets download -d nih-chest-xrays/data` (전체 다운로드). 특정 파일만 받으려면 `-f <파일명>` |

전체는 112,120장 / 약 42GB 다. **전부 받을 필요 없다.**
`run.py` 는 실제로 존재하는 이미지 파일만 인덱싱하고 메타데이터에서 파일이 없는 행은 건너뛴다.
그래서 **샤드 하나(약 4~5천 장)만 받아도** `--samples 50` 규모 실험은 그대로 돌아간다.

```
data/chestxray14/
  Data_Entry_2017.csv          # "Image Index", "Finding Labels", "Patient ID" 컬럼만 사용
  images_001/images/*.png      # 하위 폴더는 재귀 탐색하므로 구조는 자유
```

```bash
--data-dir data/chestxray14
# 메타데이터 파일명이 다르면 (예: 공식 Box 판)
--data-dir data/chestxray14 --chest-csv Data_Entry_2017_v2020.csv
```

- few-shot pool 과 평가 샘플은 **환자 단위로 분리**해 leakage 를 막는다.
- `No Finding` 이 전체의 절반 이상이라 그대로 쓰면 "No Finding 만 찍어도 맞는" 샘플이 많아진다.
  난이도를 올리려면 `--drop-no-finding` 을 쓴다.
- 원본이 1024×1024 PNG 라 16-shot 이면 업로드가 커진다. Pillow 를 깔면
  `--image-max-side` (기본 512) 로 줄여서 보낸다.

### B. 염기서열

**아직 확정 안 됨.** 아래 중 하나를 고르면 되고, 어느 걸 골라도 코드 수정은 필요 없다.
CSV 형식만 맞추면 된다.

| 후보 | task | 특징 |
|---|---|---|
| Genomic Benchmarks `human_nontata_promoters` | promoter / non-promoter 2분류 | 251bp, 약 36k. `pip install genomic-benchmarks` 또는 HuggingFace |
| GUE (DNABERT-2 벤치마크) | promoter, splice site, TF binding 등 | 이미 `sequence,label` CSV 로 배포되어 거의 그대로 쓸 수 있다 |
| UCI Splice-junction | EI / IE / N 3분류 | 60bp, 3,190건. 가장 가볍게 시작하기 좋다 |

추천: **길이가 짧은 2~3분류**부터. 서열이 길면 16-shot 프롬프트의 input token 이 급격히 늘어
"loop 가 줄어드는 효과"와 "프롬프트가 비싸지는 효과"가 섞인다.

> ⚠️ **label 이름은 `0` / `1` 같은 숫자를 쓰지 말고 의미 있는 문자열로 바꿔라.**
> 라벨이 `0`/`1` 이면 0-shot 조건에서 모델이 어느 쪽이 promoter 인지 알 방법이 없어
> 사실상 찍기가 되고, few-shot 효과가 과대평가된다.
> `promoter` / `non_promoter` 처럼 바꿔서 0-shot 도 의미를 갖게 해야 비교가 성립한다.

준비되면 아래 형태의 CSV 로만 맞춰 주면 된다.

```csv
id,sequence,label
s0,ACGTACGTTTGA...,promoter
s1,GGCATTACGCAT...,non_promoter
```

```
data/seq.csv
```

```bash
--seq-csv data/seq.csv --seq-col sequence --seq-label-col label --seq-id-col id
```

- 컬럼명은 위 옵션으로 바꿀 수 있다.
- label 이 여러 개면 `,` 또는 `|` 로 구분한다 (multilabel 로 자동 인식).
- 단일 label 데이터면 few-shot 예시를 label round-robin 으로 뽑아 shot 수가 적을 때도 label 이 골고루 들어간다.
- `--seq-max-len` 으로 서열을 자를 수 있다 (기본 0 = 자르지 않음).
- 프롬프트의 "이 서열이 무엇인가" 문장은 **알파벳을 보고 자동으로 정해진다.**
  ACGT/U/N 이 95% 넘으면 DNA 로, 아니면 단백질(아미노산)로 설명한다.
  대부분의 서열에 `|` 가 있으면 두 부분이 구분자로 나뉜다는 문장이 붙는다.
  직접 쓰고 싶으면 `--seq-desc "..."` 로 덮어쓴다.
  (데이터가 단백질인데 "A/C/G/T alphabet" 이라고 말하면 모델에 거짓 정보를 주게 된다)

---

## 실행

```bash
# 두 데이터셋을 한 번에
python run.py \
  --dataset chestxray sequence \
  --model gemini-3.5-flash-lite \
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
| `--model` | 멀티모달 모델 이름 (두 데이터셋에 동일 적용, 기본 `gemini-3.5-flash-lite`) |
| `--provider` | `auto`(기본) / `gemini` / `anthropic`. auto 는 모델 이름으로 판단한다 |
| `--thinking` | `auto`(모델 기본값) / `off`(비용·지연 감소) |
| `--mode` | `grid`(기본) = shot 조건별로 같은 프롬프트 반복 / `escalate` = 정답까지 shot 을 올려가며 재시도 |
| `--shots` | few-shot 예시 개수 목록 (기본 `0 1 4 16`). escalate 모드에선 사다리가 된다 |
| `--samples` | 데이터셋당 평가 샘플 수 |
| `--max-loops` | 샘플당 최대 Agent loop 횟수 |
| `--pool-size` | few-shot 예시를 뽑아 두는 held-out pool 크기 (기본 16) |
| `--temperature` | 기본 1.0 |
| `--thinking-budget` | Gemini 2.5 계열의 thinking 토큰 예산 (`0` 이면 비활성) |
| `--rpm` | 분당 호출 수 상한. 무료 tier RPM 에 맞춰 자동 간격 (0=무제한) |
| `--sleep` | 호출 사이 최소 대기 (초) |
| `--max-api-failures` | 연속 API 실패가 이만큼 쌓이면 그 샘플을 포기 (기본 5) |
| `--resume` | `results.csv` 에서 이미 끝난 (조건, 샘플) 은 건너뛴다 |
| `--mock` | API 없이 파이프라인만 점검 (결과는 무의미, `model` 컬럼에 `mock:` prefix) |
| `--env-file` | API 키를 읽을 `.env` 경로 (기본 `.env`) |
| `--show-prompt` | API 호출 없이 **실제로 전송될 프롬프트만 출력**하고 종료 |

동일 `--seed` 면 어떤 데이터셋/shot 조합을 실행하든 **같은 평가 샘플**이 뽑힌다.
(데이터셋별 독립 RNG + 고정 `--pool-size`) 그래서 shot 조건을 나눠 돌려도 비교가 성립한다.

few-shot 예시는 `1-shot ⊂ 4-shot ⊂ 16-shot` 이 되도록 같은 pool 의 prefix 를 쓴다.
조건 사이에서 **바뀌는 것은 shot 수뿐이다.**

---

## 프롬프트 확인

실제로 어떤 프롬프트가 나가는지는 API 호출 없이 그대로 볼 수 있다 (키도 필요 없다).

```bash
python run.py --dataset chestxray --data-dir data/chestxray14 --shots 0 4 --show-prompt
python run.py --dataset sequence  --seq-csv data/seq.csv --shots 0 4 --show-prompt
```

프롬프트는 `run.py` 안에 있다.

- 두 데이터셋이 **완전히 같은 틀**(`INSTRUCTION_TEMPLATE`)을 쓴다.
  다른 것은 "입력이 무엇인지" 한 문장뿐이다.
  한쪽에만 데이터셋 이름이나 도메인 힌트를 주면 그 자체가 교란 변수가 되기 때문이다.
- few-shot 배치: `build_fewshot_contents()` — user/model 멀티턴으로 넣는다

few-shot 예시의 답은 **데이터셋 원본 표기 그대로** 보여준다 (`Atelectasis`, `Pleural_Thickening`).
정규화는 채점할 때만 하고, 예시가 소문자로 나가면 "정확히 이 문자열을 쓰라"는
지시와 모순돼서 모델 행동에 영향을 준다.

### 다른 백엔드

기본은 Gemini 다. `--model claude-...` 를 주면 Anthropic 백엔드로 자동 전환된다
(`pip install anthropic`, `ANTHROPIC_API_KEY` 필요).
설계상 "두 데이터셋에 같은 멀티모달 모델" 이기만 하면 되므로 모델 종류는 바꿔도 실험이 성립한다.

> ⚠️ Anthropic 경로는 **아직 실제 호출로 검증하지 않았다** (키가 없어서 변환 로직만 확인).
> 실제로 쓰기 전에 소량으로 먼저 돌려봐야 한다.
> Claude 최신 모델은 `temperature` 가 제거되어 있어서 `--temperature` 는 무시된다.

---

## Agent 구조

```
Sample → Few-shot Prompt → Gemini Multimodal API → Response
       → Normalize → Rule-based Evaluator → 정답?
            ├─ YES → 종료
            └─ NO  → 동일 조건으로 다시 호출 (반복)
```

### 두 가지 모드

**`--mode grid` (기본)** — 원래 설계다. shot 조건마다 별도로 돌리고, 그 안에서는
완전히 같은 프롬프트를 정답이 나올 때까지 반복한다.

> 실측: 오답 뒤 재호출에서 **85% 가 직전과 같은 답**을 냈다. 입력이 같으면 출력도 거의 같다.
> 그래서 이 모드의 loop count 는 사실상 `1 + (max_loops-1) x 오답률` 이고,
> 정확도의 단조 변환에 가깝다. 독립적인 난이도 지표로 읽으면 안 된다.

**`--mode escalate`** — 정답이 나올 때까지 few-shot 예시 수를 사다리로 올린다
(`0 -> 1 -> 4 -> 16`). 매 재시도의 프롬프트가 실제로 달라지므로 loop 이 일을 한다.
`loop_index` 는 사다리의 몇 번째 칸인지, `shot_count` 는 그 칸의 예시 수를 뜻한다.
지표는 "이 샘플을 풀려면 몇 shot 이 필요했나" 가 된다.

grid 모드는 전수 격자라 escalate 의 결과를 사후에 유도할 수 있다(상위 집합).
escalate 모드는 맞히는 즉시 멈춰서 호출 수가 적다.

loop 안에서 **하지 않는 것**: prompt 수정 ❌ / shot 변경 ❌ / 힌트 추가 ❌ / 모델 변경 ❌ / 데이터 변경 ❌
고정된 task 를 정답이 나올 때까지 반복할 뿐이다. 이전 loop 의 오답도 프롬프트에 넣지 않는다.

- `--temperature 0` 이면 매 loop 가 같은 응답이 되어 loop 가 의미를 잃는다. 기본값 1.0 을 권장한다.
- HTTP 429/5xx/타임아웃은 **loop 로 세지 않는다.** 모델이 답을 준 게 아니라 호출 자체가 실패한 것이므로
  오답으로 처리하면 loop count 지표가 오염된다.
  - 먼저 `--max-retries` 만큼 재시도한다 (429 응답이 알려주는 `retryDelay` 를 존중, 최대 60초).
  - 그래도 실패하면 `loop_index=0`, `predicted=API_FAILURE: ...` 로 **기록만 남기고** loop 예산을 쓰지 않는다.
  - 연속 실패가 `--max-api-failures`(기본 5) 를 넘으면 그 샘플을 포기한다.
  - `plot.py` 는 `loop_index=0` 행을 집계에서 제외한다.
- 모델이 응답은 했는데 내용이 비었거나 차단된 경우는 **오답 loop 1회**로 센다 (`ERROR: ...`).

### rate limit (무료 tier)

무료 tier 한도는 **모델별로 다르다.** 실측값:

| 모델 | RPM | RPD (하루) | 이미지 입력 |
|---|---|---|---|
| `gemini-3.5-flash-lite` | 15 | **500** | O |
| `gemini-3.1-flash-lite` | 15 | **500** | O |
| `gemini-3.6-flash` | 5 | 20 | O |
| `gemini-3.5-flash` / `3.7-flash` | 5 | 20 | O |
| `gemini-2.5-*` | - | - | 404 (신규 사용자 불가) |

flash 계열은 **하루 20회**라 실험이 불가능하다. **flash-lite (500 RPD)** 를 쓴다.

```bash
--model gemini-3.5-flash-lite --rpm 12
```

RPM 보다 **TPM(분당 250K) 이 먼저 걸린다.** 실측으로 이미지 1장 ≈ 1,090 input token 이라
16-shot 이면 호출당 약 18,700 token 이 나간다. RPM 15 를 다 쓰면 280K TPM 으로 한도를 넘는다.
그래서 `--rpm 12` 정도로 두는 게 안전하다. 넘더라도 429 의 `retryDelay` 를 존중해 대기했다가
이어서 돌기 때문에 데이터가 깨지지는 않고 느려지기만 한다.

실측 (flash-lite, 32x32 이미지 기준):

| 조건 | input tokens / call |
|---|---|
| 0-shot (이미지 1장) | 1,248 |
| 2-shot (이미지 3장) | 3,437 |
| 16-shot (이미지 17장, 추정) | 약 18,700 |

`--rpm` 은 정답/오답과 무관하게 **매 호출 앞에서** 간격을 지킨다.
(현재 한도는 <https://ai.dev/rate-limit> 에서 확인)

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
| `loop_index` | 이 샘플의 몇 번째 loop 인가 (1부터). **`0` 은 API 실패**(429/타임아웃) 기록이며 loop 로 세지 않는다 |
| `predicted` | 정규화된 예측 label 집합. 모델이 이상하게 답한 경우 `ERROR: ...`, API 자체가 실패한 경우 `API_FAILURE: ...` |
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

`loop_index=0` (API 실패) 행은 집계에서 빠진다.

1. **Average loop count** — 메인 지표. 샘플별 `max(loop_index)` 의 평균.
   최대 loop 안에 못 맞춘 샘플은 `max_loops` 로 잘린 값(censored)이 들어가므로 success rate 와 함께 읽어야 한다.
2. **Total latency** — 샘플별 `latency_ms` 합의 평균 (초).
3. **Input tokens** — 샘플별 input token 합의 평균. 정답 1건을 얻는 데 든 입력 비용이다.
4. **Success rate** — 최대 loop 안에 정답에 도달한 샘플 비율.

### 상수 예측기 기준선

escalate 집계는 **항상 같은 답만 뱉는 예측기의 정확도**를 같이 보고한다.
평가셋에서 가장 흔한 정답을 계속 찍었을 때의 성적이다.

이진 과제에서는 이게 50% 근처라, 기준선 없이 "정확도 56%" 만 보면
모델이 과제를 푼 것처럼 오독하게 된다. 실측 사례:

```
0-shot 만으로 푼 비율  56.0%  vs  상수 예측기  52.0%  -> 차이 +4.0%p
```

실제로 그 실행에서 모델은 0-shot 25건 중 21건을 같은 라벨로 답했다.
기준선과의 차이가 작으면 "few-shot 이 필요 없다" 가 아니라
"아직 과제를 풀고 있지 않다" 로 읽어야 한다.

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
