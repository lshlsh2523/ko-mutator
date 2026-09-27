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
7. 연음이 이어지는 경우를 모두 적용 (원본은 한 번 적용 후 다음 글자를 건너뛰어
   '먹었어요 → 머겄어요'가 됨. 수정 후 '머거써요')
8. 연음에서 홑받침 ㅎ은 옮기지 않고 탈락 (좋아요 → 조아요. 원본은 '조하요')
9. 역연음(머거 → 먹어) 대체 동작은 이식하지 않음 (강도 체계와 맞지 않음)
10. 음절 섞기(원본 11 배열교란): 원본은 공백으로 나눈 어절 전체를 섞지만, 여기서는
    한글 음절이 이어진 구간 단위로 섞음(공백·문장부호·숫자·영문을 넘지 않음).
    강도 = 섞을 구간 비율, 선택된 구간은 다를 때까지 다시 섞음,
    3음절 구간은 원본처럼 2·3번째 교환(끝 음절이 바뀜)하되 원본의 70% 확률은 미적용
11. 기호 삽입(원본 13 표현추가): 원본 기호 집합(하트·별·원형·도형·괄호·구두점·감정 표현·
    장식·특수 문자) 전체에서 숫자 '1'만 제외(canary 7359와 섞임 방지). 원본은 종류별로
    확률 삽입·단어 감싸기를 하지만, 여기서는 선택된 음절 뒤에 기호 1개를 넣고 강도 비율로 선택
12. 로마자 표기: 국어의 로마자 표기법 자모 대응을 쓰되 발음 변화는 반영하지 않고
    음절마다 글자 그대로 옮김(신라 → sinra, 없이 → eopi). 받침은 표기법의 대표음
    (ㄱ·ㄲ·ㅋ·ㄳ·ㄺ → k, ㄷ·ㅅ·ㅆ·ㅈ·ㅊ·ㅌ·ㅎ → t, ㅂ·ㅍ·ㄿ·ㅄ → p, ㄼ·ㄽ·ㄾ·ㅀ → l,
    ㄵ·ㄶ → n, ㄻ → m). 강도 = 로마자로 바꿀 음절 비율
13. 자모 도상 대치(원본 5-2): 초성만 모양이 닮은 문자로 바꾼다. 원본의 모음·복합 처리는
    버그가 있어 제외. 후보에서 쌍자음을 홑자음 둘로 푸는 항목(ㄲ → ㄱㄱ, 자모 분해와 겹침)과
    한글 음절로 바꾸는 항목(ㄹ → 근, 야민정음에 가까움)은 제외. 원본의 ㄹ → ㉢(동그라미 ㄷ)은
    ㉣으로 바로잡음. 숫자 후보(ㄱ → 7, ㄹ → 2, ㅇ → 0)는 쓰되, 앞 글자가 숫자인 음절에서는
    숫자와 숫자 닮은꼴(O·○·Z 등)을 쓰지 않음(7359 등이 다른 수로 읽히는 것 방지)
14. 연음 사전의 ㄳ 항목: 원본은 ㄳ 전체를 넘겨 ㄱ이 사라짐(넋이 → 너기). 같은 사전의
    ㄽ·ㅄ 처리에 맞춰 ㄱ을 남기고 ㅅ을 된소리로 넘김(넋이 → 넉씨)

범위: 연음은 '받침+초성 ㅇ' 사전 치환(기본·연속·ㅎ 탈락)만. 형태소 경계 예외
(맛없다), 구개음화(굳이) 등은 처리하지 않는다. 로마자는 표기법의 자모 대응만 쓴다.
"""
import json
import random
import unicodedata
from pathlib import Path

from .core import CHO, JUNG, JONG, is_syl, split, join, pick, candidates

RULES_DIR = Path(__file__).parent / 'rules'


def _load(name):
    return json.loads((RULES_DIR / name).read_text(encoding='utf-8'))


_REPLACE = _load('replace.json')
_ICONIC = _load('iconic_dictionary.json')

VOWEL_MAP = _REPLACE['vowel_replace_map']        # ㅐ↔ㅔ, ㅚ·ㅙ·ㅞ 교체
REAL_SOUND = _REPLACE['real_sound_map']          # 받침 → 대표음 (음절 끝소리 규칙)
CONTINUE = dict(_REPLACE['continue_sound_map'])  # 받침+ㅇ → 연음
CONTINUE['ㅎᴥㅇ'] = 'ᴥㅇ'                         # 달라진 점 8: 홑받침 ㅎ은 탈락
CONTINUE['ㄳᴥㅇ'] = 'ㄱᴥㅆ'                        # 달라진 점 14: ㄳ은 ㄱ을 남기고 ㅅ을 넘김 (넋이 → 넉씨)
YAMIN = _ICONIC['yamin_dict']                    # 자형 유사 치환 (멍→댕 등)

# 대표음이 같은 받침끼리 묶기 (예: ㄷ → [ㅅ, ㅈ, ㅊ, ㅌ, ㅎ, ㅆ, ...])
_SAME_SOUND = {}
for _jong, _rep in REAL_SOUND.items():
    _SAME_SOUND.setdefault(_rep, []).append(_jong)


def _vowel_ok(ch):
    return JUNG[split(ch)[1]] in VOWEL_MAP


def _final_ok(ch):
    t = split(ch)[2]
    return t != 0 and JONG[t] in REAL_SOUND and len(_SAME_SOUND[REAL_SOUND[JONG[t]]]) > 1


def _yamin_ok(ch):
    return ch in YAMIN


def vowel_replace(text, intensity=1.0, seed=0):
    """KOTOX 1-3 모음 대치: 시스템 → 시스탬 (ㅐ↔ㅔ, ㅚ·ㅙ·ㅞ 교체)"""
    rng = random.Random(seed)
    sel = pick(text, intensity, rng, cond=_vowel_ok)
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
    sel = pick(text, intensity, rng, cond=_final_ok)
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


def _continue_candidates(text):
    """연음 후보: 받침이 있고(ㅇ 제외) 다음 글자 초성이 ㅇ인 위치"""
    cand = []
    for i in range(len(text) - 1):
        a, b = text[i], text[i + 1]
        if not (is_syl(a) and is_syl(b)):
            continue
        ta, cb = split(a)[2], split(b)[0]
        if ta != 0 and JONG[ta] != 'ㅇ' and CHO[cb] == 'ㅇ' and (JONG[ta] + 'ᴥㅇ') in CONTINUE:
            cand.append(i)
    return cand


def continue_sound(text, intensity=1.0, seed=0):
    """KOTOX 3-1 연음: 받침이 다음 초성(ㅇ)으로 넘어감 (먹을 → 머글, 먹었어요 → 머거써요)"""
    rng = random.Random(seed)
    cand = _continue_candidates(text)
    k = round(len(cand) * intensity)
    sel = set(rng.sample(cand, k)) if k else set()
    syl = {i: list(split(ch)) for i, ch in enumerate(text) if is_syl(ch)}
    for i in sorted(sel):
        new_t, new_c = CONTINUE[JONG[syl[i][2]] + 'ᴥㅇ'].split('ᴥ')
        syl[i][2] = JONG.index(new_t)
        syl[i + 1][0] = CHO.index(new_c)
    return ''.join(join(*syl[i]) if i in syl else ch for i, ch in enumerate(text))


def yamin_swap(text, intensity=1.0, seed=0):
    """KOTOX 5-1 자형 유사 치환(야민정음): 멍멍이 → 댕댕이"""
    rng = random.Random(seed)
    sel = pick(text, intensity, rng, cond=_yamin_ok)
    return ''.join(rng.choice(YAMIN[ch]) if i in sel else ch
                   for i, ch in enumerate(text))


def _hangul_runs(text):
    """한글 음절이 끊기지 않고 이어진 구간들의 위치 목록 (공백·문장부호·숫자·영문에서 끊김)"""
    runs, cur = [], []
    for i, ch in enumerate(text):
        if is_syl(ch):
            cur.append(i)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return runs


def _shuffle_ok(text, pos):
    """섞을 수 있는 구간인지: 3음절 이상이고, 섞었을 때 반드시 달라질 수 있어야 함"""
    if len(pos) < 3:
        return False
    if len(pos) == 3:
        return text[pos[1]] != text[pos[2]]
    return len({text[p] for p in pos[1:-1]}) >= 2


def _shuffle_candidates(text):
    return [r for r, pos in enumerate(_hangul_runs(text)) if _shuffle_ok(text, pos)]


def syllable_shuffle(text, intensity=1.0, seed=0):
    """KOTOX 11 음절 섞기: 한글 구간의 첫·끝 음절은 두고 가운데 순서를 섞음 (무시하고 → 무하시고).
    3음절 구간은 원본처럼 2·3번째를 맞바꾸므로 끝 음절이 바뀐다 (알려줘 → 알줘려)."""
    rng = random.Random(seed)
    words = _hangul_runs(text)
    cand = _shuffle_candidates(text)
    k = round(len(cand) * intensity)
    sel = sorted(rng.sample(cand, k)) if k else []
    chars = list(text)
    for w in sel:
        pos = words[w]
        if len(pos) == 3:
            a, b = pos[1], pos[2]
            chars[a], chars[b] = chars[b], chars[a]
            continue
        mid = pos[1:-1]
        orig = [text[p] for p in mid]
        new = orig[:]
        while new == orig:
            rng.shuffle(new)
        for p, ch in zip(mid, new):
            chars[p] = ch
    return ''.join(chars)



# 국어의 로마자 표기법 자모 대응 (발음 변화 미반영, 달라진 점 12)
_ROM_CHO = {'ㄱ': 'g', 'ㄲ': 'kk', 'ㄴ': 'n', 'ㄷ': 'd', 'ㄸ': 'tt', 'ㄹ': 'r',
            'ㅁ': 'm', 'ㅂ': 'b', 'ㅃ': 'pp', 'ㅅ': 's', 'ㅆ': 'ss', 'ㅇ': '',
            'ㅈ': 'j', 'ㅉ': 'jj', 'ㅊ': 'ch', 'ㅋ': 'k', 'ㅌ': 't', 'ㅍ': 'p', 'ㅎ': 'h'}
_ROM_JUNG = {'ㅏ': 'a', 'ㅐ': 'ae', 'ㅑ': 'ya', 'ㅒ': 'yae', 'ㅓ': 'eo', 'ㅔ': 'e',
             'ㅕ': 'yeo', 'ㅖ': 'ye', 'ㅗ': 'o', 'ㅘ': 'wa', 'ㅙ': 'wae', 'ㅚ': 'oe',
             'ㅛ': 'yo', 'ㅜ': 'u', 'ㅝ': 'wo', 'ㅞ': 'we', 'ㅟ': 'wi', 'ㅠ': 'yu',
             'ㅡ': 'eu', 'ㅢ': 'ui', 'ㅣ': 'i'}
# 받침은 표기법대로 대표음으로 적는다 (ㄱ·ㄲ·ㅋ → k, ㄷ·ㅅ·ㅆ·ㅈ·ㅊ·ㅌ·ㅎ → t, ㅂ·ㅍ → p, 겹받침 포함)
_ROM_JONG = {0: '', 1: 'k', 2: 'k', 3: 'k', 4: 'n', 5: 'n', 6: 'n', 7: 't', 8: 'l',
             9: 'k', 10: 'm', 11: 'l', 12: 'l', 13: 'l', 14: 'p', 15: 'l', 16: 'm',
             17: 'p', 18: 'p', 19: 't', 20: 't', 21: 'ng', 22: 't', 23: 't', 24: 'k',
             25: 't', 26: 'p', 27: 't'}


def _romanize_syl(ch):
    c, j, t = split(ch)
    jong = _ROM_JONG.get(t, '')
    return _ROM_CHO[CHO[c]] + _ROM_JUNG.get(JUNG[j], '') + jong


def _rom_ok(ch):
    c, j, t = split(ch)
    return JUNG[j] in _ROM_JUNG and t in _ROM_JONG


def romanize(text, intensity=1.0, seed=0):
    """로마자 표기: 선택된 음절을 국어의 로마자 표기법으로 옮김 (제한 → jehan)"""
    sel = pick(text, intensity, random.Random(seed), cond=_rom_ok)
    return ''.join(_romanize_syl(ch) if i in sel else ch for i, ch in enumerate(text))


# 기호 삽입: KOTOX 원본 SymbolAddition의 기호 집합 전체에서 숫자 '1'만 제외 (달라진 점 11)
_SYMBOLS = (
    ['♡', '♥', '♤', '♧']                                                     # 하트
    + ['★', '☆', '✦', '✧', '✩', '✪']                                        # 별
    + ['○', '●', '◎', '◯', '◈', '◉', '◊']                                   # 원형
    + ['◇', '◆', '□', '■', '▲', '△', '▼', '▽']                              # 도형
    + ['【', '】', '《', '》', '「', '」', '『', '』', '∥', '〃']            # 괄호
    + ['‥', '…', '、', '。', '．', '¿', '？', '!']                           # 구두점 ('1' 제외)
    + ['ε♡з', 'ε♥з', 'T^T', '∏-∏', '≥ㅇ≤', '≥ㅅ≤', '≥ㅂ≤', '≥ㅁ≤', '≥ㅃ≤']  # 감정 표현
    + ['━', '─', '┃', '┗', '┣', '┓', '┫', '┛', '┻', '┳']                    # 장식
    + ['¸', 'º', '°', '˛', '˚', '¯', '´', '`', '¨', 'ˆ', '˜', '˙']          # 특수 문자
)


def symbol_insert(text, intensity=1.0, seed=0):
    """기호 삽입: 선택된 음절 뒤에 기호 1개를 넣음 (무시 → 무★시)"""
    rng = random.Random(seed)
    sel = pick(text, intensity, rng, cond=None)
    out = []
    for i, ch in enumerate(text):
        out.append(ch)
        if i in sel:
            out.append(rng.choice(_SYMBOLS))
    return ''.join(out)


# 자모 도상 대치: 초성만 모양이 닮은 문자로 (달라진 점 13). 사전 생성: komutator/rules/build_iconic_cho.py
_ICONIC_CHO = _load('iconic_cho.json')   # 초성 → 닮은꼴 문자 (숫자 포함, 두 글자·한글 제외)


_DIGIT_LIKE = set('OoΘθ○◯◎ZzlIΙ|')


def _digit_like(ch):
    """숫자이거나 숫자처럼 읽힐 수 있는 문자 (0 ↔ O·○, 2 ↔ Z, 1 ↔ l·I)"""
    return unicodedata.normalize('NFKC', ch).isdigit() or ch in _DIGIT_LIKE


def _iconic_ok(ch):
    return CHO[split(ch)[0]] in _ICONIC_CHO


def iconic_swap(text, intensity=1.0, seed=0):
    """자모 도상 대치: 초성을 닮은꼴 문자로 바꿈 (강 → 勹ㅏㅇ 형태로 음절이 풀림)"""
    rng = random.Random(seed)
    sel = pick(text, intensity, rng, cond=_iconic_ok)
    out = []
    for i, ch in enumerate(text):
        if i in sel:
            c, j, t = split(ch)
            opts = _ICONIC_CHO[CHO[c]]
            # 바뀐 문자는 음절 맨 앞에 오므로 왼쪽 이웃만 본다. 숫자 옆에는 숫자·숫자 닮은꼴을 쓰지 않음
            if i > 0 and unicodedata.normalize('NFKC', text[i - 1]).isdigit():
                opts = [o for o in opts if not _digit_like(o)]
            sym = rng.choice(opts)
            out.append(sym + JUNG[j] + (JONG[t] if t else ''))
        else:
            out.append(ch)
    return ''.join(out)


TRANSFORMS = {
    'vowel_replace': vowel_replace,
    'final_replace': final_replace,
    'continue_sound': continue_sound,
    'yamin_swap': yamin_swap,
    'syllable_shuffle': syllable_shuffle,
    'symbol_insert': symbol_insert,
    'romanize': romanize,
    'iconic_swap': iconic_swap,
}

CANDIDATES = {
    'vowel_replace': lambda t: candidates(t, _vowel_ok),
    'final_replace': lambda t: candidates(t, _final_ok),
    'continue_sound': _continue_candidates,
    'yamin_swap': lambda t: candidates(t, _yamin_ok),
    'syllable_shuffle': _shuffle_candidates,
    'symbol_insert': lambda t: candidates(t),
    'romanize': lambda t: candidates(t, _rom_ok),
    'iconic_swap': lambda t: candidates(t, _iconic_ok),
}