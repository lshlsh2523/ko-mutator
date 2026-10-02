# Step 1 분류기 데이터 v1 (2026-10-03)

한국어 프롬프트 인젝션 탐지 Step 1 분류기(KoELECTRA·mDeBERTa) 학습·평가용 데이터입니다.
영어 공개 데이터를 DeepL로 번역한 문장과 한국어 원본 문장으로 구성됩니다.

> **배포 금지**: xTRam1 데이터(라이선스 미표기)가 포함되어 있어 팀 내부에서만 사용합니다.

## 1. 파일

| 파일 | 건수 | 공격 / 정상 | 용도 |
| --- | --- | --- | --- |
| `train.jsonl` | 4,809 | 2,401 / 2,408 | 학습 (길이 보정용 복제 373건 포함) |
| `valid.jsonl` | 604 | 300 / 304 | 검증 (best model 선택) |
| `test.jsonl` | 604 | 300 / 304 | 평가 (본 결과) |
| `kg_test.jsonl` | 172 | 108 / 64 | 보조 평가 (KoreanGuardrail) |
| `kg_test_meta.jsonl` | 172 | | `kg_test`의 KG 원본 정보 (category, subtype 등) |

### 필드

| 필드 | 내용 | 예시 |
| --- | --- | --- |
| `id` | 고유 ID (`출처_번호`, 복제 행은 `_dup1`, KG는 `kg_` 접두) | `xtram1_00123` |
| `text` | 한국어 입력 문장 | |
| `label` | 0 = 정상, 1 = 공격 | `1` |
| `source` | 출처 | `xtram1` |

- 파일 안 순서는 무작위입니다.
- `kg_test_meta`의 `kg_label`, `kg_source`는 KG 원본 값입니다. 평가에는 `kg_test.jsonl`의 `label`을 사용합니다.

## 2. 출처

| 출처 (`source`) | 라벨 | 원본 데이터 | 라이선스 | 번역 |
| --- | --- | --- | --- | --- |
| `gandalf` | 공격 | Lakera/gandalf_ignore_instructions | MIT | O |
| `xtram1` | 공격·정상 | xTRam1/safe-guard-prompt-injection | 미표기 (배포 금지) | O |
| `hhrlhf` | 정상 | Anthropic/hh-rlhf (helpful-base, 첫 사용자 발화) | MIT | O |
| `promptschat` | 정상 | fka/awesome-chatgpt-prompts | CC0-1.0 | O |
| `koalpaca` | 정상 | beomi/KoAlpaca-RealQA (질문) | CC-BY-SA-4.0 | X (한국어 원본) |
| `koreanguardrail` | 공격·정상 | KoreanGuardrail (비템플릿 시드) | CC-BY | X (Claude 생성 후 검수) |

- 원본 버전(커밋 해시)은 ko-mutator 레포 `step1_data/data_revision.txt`에 있습니다.
- deepset/prompt-injections는 라벨 기준이 다른 데이터와 충돌해 제외했습니다.

## 3. 만든 과정

1. **정리**: 인코딩 깨짐 수리, 영문 원문 300자 초과 제외, 라벨 충돌·중복 제거, 정상 데이터 중 탈옥 표현이 있는 문장 제외, xTRam1 공격의 같은 틀은 최대 75건
2. **정상 추출 (짝 맞추기)**: 공격 출처마다 같은 수의 정상을 같은 길이 분포로 추출
    - xTRam1 공격 ↔ xTRam1 정상
    - gandalf 공격 ↔ hh-rlhf + prompts.chat + KoAlpaca(1/3)
    - password, ignore 등 공격에 자주 나오는 단어가 들어간 정상 문장은 우선 포함
3. **번역**: DeepL API (EN→KO, `preserve_formatting=True`, deepl-python 1.32.0)
    - 공격 의미가 사라진 203건은 용어집(prompt → 프롬프트)과 맥락("사용자가 AI 챗봇에게 보내는 메시지")을 지정해 재번역
4. **번역 후 정리**: 정리 함수 재적용, 번역 후 같은 문장이 된 31건 제거, KoAlpaca 중 인젝션·비밀 정보 요구 질문 제외
5. **분할**: 아래 4절

스크립트는 ko-mutator 레포 `step1_data/`에 있고, 시드는 모두 `20261002`입니다.

## 4. 분할

- **그룹 분할**: 영어 원문 단어가 60% 이상 겹치는 공격끼리 묶고(Jaccard ≥ 0.6), 같은 그룹은 한 분할에만 넣었습니다. 30건 이상인 큰 그룹 6개는 train에 고정했습니다. → test 공격은 train에서 본 적 없는 표현입니다.
- **층화**: (라벨, 출처) 칸마다 train : valid : test ≈ 8 : 1 : 1

| 칸 (라벨_출처) | train | valid | test |
| --- | --- | --- | --- |
| 공격_gandalf | 785 | 98 | 97 |
| 공격_xtram1 | 1,616 | 202 | 203 |
| 정상_xtram1 | 1,630 | 204 | 204 |
| 정상_hhrlhf | 468 | 59 | 59 |
| 정상_koalpaca | 265 | 33 | 33 |
| 정상_promptschat | 59 | 8 | 8 |

(train은 길이 보정 전 기준)

### 번역 / 한국어 원본 비율 (정상 기준, 공격은 전부 번역)

| 분할 | 번역 | 한국어 원본 (KoAlpaca) |
| --- | --- | --- |
| train | 2,157 (89.1%) | 265 (10.9%) |
| valid | 271 (89.1%) | 33 (10.9%) |
| test | 271 (89.1%) | 33 (10.9%) |
| kg_test | 0 | 172 (100%, Claude 생성 한국어) |

### train 길이 보정

- xTRam1 짝만, 한국어 길이 10개 구간별로 정상을 줄이거나 복제해 공격의 길이 분포에 맞췄습니다. (복제 373건, `_dup1`)
- xTRam1 짝 길이 KS: train 0.153 → 0.035 / valid 0.164 / test 0.165 (valid·test는 보정 안 함)

### kg_test

- KoreanGuardrail 505건 중 템플릿이 아닌 249건에서 스크리닝 시드 70건(T1 `holdout_ids.txt`)과 외국어 공격 7건을 뺀 172건
- 학습 데이터와 겹치는 문장 0건

## 5. 사용 시 주의

- **증강(mutator)에는 `_dup`을 뺀 train 원본만 시드로 사용**해야 합니다. 복제 행까지 쓰면 같은 정상의 변형이 두 배로 생깁니다.
- valid·test의 xTRam1 짝은 길이 분포 차이(KS 0.16)가 남아 있으므로 **길이 구간별 성능**도 함께 봅니다.
- `max_length` 128 기준 토큰 초과: KoELECTRA 0건, mDeBERTa 5건(0.08%, 문장 끝 몇 어절만 잘림)

## 6. 한계

- **범위**: 영문 원문 300자 이하의 짧은 단일 프롬프트만 다룹니다. 긴 탈옥 프롬프트와 긴 문서 속에 숨긴 인젝션은 포함하지 않습니다.
- **말투**: 공격은 "당신은 ~입니다", "~하십시오" 같은 번역투 명령문이 많고, 반말은 대부분 정상(KoAlpaca)에 있습니다. 문장 끝만 보고도 라벨을 어느 정도 맞힐 수 있습니다. (최대 63~68%, 기준 50%)
- **키워드**: "무시", "비밀번호" 등은 공격에 훨씬 많이 나옵니다. 공격의 실제 내용이라 없애지 않았고, 오탐은 `kg_test`의 정상(hard negative)으로 확인합니다.
- **한국어 원본**: 공격은 전부 번역문입니다. 실제 사람이 쓴 한국어 공격에 대한 성능은 확인되지 않았습니다.
- **출처**: gandalf에는 공격만 있어 gandalf 문체 자체가 공격 신호가 될 수 있습니다.
- **근접 중복**: 번역 후 비슷해진 정상 문장이 분할 간에 일부 남아 있습니다. (train-test 한국어 3-gram 유사도 0.8 이상 6쌍)