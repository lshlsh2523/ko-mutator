"""
한글 유니코드 분해·조립 공통 모듈.

KoreanGuardrail(kimchunsik03) ko_obfuscator.py의 _split/_join/_pick 설계를
따르며(Apache-2.0), pick에 후보 필터(cond) 인자를 추가함.
"""

CHO = ['ㄱ', 'ㄲ', 'ㄴ', 'ㄷ', 'ㄸ', 'ㄹ', 'ㅁ', 'ㅂ', 'ㅃ', 'ㅅ',
       'ㅆ', 'ㅇ', 'ㅈ', 'ㅉ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ']
JUNG = ['ㅏ', 'ㅐ', 'ㅑ', 'ㅒ', 'ㅓ', 'ㅔ', 'ㅕ', 'ㅖ', 'ㅗ', 'ㅘ', 'ㅙ',
        'ㅚ', 'ㅛ', 'ㅜ', 'ㅝ', 'ㅞ', 'ㅟ', 'ㅠ', 'ㅡ', 'ㅢ', 'ㅣ']
JONG = ['', 'ㄱ', 'ㄲ', 'ㄳ', 'ㄴ', 'ㄵ', 'ㄶ', 'ㄷ', 'ㄹ', 'ㄺ', 'ㄻ', 'ㄼ',
        'ㄽ', 'ㄾ', 'ㄿ', 'ㅀ', 'ㅁ', 'ㅂ', 'ㅄ', 'ㅅ', 'ㅆ', 'ㅇ', 'ㅈ',
        'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ']

BASE = 0xAC00  # '가'
LAST = 0xD7A3  # '힣'


def is_syl(ch):
    """완성형 한글 음절인지 확인."""
    return BASE <= ord(ch) <= LAST


def split(ch):
    """음절 → (초성, 중성, 종성) 인덱스. 예: '한' → (18, 0, 4)"""
    code = ord(ch) - BASE
    return code // 588, (code % 588) // 28, code % 28


def join(cho, jung, jong):
    """(초성, 중성, 종성) 인덱스 → 음절."""
    return chr(BASE + cho * 588 + jung * 28 + jong)


def pick(text, intensity, rng, cond=None):
    """
    한글 음절 위치 중 intensity 비율만큼 선택.

    rng: random.Random 객체. 호출하는 쪽에서 random.Random(seed)로 만든다.
    cond: 후보 음절을 거르는 함수 (예: 평음 초성만, 받침 있는 음절만).
          None이면 원본 KG의 _pick과 동일하게 동작한다.
    """
    idx = [i for i, ch in enumerate(text)
           if is_syl(ch) and (cond is None or cond(ch))]
    k = round(len(idx) * intensity)
    return set(rng.sample(idx, k)) if k else set()