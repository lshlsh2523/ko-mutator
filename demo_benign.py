"""정상 문장(KoAlpaca풍)이 9종 기법으로 난독화되는지 확인한다."""
import mutators as m

BENIGN = [
    '오늘 저녁에 먹을 간단한 요리 추천해줘',
    '파이썬으로 CSV 파일 읽는 법 알려줘',
    '주말에 아이랑 갈 만한 실내 놀이 장소 있을까?',
]
INTENSITIES = [0.3, 0.7]

for s in BENIGN:
    print(f'\n원문: {s}')
    for name, fn in m.TRANSFORMS.items():
        for it in INTENSITIES:
            out = fn(s, it, 1234)
            if name == 'zwsp_inject':      # 눈에 안 보이므로 기호로 치환해 표시
                out = out.replace('\u200b', '·')
            print(f'  {name:16} {it}  {out}')