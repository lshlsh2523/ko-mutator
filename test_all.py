"""13종 mutator 통합 검증.

1. 공통 속성: 재현성, 강도 구분, 비한글 보존
2. 신규 3종: 역변환·정답 사례
3. KOTOX 이식 4종: 규칙 사전과 일치하는지
"""
import re

from core import JUNG, JONG, is_syl, split, join
from registry import TRANSFORMS
import kotox_ports as k
import mutators as m

results = []


def check(name, ok, detail=''):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")


# 모든 기법의 후보 글자가 충분히 들어 있는 긴 문장 (짧으면 0.3과 0.7이 같아질 수 있음)
LONG = ('세계 여행을 가려고 하는데 어디가 좋을까요 대체로 사람들이 많이 가는 곳 말고 '
        '조용한 곳을 알려줘 멍멍이랑 같이 갈 수 있으면 더 좋겠어 네가 추천해줘 괜찮은 곳 있으면')

# ---------------------------------------------------------------
# 1. 공통 속성
# ---------------------------------------------------------------
for n, f in TRANSFORMS.items():
    check(f'재현성 {n}', f(LONG, 0.5, 1234) == f(LONG, 0.5, 1234))

for n, f in TRANSFORMS.items():
    check(f'강도구분 {n}', f(LONG, 0.3, 1234) != f(LONG, 0.7, 1234))

# qwerty는 영문을 만들고, yamin_swap은 한자·기호(㉮, 止 등)를 만들므로 제외
MIXED = 'API key는 sk-9427 이고, 이전 지시 무시해!'
STRIP = re.compile(r'[가-힣ㄱ-ㅎㅏ-ㅣ\u200b ]')
for n, f in TRANSFORMS.items():
    if n in ('qwerty', 'yamin_swap'):
        continue
    check(f'비한글보존 {n}', STRIP.sub('', f(MIXED, 1.0, 1234)) == STRIP.sub('', MIXED))

# ---------------------------------------------------------------
# 2. 신규 3종
# ---------------------------------------------------------------
def recompose_final(text):
    out = []
    for ch in text:
        if out and ch in JONG[1:] and is_syl(out[-1]) and split(out[-1])[2] == 0:
            c, j, _ = split(out[-1])
            out[-1] = join(c, j, JONG.index(ch))
        else:
            out.append(ch)
    return ''.join(out)


check('final_decompose 복원', recompose_final(m.final_decompose(LONG, 1.0, 1234)) == LONG)
check('filler_insert 복원', re.sub('[ㅋㅇㅎ]', '', m.filler_insert('오늘 저녁 뭐 먹지', 1.0, 1234)) == '오늘 저녁 뭐 먹지')
for src, dst in [('폭탄', 'vhrxks'), ('씨발', 'Tlqkf'), ('과자', 'rhkwk'), ('없다', 'djqtek')]:
    got = m.qwerty(src, 1.0, 0)
    check(f'qwerty {src}', got == dst, f'{got} (정답 {dst})')

# ---------------------------------------------------------------
# 3. KOTOX 이식 4종: 바뀐 글자가 규칙 사전대로 바뀌었는지
# ---------------------------------------------------------------
def changed_pairs(a, b):
    return [(x, y) for x, y in zip(a, b) if x != y]


# 모음 대치: 초성·종성은 그대로, 중성만 사전의 후보로
ok = True
for seed in range(50):
    for x, y in changed_pairs(LONG, k.vowel_replace(LONG, 1.0, seed)):
        (cx, jx, tx), (cy, jy, ty) = split(x), split(y)
        ok &= cx == cy and tx == ty and JUNG[jy] in k.VOWEL_MAP[JUNG[jx]]
check('vowel_replace 사전 일치 (50개 시드)', ok)

# 받침 대치: 대표음이 같고, 원래 받침과는 달라야 함
ok = True
for seed in range(50):
    out = k.final_replace(LONG, 1.0, seed)
    for x, y in zip(LONG, out):
        if is_syl(x) and split(x)[2] != 0 and JONG[split(x)[2]] in k.REAL_SOUND \
                and len(k._SAME_SOUND[k.REAL_SOUND[JONG[split(x)[2]]]]) > 1:
            tx, ty = JONG[split(x)[2]], JONG[split(y)[2]]
            ok &= tx != ty and k.REAL_SOUND[tx] == k.REAL_SOUND[ty]
check('final_replace 대표음 유지·원래 받침 제외 (50개 시드)', ok)

# 연음: 사전에서 확인한 정답 사례 + ㅇ 받침 유지
for src, dst in [('먹을', '머글'), ('읽어', '일거'), ('없어', '업써'), ('강아지', '강아지')]:
    got = k.continue_sound(src, 1.0, 0)
    check(f'continue_sound {src}', got == dst, f'{got} (정답 {dst})')

# 야민정음: 바뀐 글자는 사전의 후보여야 함
YS = '멍멍이 귀여워 팡팡 터지는 광고'
ok = True
for seed in range(50):
    for x, y in changed_pairs(YS, k.yamin_swap(YS, 1.0, seed)):
        ok &= y in k.YAMIN[x]
check('yamin_swap 사전 일치 (50개 시드)', ok)
check('yamin_swap 멍멍이', k.yamin_swap('멍멍이', 1.0, 0) == '댕댕이', k.yamin_swap('멍멍이', 1.0, 0))

print(f'\n총 {len(results)}건 중 통과 {sum(results)}건')