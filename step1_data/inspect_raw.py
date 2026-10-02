"""Step 1 원본 데이터 구조 확인 (읽기 전용, 데이터를 바꾸지 않음).

사용: 레포 루트에서  python step1_data/inspect_raw.py
결과: step1_data/data/reports/inspect_raw.txt  (git 제외 폴더)

데이터셋마다 파일별로 다음을 기록한다.
- 행 수, 컬럼 이름과 타입
- 값 종류가 적은 컬럼(라벨 후보)의 값 분포
- 문자열 컬럼의 길이 통계, 빈 값 수, 중복 수, 한글 포함 비율
- 무작위 샘플 3개 (시드 고정)
"""
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "data" / "raw"
OUT_FILE = ROOT / "data" / "reports" / "inspect_raw.txt"

DATA_EXTS = (".parquet", ".csv", ".jsonl", ".jsonl.gz")
SEED = 20261002      # 샘플 추출용 난수 시드
SAMPLE_N = 3         # 파일당 샘플 수
MAX_UNIQUE = 10      # 값 종류가 이 이하면 라벨 후보로 보고 분포 출력
CLIP = 200           # 샘플 출력 시 최대 글자 수
HANGUL = re.compile("[가-힣]")  # 완성형 한글 음절


def find_data_files(folder):
    files = []
    for path in sorted(folder.rglob("*")):
        if ".cache" in path.parts or not path.is_file():
            continue
        if path.name.endswith(DATA_EXTS):
            files.append(path)
    return files


def read_file(path):
    name = path.name
    if name.endswith(".parquet"):
        return pd.read_parquet(path)
    if name.endswith(".csv"):
        return pd.read_csv(path)
    return pd.read_json(path, lines=True)  # .jsonl / .jsonl.gz (압축 자동 인식)


def is_text_column(series):
    values = series.dropna()
    return len(values) > 0 and values.map(lambda v: isinstance(v, str)).all()


def describe_column(name, series, out):
    nulls = int(series.isna().sum())
    try:
        n_unique = series.nunique(dropna=True)
    except TypeError:  # list/dict 같은 복합 타입
        out.append(f"  - {name}: 복합 타입(list/dict 등), 빈 값 {nulls}")
        return

    if n_unique <= MAX_UNIQUE:
        counts = {clip(k, 40): v for k, v in series.value_counts(dropna=False).items()}
        out.append(f"  - {name}: 값 {n_unique}종 (라벨 후보) {counts}")
        return

    if is_text_column(series):
        text = series.dropna()
        lengths = text.str.len()
        dup = int(text.duplicated().sum())
        empty = int((text.str.strip() == "").sum())
        hangul = text.map(lambda t: bool(HANGUL.search(t))).mean() * 100
        out.append(
            f"  - {name}: 문자열 | 길이 평균 {lengths.mean():.0f} / 중앙값 {lengths.median():.0f}"
            f" / 최소 {lengths.min()} / 최대 {lengths.max()} | 총 {lengths.sum():,}자"
            f" | 빈 값 {nulls} | 빈 문자열 {empty} | 중복 {dup} | 한글 포함 {hangul:.1f}%"
        )
    else:
        out.append(f"  - {name}: {series.dtype}, 값 {n_unique}종, 빈 값 {nulls}")


def clip(value, limit=CLIP):
    if not isinstance(value, str):
        return value if isinstance(value, (int, float, bool)) or value is None else clip(
            json.dumps(value, ensure_ascii=False, default=str), limit)
    text = value.replace("\n", "\\n")
    return text if len(text) <= limit else text[:limit] + " …"


def inspect_dataset(folder, out):
    out.append("=" * 70)
    out.append(f"[{folder.name}]")
    files = find_data_files(folder)
    if not files:
        out.append("  !! 데이터 파일을 찾지 못함")
        return

    for path in files:
        out.append("-" * 70)
        out.append(f"파일: {path.relative_to(folder)}")
        try:
            df = read_file(path)
        except Exception as e:  # 읽기 실패해도 다른 파일은 계속
            out.append(f"  !! 읽기 실패: {type(e).__name__}: {e}")
            continue

        out.append(f"행 수: {len(df):,}")
        out.append("컬럼: " + ", ".join(f"{c}({df[c].dtype})" for c in df.columns))
        for col in df.columns:
            describe_column(col, df[col], out)

        out.append(f"샘플 {min(SAMPLE_N, len(df))}개 (seed={SEED}):")
        for i, (_, row) in enumerate(df.sample(min(SAMPLE_N, len(df)), random_state=SEED).iterrows(), 1):
            out.append(f"  [{i}]")
            for col in df.columns:
                out.append(f"    {col}: {clip(row[col])}")


def main():
    out = []
    for folder in sorted(p for p in RAW_DIR.iterdir() if p.is_dir()):
        print(f"검사 중: {folder.name}")
        inspect_dataset(folder, out)

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"\n완료: {OUT_FILE.relative_to(ROOT.parent)}")


if __name__ == "__main__":
    main()