"""
한글 표기 난독화 mutator 모음.

- KG 계열: KoreanGuardrail(kimchunsik03) ko_obfuscator.py 기반 (Apache-2.0)
- 신규: 선행 연구(Yu et al. 2024, Cho & Kim 2021)의 기법을 직접 구현

모든 함수는 f(text, intensity=1.0, seed=0) -> str 형태다.
"""
import random

from core import CHO, JUNG, JONG, split, join, pick

ZWSP = '\u200b'
# 평음 초성 인덱스 → 경음 초성 인덱스 (ㄱ→ㄲ, ㄷ→ㄸ, ㅂ→ㅃ, ㅅ→ㅆ, ㅈ→ㅉ)
TENSE_IDX = {0: 1, 3: 4, 7: 8, 9: 10, 12: 13}


# ---------------------------------------------------------------
# KG 계열 (원본과 동일한 출력)
# ---------------------------------------------------------------
def jamo_decompose(text, intensity=1.0, seed=0):
    """자모 분해: 안녕 → ㅇㅏㄴㄴㅕㅇ"""
    sel = pick(text, intensity, random.Random(seed))
    out = []
    for i, ch in enumerate(text):
        if i in sel:
            c, j, t = split(ch)
            out.append(CHO[c] + JUNG[j] + JONG[t])
        else:
            out.append(ch)
    return ''.join(out)


def chosung(text, intensity=1.0, seed=0):
    """초성체: 안녕하세요 → ㅇㄴㅎㅅㅇ"""
    sel = pick(text, intensity, random.Random(seed))
    return ''.join(CHO[split(ch)[0]] if i in sel else ch
                   for i, ch in enumerate(text))


def tensify(text, intensity=1.0, seed=0):
    """된소리화: 시스템 → 씨스템 (평음 초성이 있는 음절만 후보)"""
    sel = pick(text, intensity, random.Random(seed),
               cond=lambda ch: split(ch)[0] in TENSE_IDX)
    out = []
    for i, ch in enumerate(text):
        if i in sel:
            c, j, t = split(ch)
            out.append(join(TENSE_IDX[c], j, t))
        else:
            out.append(ch)
    return ''.join(out)


def zwsp_inject(text, intensity=1.0, seed=0):
    """제로폭 공백 삽입: 선택된 음절 뒤에 U+200B (눈에 안 보임)"""
    sel = pick(text, intensity, random.Random(seed))
    out = []
    for i, ch in enumerate(text):
        out.append(ch)
        if i in sel:
            out.append(ZWSP)
    return ''.join(out)


# 원본 break_spacing은 강도에 따라 '제거'와 '삽입'이 갈리는 설계라,
# 강도별로 따로 쓸 수 있게 두 기법으로 분리했다.
def space_delete(text, intensity=1.0, seed=0):
    """띄어쓰기 제거: 공백 중 intensity 비율만큼 제거 (1.0 = 원본 break_spacing 1.0)"""
    spaces = [i for i, ch in enumerate(text) if ch == ' ']
    k = round(len(spaces) * intensity)
    rng = random.Random(seed)
    removed = set(rng.sample(spaces, k)) if k else set()
    return ''.join(ch for i, ch in enumerate(text) if i not in removed)


def space_insert(text, intensity=1.0, seed=0):
    """띄어쓰기 삽입: 선택된 음절 뒤에 공백 (= 원본 break_spacing의 강도 0.5 미만 동작)"""
    sel = pick(text, intensity, random.Random(seed))
    out = []
    for i, ch in enumerate(text):
        out.append(ch)
        if i in sel:
            out.append(' ')
    return ''.join(out)


# ---------------------------------------------------------------
# 신규 구현
# ---------------------------------------------------------------
def final_decompose(text, intensity=1.0, seed=0):
    """받침만 분리: 폭탄 → 포ㄱ타ㄴ (Yu et al. 2024 DECOMPOSE_final)"""
    sel = pick(text, intensity, random.Random(seed),
               cond=lambda ch: split(ch)[2] != 0)
    out = []
    for i, ch in enumerate(text):
        if i in sel:
            c, j, t = split(ch)
            out.append(join(c, j, 0) + JONG[t])
        else:
            out.append(ch)
    return ''.join(out)


FILLERS = ['ㅋ', 'ㅇ', 'ㅎ']


def filler_insert(text, intensity=1.0, seed=0):
    """무의미 자모 삽입: 틀딱 → 틀ㅋㅋ딱 (Yu et al. 2024 INSERT_zz)"""
    rng = random.Random(seed)
    sel = pick(text, intensity, rng)
    out = []
    for i, ch in enumerate(text):
        out.append(ch)
        if i in sel:
            out.append(rng.choice(FILLERS) * rng.randint(1, 2))
    return ''.join(out)


# 두벌식 자판 → QWERTY 키
Q_CHO = {'ㄱ': 'r', 'ㄲ': 'R', 'ㄴ': 's', 'ㄷ': 'e', 'ㄸ': 'E', 'ㄹ': 'f',
         'ㅁ': 'a', 'ㅂ': 'q', 'ㅃ': 'Q', 'ㅅ': 't', 'ㅆ': 'T', 'ㅇ': 'd',
         'ㅈ': 'w', 'ㅉ': 'W', 'ㅊ': 'c', 'ㅋ': 'z', 'ㅌ': 'x', 'ㅍ': 'v',
         'ㅎ': 'g'}
Q_JUNG = {'ㅏ': 'k', 'ㅐ': 'o', 'ㅑ': 'i', 'ㅒ': 'O', 'ㅓ': 'j', 'ㅔ': 'p',
          'ㅕ': 'u', 'ㅖ': 'P', 'ㅗ': 'h', 'ㅘ': 'hk', 'ㅙ': 'ho', 'ㅚ': 'hl',
          'ㅛ': 'y', 'ㅜ': 'n', 'ㅝ': 'nj', 'ㅞ': 'np', 'ㅟ': 'nl', 'ㅠ': 'b',
          'ㅡ': 'm', 'ㅢ': 'ml', 'ㅣ': 'l'}
Q_JONG = {'': '', 'ㄱ': 'r', 'ㄲ': 'R', 'ㄳ': 'rt', 'ㄴ': 's', 'ㄵ': 'sw',
          'ㄶ': 'sg', 'ㄷ': 'e', 'ㄹ': 'f', 'ㄺ': 'fr', 'ㄻ': 'fa', 'ㄼ': 'fq',
          'ㄽ': 'ft', 'ㄾ': 'fx', 'ㄿ': 'fv', 'ㅀ': 'fg', 'ㅁ': 'a', 'ㅂ': 'q',
          'ㅄ': 'qt', 'ㅅ': 't', 'ㅆ': 'T', 'ㅇ': 'd', 'ㅈ': 'w', 'ㅊ': 'c',
          'ㅋ': 'z', 'ㅌ': 'x', 'ㅍ': 'v', 'ㅎ': 'g'}


def qwerty(text, intensity=1.0, seed=0):
    """영문 자판 치환: 폭탄 → vhrxks (Cho & Kim 2021)"""
    sel = pick(text, intensity, random.Random(seed))
    out = []
    for i, ch in enumerate(text):
        if i in sel:
            c, j, t = split(ch)
            out.append(Q_CHO[CHO[c]] + Q_JUNG[JUNG[j]] + Q_JONG[JONG[t]])
        else:
            out.append(ch)
    return ''.join(out)


TRANSFORMS = {
    'jamo_decompose': jamo_decompose,
    'chosung': chosung,
    'tensify': tensify,
    'zwsp_inject': zwsp_inject,
    'space_delete': space_delete,
    'space_insert': space_insert,
    'final_decompose': final_decompose,
    'filler_insert': filler_insert,
    'qwerty': qwerty,
}