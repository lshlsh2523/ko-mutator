"""KOTOX 난독화 규칙 이식.

원본: https://github.com/leeyejin1231/KOTOX (MIT License, Copyright (c) 2025 Yejin Lee)
커밋 a01c9174390720e4bb83e5c311a4ca71ba5fffcb (2026-05-28)

원본과 달라진 점:
1. hgtk 의존성을 core.py의 split/join으로 대체 (외부 의존성 제거)
2. 전역 random 대신 seed로 만든 지역 난수 생성기 사용 (재현성 확보)
3. 문장 전체가 아니라 intensity 비율만큼만 적용 (우리 강도 체계에 맞춤)
4. 규칙 사전을 UTF-8 명시로 로드
5. 받침 대치에서 원래 받침을 다시 고르지 않도록 제외
6. 연음에서 ㅇ 받침은 제외 (원본 사전의 'ㅇᴥㅇ' 항목 미사용)
"""
import json
import random
from pathlib import Path

from core import CHO, JUNG, JONG, is_syl, split, join, pick

RULES_DIR = Path(__file__).parent / 'rules'


def _load(name):
    return json.loads((RULES_DIR / name).read_text(encoding='utf-8'))


_REPLACE = _load('replace.json')
_ICONIC = _load('iconic_dictionary.json')

VOWEL_MAP = _REPLACE['vowel_replace_map']        # ㅐ↔ㅔ, ㅚ·ㅙ·ㅞ 교체
REAL_SOUND = _REPLACE['real_sound_map']          # 받침 → 대표음 (음절 끝소리 규칙)
CONTINUE = _REPLACE['continue_sound_map']        # 받침+ㅇ → 연음
YAMIN = _ICONIC['yamin_dict']                    # 자형 유사 치환 (멍→댕 등)

# 대표음이 같은 받침끼리 묶기 (예: ㄷ → [ㅅ, ㅈ, ㅊ, ㅌ, ㅎ, ㅆ, ...])
_SAME_SOUND = {}
for _jong, _rep in REAL_SOUND.items():
    _SAME_SOUND.setdefault(_rep, []).append(_jong)


def vowel_replace(text, intensity=1.0, seed=0):
    """KOTOX 1-3 모음 대치: 시스템 → 시스탬 (ㅐ↔ㅔ, ㅚ·ㅙ·ㅞ 교체)"""
    rng = random.Random(seed)
    sel = pick(text, intensity, rng, cond=lambda ch: JUNG[split(ch)[1]] in VOWEL_MAP)
    out = []
    for i, ch in enumerate(text):
        if i in sel:
            c, j, t = split(ch)
            new_j = rng.choice(VOWEL_MAP[JUNG[j]])
            out.append(join(c, JUNG.index(new_j), t))
        else:
            out.append(ch)
    return ''.join(out)


def final_replace(text, intensity=1.0, seed=0):
    """KOTOX 1-4 받침 대치: 같은 대표음을 내는 다른 받침으로 (오늘 → 오늜)"""
    rng = random.Random(seed)

    def ok(ch):
        t = split(ch)[2]
        return t != 0 and JONG[t] in REAL_SOUND and len(_SAME_SOUND[REAL_SOUND[JONG[t]]]) > 1

    sel = pick(text, intensity, rng, cond=ok)
    out = []
    for i, ch in enumerate(text):
        if i in sel:
            c, j, t = split(ch)
            options = [x for x in _SAME_SOUND[REAL_SOUND[JONG[t]]] if x != JONG[t]]
            new_t = rng.choice(options)
            out.append(join(c, j, JONG.index(new_t)))
        else:
            out.append(ch)
    return ''.join(out)


def continue_sound(text, intensity=1.0, seed=0):
    """KOTOX 3-1 연음: 받침이 다음 음절 초성(ㅇ)으로 넘어감 (먹을 → 머글)"""
    rng = random.Random(seed)
    # 후보: 받침이 있고 다음 글자의 초성이 'ㅇ'인 위치
    cand = []
    for i in range(len(text) - 1):
        a, b = text[i], text[i + 1]
        if not (is_syl(a) and is_syl(b)):
            continue
        ca, ja, ta = split(a)
        cb, jb, tb = split(b)
        # ㅇ 받침은 뒤 모음으로 넘어가지 않으므로(강아지 → [강아지]) 제외
        if ta != 0 and JONG[ta] != 'ㅇ' and CHO[cb] == 'ㅇ' and (JONG[ta] + 'ᴥㅇ') in CONTINUE:
            cand.append(i)
    k = round(len(cand) * intensity)
    sel = set(rng.sample(cand, k)) if k else set()

    out = []
    skip = False
    for i, ch in enumerate(text):
        if skip:
            skip = False
            continue
        if i in sel:
            c, j, t = split(ch)
            nc, nj, nt = split(text[i + 1])
            new_t, new_c = CONTINUE[JONG[t] + 'ᴥㅇ'].split('ᴥ')
            out.append(join(c, j, JONG.index(new_t)))
            out.append(join(CHO.index(new_c), nj, nt))
            skip = True
        else:
            out.append(ch)
    return ''.join(out)


def yamin_swap(text, intensity=1.0, seed=0):
    """KOTOX 5-1 자형 유사 치환(야민정음): 멍멍이 → 댕댕이"""
    rng = random.Random(seed)
    sel = pick(text, intensity, rng, cond=lambda ch: ch in YAMIN)
    return ''.join(rng.choice(YAMIN[ch]) if i in sel else ch
                   for i, ch in enumerate(text))


TRANSFORMS = {
    'vowel_replace': vowel_replace,
    'final_replace': final_replace,
    'continue_sound': continue_sound,
    'yamin_swap': yamin_swap,
}