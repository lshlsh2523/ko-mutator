"""Step 1 데이터 규모 집계 (읽기 전용).

사용: 레포 루트에서  python step1_data/count_scale.py
결과: step1_data/data/reports/scale.txt

결정 사항 반영 (10/2):
- 라벨: 1 = 공격, 0 = 정상
- deepset 제외
- xtram1 정상(0)도 정상으로 사용
- 원본 train/test 분할은 무시하고 모두 합침

이 스크립트는 '대략 몇 건, 몇 글자인가'만 본다.
최종 정리 규칙(인코딩 수리, 짧은 문장 제거 등)은 2단계에서 따로 적용한다.
"""
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
OUT_FILE = ROOT / "data" / "reports" / "scale.txt"

LENGTH_CAPS = [300, 500, 1000, 2000]   # 길이 상한 후보 (원문 글자 수)
NO_TRANSLATION = {"koalpaca"}          # 한국어 원본이라 번역 안 함
FIRST_HUMAN = re.compile(r"^\n\nHuman: (.*?)(?=\n\nAssistant:|\n\nHuman:|$)", re.DOTALL)


def read_all(folder, pattern):
    files = sorted(p for p in folder.rglob(pattern) if ".cache" not in p.parts)
    if not files:
        raise FileNotFoundError(f"{folder}에서 {pattern} 파일을 찾지 못함")
    frames = []
    for path in files:
        if path.name.endswith(".parquet"):
            frames.append(pd.read_parquet(path))
        elif path.name.endswith(".csv"):
            frames.append(pd.read_csv(path))
        else:
            frames.append(pd.read_json(path, lines=True))
    return pd.concat(frames, ignore_index=True)


def first_human(dialogue):
    match = FIRST_HUMAN.match(dialogue)
    return match.group(1) if match else None


def load_sources():
    """각 출처를 (source, text, label) 형태로 통일"""
    parts = []

    df = read_all(RAW / "gandalf", "*.parquet")
    parts.append(pd.DataFrame({"source": "gandalf", "text": df["text"], "label": 1}))

    df = read_all(RAW / "xtram1", "*.parquet")
    parts.append(pd.DataFrame({"source": "xtram1", "text": df["text"], "label": df["label"]}))

    df = read_all(RAW / "hhrlhf", "*.jsonl.gz")
    parts.append(pd.DataFrame({"source": "hhrlhf", "text": df["chosen"].map(first_human), "label": 0}))

    df = read_all(RAW / "koalpaca", "*.parquet")
    parts.append(pd.DataFrame({"source": "koalpaca", "text": df["question"], "label": 0}))

    df = read_all(RAW / "promptschat", "*.csv")
    parts.append(pd.DataFrame({"source": "promptschat", "text": df["prompt"], "label": 0}))

    data = pd.concat(parts, ignore_index=True)
    data = data[data["text"].notna()].copy()
    data["text"] = data["text"].str.strip()
    data = data[data["text"] != ""]
    # 중복 판정용 키: 공백 압축 + 소문자
    data["key"] = data["text"].str.replace(r"\s+", " ", regex=True).str.lower()
    data["length"] = data["text"].str.len()
    return data


def main():
    data = load_sources()
    out = []
    groups = ["source", "label"]

    # 1) 원본 건수 (모든 split 합침)
    raw_counts = data.groupby(groups).size().rename("원본")

    # 2) 출처 안에서 중복 제거
    within = data.drop_duplicates(subset=["source", "key"])
    within_counts = within.groupby(groups).size().rename("출처내 중복제거")

    # 3) 같은 문장에 다른 라벨 (출처 안/밖 모두, 중복 제거 전 원본 기준)
    label_kinds = data.groupby("key")["label"].nunique()
    conflict_keys = set(label_kinds[label_kinds > 1].index)

    # 4) 출처 간 중복 제거 (라벨 충돌 문장은 제외, 나머지는 먼저 나온 출처를 남김:
    #    gandalf → xtram1 → hhrlhf → koalpaca → promptschat 순)
    clean = within[~within["key"].isin(conflict_keys)]
    cross = clean.drop_duplicates(subset=["key"])
    cross_counts = cross.groupby(groups).size().rename("전체 중복제거")

    table = pd.concat([raw_counts, within_counts, cross_counts], axis=1)
    for cap in LENGTH_CAPS:
        table[f"≤{cap}자"] = cross[cross["length"] <= cap].groupby(groups).size()
    table = table.fillna(0).astype(int)

    out.append("## 1. 건수 (출처 x 라벨)")
    out.append(table.to_string())
    out.append("")
    out.append("라벨별 합계:")
    out.append(table.groupby(level="label").sum().to_string())
    out.append("")
    out.append(f"라벨 충돌로 제외된 고유 문장: {len(conflict_keys)}개")

    # 출처 간 겹침 현황
    dup_keys = within[within.duplicated(subset=["key"], keep=False)]
    pairs = (dup_keys.groupby("key")["source"].apply(lambda s: " + ".join(sorted(set(s))))
             .value_counts())
    pairs = pairs[pairs.index.str.contains(r"\+")]
    out.append("")
    out.append("출처 간 겹침 (고유 문장 수):")
    out.append(pairs.to_string() if len(pairs) else "  없음")

    # 5) 길이 분포 (지름길 확인용)
    out.append("")
    out.append("## 2. 길이 분포 (전체 중복제거 후, 원문 글자 수)")
    desc = cross.groupby(groups)["length"].describe(percentiles=[0.5, 0.9, 0.99])
    out.append(desc[["count", "mean", "50%", "90%", "99%", "max"]].round(0).astype(int).to_string())

    # 6) 번역할 글자 수 (koalpaca 제외)
    out.append("")
    out.append("## 3. 번역 대상 총 글자 수 (koalpaca 제외, 해당 출처 전량 기준)")
    to_translate = cross[~cross["source"].isin(NO_TRANSLATION)]
    rows = []
    for cap in [None] + LENGTH_CAPS:
        subset = to_translate if cap is None else to_translate[to_translate["length"] <= cap]
        by_label = subset.groupby("label")["length"].sum()
        rows.append({
            "상한": "없음" if cap is None else f"≤{cap}자",
            "공격(1) 글자": int(by_label.get(1, 0)),
            "정상(0) 글자": int(by_label.get(0, 0)),
            "합계": int(subset["length"].sum()),
            "문장 수": len(subset),
        })
    out.append(pd.DataFrame(rows).to_string(index=False))
    out.append("")
    out.append("※ 정상은 실제로는 일부만 뽑아 쓰므로 실제 번역량은 이보다 적음.")

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))
    print(f"\n저장: {OUT_FILE.relative_to(ROOT.parent)}")


if __name__ == "__main__":
    main()