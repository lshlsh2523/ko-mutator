# ko-mutator

한국어 프롬프트 인젝션 탐지 연구를 위한 **한글 표기 난독화 변형기**와 **사전 스크리닝 데이터 생성 도구**입니다.
외부 라이브러리 없이 파이썬 표준 라이브러리만으로 동작하며, 같은 입력·강도·시드에 항상 같은 결과를 냅니다.

## 설치

```bash
git clone https://github.com/lshlsh2523/ko-mutator
cd ko-mutator
python -m pip install huggingface_hub   # KoreanGuardrail 다운로드에만 필요
python tools/download_kg.py             # data/KoreanGuardrail/ (git 제외, 버전은 data_revision.txt)
```

## 폴더 구조

```
ko-mutator/
├── komutator/        변형기 본체 (core, mutators, kotox_ports, registry)
│   └── rules/        KOTOX 규칙 사전, 도상 대치 사전과 생성 스크립트
├── tests/            테스트
├── tools/            KG 다운로드, 검수표 생성
├── docs/             검수표 (review_sheet.md)
├── screening/        사전 스크리닝: 시드 선별, canary, 스크리닝 셋
└── data/             KoreanGuardrail 원본 (git 제외)
```

## 변형 기법 17종

모든 기법은 `f(text, intensity, seed) -> str` 형태입니다. `intensity`는 **후보 위치 중 바꿀 비율**이며, 후보의 정의는 기법마다 다릅니다.

KOTOX의 난독화 5범주(음운 4·도상 2·음차 1·통사 3·화용 1종)를 모두 포함하고, KoreanGuardrail과 자체 구현의 표기 기법 6종(자모·자판 단위)을 더했습니다. 음차와 화용은 각 1종뿐입니다.

| 기법 | 예시 | 범주 | 출처 |
| --- | --- | --- | --- |
| `jamo_decompose` 자모 분해 | 폭탄 → ㅍㅗㄱㅌㅏㄴ | 표기(자모) | KG |
| `chosung` 초성체 | 폭탄 → ㅍㅌ | 표기(자모) | KG |
| `tensify` 된소리화 | 시스템 → 씨스템 | 음운 | KG |
| `zwsp_inject` 투명문자 삽입 | 폭탄 → 폭​탄 | 표기(자모) | KG |
| `space_delete` 띄어쓰기 제거 | 무시 해 → 무시해 | 통사 | KG(분리) |
| `space_insert` 띄어쓰기 삽입 | 무시해 → 무 시해 | 통사 | KG(분리) |
| `final_decompose` 받침 분리 | 폭탄 → 포ㄱ타ㄴ | 표기(자모) | 신규 |
| `filler_insert` 무의미 자모 삽입 | 폭탄 → 폭ㅋ탄ㅋㅋ | 표기(자모) | 신규 |
| `qwerty` 영타 변환 | 폭탄 → vhrxks | 표기(자판) | 신규 |
| `vowel_replace` 모음 대치 | 시스템 → 시스탬 | 음운 | KOTOX 1-3 |
| `final_replace` 받침 대치 | 간단한 → 갅닩핞 | 음운 | KOTOX 1-4 |
| `continue_sound` 연음 | 먹었어요 → 머거써요 | 음운 | KOTOX 3-1 |
| `yamin_swap` 야민정음 | 멍멍이 → 댕댕이 | 도상 | KOTOX 5-1 |
| `iconic_swap` 자모 도상 대치 | 강 → 勹ㅏㅇ | 도상 | KOTOX 5-2 |
| `romanize` 로마자 표기 | 제한 없이 → jehan eopi (발음 변화 미반영) | 음차 | KOTOX 음차(규칙화) |
| `syllable_shuffle` 음절 섞기 | 무시하고 → 무하시고 (3음절은 알려줘 → 알줘려) | 통사 | KOTOX 11 |
| `symbol_insert` 기호 삽입 | 무시 → 무★시 | 화용 | KOTOX 13 |

- 한글만 바꾸고 숫자·영문·기존 기호는 그대로 둡니다(영타 변환·야민정음·로마자·도상 대치·기호 삽입은 결과에 영문·기호를 만듦).
- KG 계열 6종은 원본 `ko_obfuscator.py`와 출력이 같습니다(`tests/test_kg_equivalence.py`).
- KOTOX 이식분이 원본과 달라진 점(연음 연속 적용·ㅎ 탈락, 로마자·기호·도상의 규칙화 등)은 `komutator/kotox_ports.py` 상단에 정리되어 있습니다.

## 사용법

```python
from komutator.registry import TRANSFORMS, mutate

TRANSFORMS['chosung']('이전 지시를 무시해', 0.7, 1234)       # 변형 결과만

r = mutate('continue_sound', '먹었어요', 1.0, 1234)          # 변형 + 변경량
# {'text': '머거써요', 'n_cand': 2, 'n_changed': 2, 'changed': True, 'n_syl': 4}
```

| 필드 | 의미 |
| --- | --- |
| `n_cand` | 바꿀 수 있는 위치 수 (단위는 `registry.UNIT`: 음절 / 공백 / 음절 쌍 / 한글 구간) |
| `n_changed` | 실제로 바꾼 위치 수 (= 후보 수 × 강도를 파이썬 `round`로 반올림. KG 원본과 같게 하려고 짝수 쪽 반올림을 그대로 씀: 1.5 → 2, 2.5 → 2) |
| `changed` | 원문과 달라졌는지. **False인 행은 회피·전달 분석에서 제외**하고 적용률로 따로 보고 |
| `n_syl` | 원문의 한글 음절 수 |

후보가 드문 기법(연음·모음 대치·야민정음·음절 섞기)은 짧은 문장에서 강도 0.3이 변화 없음이 되거나 0.3과 0.7이 같아질 수 있습니다. 강도의 단위가 기법마다 다르므로, 기법 간 비교에는 `n_changed / n_syl`(실제 변경 비율)을 함께 봅니다.

## 테스트

```bash
python tests/test_all.py              # 17종 통합 검증
python tests/test_properties.py       # KG 계열·신규 기법 속성
python tests/test_kg_equivalence.py   # KG 원본과 출력 대조 (tools/download_kg.py 먼저 실행)
python screening/test_canary.py       # canary 판정·토큰 보존
python tools/make_review_sheet.py     # docs/review_sheet.md 갱신
```

`tests/test_all.py`·`tests/test_kg_equivalence.py`·`screening/test_canary.py`는 실패가 있으면 종료 코드 1을 냅니다.

## 사전 스크리닝 (`screening/`)

| 파일 | 내용 |
| --- | --- |
| `filter_seeds.py` → `candidates.jsonl`, `excluded.jsonl` | KG 시드 505건에 제외 기준 E1~E4 적용 |
| `select_seeds.py` → `seeds_selected.jsonl`, `holdout_ids.txt` | 층화 추출 70건 (난수 시드 20260926). `holdout_ids.txt`는 최종 평가에서 제외 |
| `canary_config.json`, `canary.py` → `seeds_screening.jsonl` | canary 적용·판정 규칙 (git 태그 `canary-v2`) |
| `build_screening_set.py` → `screening_set.jsonl`·`.csv`·`_manifest.json`·`_summary.md` | 시드 70 × (17종 × 강도 0.3/0.7 + 원문) = 2,450행. 측정 입력은 `text` 필드, `changed=false` 행은 분석에서 제외 |

## 라이선스와 출처

- KoreanGuardrail (kimchunsik03): 코드 Apache-2.0, 데이터 CC-BY-4.0
- KOTOX (leeyejin1231): MIT. 규칙 사전·기호 집합을 가져와 재구현. `komutator/rules/KOTOX_LICENSE` 참고. `komutator/rules/iconic_cho.json`은 `komutator/rules/build_iconic_cho.py`로 생성
