"""2단계: 번역 전 정리 (2-1 공통 정리, 2-2 출처별 정리, 2-3 중복 제거·길이 상한·템플릿 상한).

사용: 레포 루트에서  python step1_data/clean.py
필요: pip install pandas pyarrow ftfy

결과
- step1_data/data/interim/clean.jsonl        남은 문장 (git 제외)
- step1_data/data/reports/clean_dropped.jsonl 제외된 문장과 이유 (git 제외, 검토용)
- step1_data/reports/clean_summary.txt         이유별 건수 (문장 없음, 커밋 가능)

적용 순서 (먼저 걸린 이유 하나만 기록)
  1. over_length     번역 대상 출처에서 300자 초과   <- 맨 먼저: 나머지 이유는 300자 이하에 대해서만 집계됨
  2. label_conflict  같은 문장에 0과 1이 모두 붙음 -> 양쪽 제외
  3. 내용 규칙        empty / too_short / not_english / not_korean / non_text_type / placeholder / benign_jailbreak_kw
  4. duplicate       공백·대소문자·구두점 무시 기준 중복 (출처 우선순위가 높은 쪽을 남김)
  5. template_cap    xTRam1 공격에서 같은 틀(첫 세 단어)이 TEMPLATE_CAP건을 넘으면 무작위로 줄임

KoAlpaca는 번역하지 않으므로 길이 상한(영문 300자)을 여기서 적용하지 않는다.
번역된 공격의 한국어 길이 분포에 맞춰 2-4 이후에 따로 뽑는다.
"""
import re
import unicodedata
from pathlib import Path

import ftfy
import pandas as pd

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
OUT_CLEAN = ROOT / "data" / "interim" / "clean.jsonl"
OUT_DROPPED = ROOT / "data" / "reports" / "clean_dropped.jsonl"
OUT_SUMMARY = ROOT / "reports" / "clean_summary.txt"

# 출처 간 중복이면 앞쪽 출처를 남긴다 (공격 데이터 우선)
SOURCE_ORDER = ["gandalf", "xtram1", "hhrlhf", "koalpaca", "promptschat"]
TRANSLATE_SOURCES = {"gandalf", "xtram1", "hhrlhf", "promptschat"}
LITERAL_NEWLINE_SOURCES = {"xtram1", "koalpaca"}  # gandalf의 '\n'은 공격 내용 자체라 그대로 둠

SEED = 20261002
MAX_LEN = 300          # 번역 대상 출처의 길이 상한 (영문 원문 글자 수)
MIN_LEN_EN = 10        # 번역 대상 출처의 최소 길이
MIN_LEN_KO = 2         # KoAlpaca 최소 길이
MIN_HANGUL = 2         # KoAlpaca: 한글 음절이 이 수 미만이면 제외 (영어 섞인 한국어 질문은 남김)
MIN_LATIN_RATIO = 0.9  # 번역 대상: 글자 중 라틴 문자 비율
TEMPLATE_CAP = 75      # xTRam1 공격: 같은 틀(첫 세 단어)당 최대 건수
CAP_SCENARIOS = [None, 100, 75, 50]  # 요약에 함께 보여줄 상한 후보

FIRST_HUMAN = re.compile(r"^\n\nHuman: (.*?)(?=\n\nAssistant:|\n\nHuman:|$)", re.DOTALL)
# 정상(0) 라벨인데 탈옥·인젝션 표현이 있으면 제외 (라벨이 의심스러운 정상 데이터)
JAILBREAK_KW = re.compile(
    r"jailbr(?:eak|oken)|\bunfiltered\b|\buncensored\b|developer mode|do anything now"
    r"|\bno (?:ethical |moral )?(?:restrictions|limits|filters)\b"
    r"|ignore (?:all |any )?(?:the )?(?:previous|prior|above|earlier) (?:instructions|prompts|rules)",
    re.IGNORECASE,
)
JAILBREAK_DAN = re.compile(r"\bDAN\b")  # 대소문자 구분 ("Steely Dan" 제외)
# 빈칸 틀: {{주제}}, ${topic}, [PLACEHOLDER], [your field] (마크다운 링크 [글자](주소)는 제외)
PLACEHOLDER = re.compile(r"\{\{.*?\}\}|\$\{.*?\}|\[[A-Za-z][A-Za-z _/'-]{2,40}\](?!\()")
HANGUL = re.compile(r"[가-힣]")
ZERO_WIDTH = re.compile("[\u200b\u200c\u200d\u2060\ufeff]")
PUNCT = re.compile(r"[^\w\s]")


# ---------------------------------------------------------------- 불러오기
def read_files(folder, pattern):
    files = sorted(p for p in folder.rglob(pattern) if ".cache" not in p.parts)
    if not files:
        raise FileNotFoundError(f"{folder}에서 {pattern} 파일을 찾지 못함")
    for path in files:
        if path.name.endswith(".parquet"):
            df = pd.read_parquet(path)
        elif path.name.endswith(".csv"):
            df = pd.read_csv(path)
        else:
            df = pd.read_json(path, lines=True)
        split = path.name.split(".")[0].split("-")[0]  # train / test / validation / prompts
        yield split, df


def load_records():
    rows = []

    def add(source, frames, text_fn, label_fn, extra_fn=None):
        for split, df in frames:
            for i, r in enumerate(df.itertuples(index=False)):
                rows.append({
                    "source": source,
                    "label": int(label_fn(r)),
                    "text": text_fn(r),
                    "orig_split": split,   # 원본 파일
                    "orig_row": i,         # 원본 행 번호 (추적용)
                    "extra": extra_fn(r) if extra_fn else None,
                })

    add("gandalf", read_files(RAW / "gandalf", "*.parquet"), lambda r: r.text, lambda r: 1)
    add("xtram1", read_files(RAW / "xtram1", "*.parquet"), lambda r: r.text, lambda r: r.label)

    def hh_text(r):
        m = FIRST_HUMAN.match(r.chosen)
        return m.group(1) if m else None
    add("hhrlhf", read_files(RAW / "hhrlhf", "*.jsonl.gz"), hh_text, lambda r: 0)

    add("koalpaca", read_files(RAW / "koalpaca", "*.parquet"), lambda r: r.question, lambda r: 0)
    add("promptschat", read_files(RAW / "promptschat", "*.csv"), lambda r: r.prompt, lambda r: 0,
        extra_fn=lambda r: r.type)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 2-1 공통 정리
def normalize(text, source):
    """번역 후 한국어 문장에도 다시 쓸 수 있도록 언어에 의존하지 않게 작성."""
    if not isinstance(text, str):
        return ""
    text = ftfy.fix_text(text)                    # 인코딩 깨짐 수리 (LÃ¼beck -> Lübeck), 따옴표 통일
    if source in LITERAL_NEWLINE_SOURCES:
        text = text.replace("\\n", "\n")          # 글자 그대로 들어간 '\n'을 실제 줄바꿈으로
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = ZERO_WIDTH.sub("", text)               # 보이지 않는 문자 제거
    text = "".join(c for c in text
                   if c in "\n\t" or unicodedata.category(c) != "Cc")  # 제어문자 제거
    text = re.sub(r"[ \t]+", " ", text)          # 연속 공백 -> 한 칸
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)       # 빈 줄 여러 개 -> 하나
    return text.strip()


def dedup_key(text):
    """중복 판정용: 구두점 제거 + 공백 압축 + 소문자"""
    return re.sub(r"\s+", " ", PUNCT.sub(" ", text)).strip().lower()


def template_key(text):
    """템플릿 판정용: 구두점 제거 후 첫 세 단어"""
    return " ".join(dedup_key(text).split()[:3])


def latin_ratio(text):
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(ord(c) < 0x250 for c in letters) / len(letters)  # 기본·확장 라틴


# ---------------------------------------------------------------- 2-2 내용 규칙
def content_reason(row):
    text, source, label = row["text"], row["source"], row["label"]
    if not text:
        return "empty"

    if source in TRANSLATE_SOURCES:
        if len(text) < MIN_LEN_EN:
            return "too_short"
        if latin_ratio(text) < MIN_LATIN_RATIO:
            return "not_english"
    else:  # koalpaca
        if len(text) < MIN_LEN_KO:
            return "too_short"
        if len(HANGUL.findall(text)) < MIN_HANGUL:
            return "not_korean"

    if source == "promptschat":
        if row["extra"] != "TEXT":
            return "non_text_type"   # STRUCTURED(JSON 등), IMAGE
        if PLACEHOLDER.search(text):
            return "placeholder"

    if label == 0 and (JAILBREAK_KW.search(text) or JAILBREAK_DAN.search(text)):
        return "benign_jailbreak_kw"
    return None


def cap_templates(df, cap):
    """같은 틀이 cap건을 넘으면 무작위로 cap건만 남긴다. 남길 행의 index 반환."""
    if cap is None or df.empty:
        return df.index
    keep = []
    for _, g in df.groupby("template", sort=True):
        keep.extend(g.sample(min(len(g), cap), random_state=SEED).index)
    return pd.Index(sorted(keep))


# ---------------------------------------------------------------- 실행
def main():
    data = load_records()
    data["source_rank"] = data["source"].map(SOURCE_ORDER.index)
    data = data.sort_values(["source_rank", "orig_split", "orig_row"], kind="stable").reset_index(drop=True)

    data["text"] = [normalize(t, s) for t, s in zip(data["text"], data["source"])]
    data["key"] = data["text"].map(dedup_key)
    data["reason"] = None

    def alive():
        return data["reason"].isna()

    # 1) 길이 상한 (번역 대상 출처만)
    over = data["source"].isin(TRANSLATE_SOURCES) & (data["text"].str.len() > MAX_LEN)
    data.loc[over, "reason"] = "over_length"

    # 2) 라벨 충돌: 내용 규칙보다 먼저 (정상 쪽만 걸러지고 공격 쪽만 남는 일 방지)
    mask = alive() & (data["text"] != "")
    n_labels = data[mask].groupby("key")["label"].nunique()
    data.loc[mask & data["key"].isin(n_labels[n_labels > 1].index), "reason"] = "label_conflict"

    # 3) 내용 규칙
    mask = alive()
    data.loc[mask, "reason"] = data[mask].apply(content_reason, axis=1)

    # 4) 중복 제거 (출처 안·밖 모두, 우선순위 높은 출처의 첫 행을 남김)
    mask = alive()
    dup = data[mask].duplicated(subset="key", keep="first")
    data.loc[dup[dup].index, "reason"] = "duplicate"

    # 5) 템플릿 상한 (xTRam1 공격만)
    attack_x = data[alive() & (data["source"] == "xtram1") & (data["label"] == 1)].copy()
    attack_x["template"] = attack_x["text"].map(template_key)
    keep_idx = cap_templates(attack_x, TEMPLATE_CAP)
    data.loc[attack_x.index.difference(keep_idx), "reason"] = "template_cap"

    # ---- 저장
    kept = data[alive()]
    dropped = data[~alive()]
    for path in (OUT_CLEAN, OUT_DROPPED, OUT_SUMMARY):
        path.parent.mkdir(parents=True, exist_ok=True)
    kept[["source", "label", "text", "orig_split", "orig_row"]].to_json(
        OUT_CLEAN, orient="records", lines=True, force_ascii=False)
    dropped[["source", "label", "reason", "text", "orig_split", "orig_row"]].to_json(
        OUT_DROPPED, orient="records", lines=True, force_ascii=False)

    # ---- 요약 (문장 없이 숫자만)
    order = ["over_length", "label_conflict", "empty", "too_short", "not_english", "not_korean",
             "non_text_type", "placeholder", "benign_jailbreak_kw", "duplicate", "template_cap"]
    table = pd.crosstab([data["source"], data["label"]], data["reason"].fillna("KEPT"))
    table = table.reindex(columns=[r for r in order if r in table.columns] + ["KEPT"], fill_value=0)
    table.insert(0, "원본", table.sum(axis=1))
    table = table.reindex(sorted(table.index, key=lambda k: (SOURCE_ORDER.index(k[0]), -k[1])))

    other_attacks = int(((kept["label"] == 1) & (kept["source"] != "xtram1")).sum())
    scen = []
    for cap in CAP_SCENARIOS:
        idx = cap_templates(attack_x, cap)
        counts = attack_x.loc[idx, "template"].value_counts()
        scen.append({"틀당 상한": "없음" if cap is None else cap,
                     "xtram1 공격": len(idx), "공격 합계": len(idx) + other_attacks,
                     "상위 10개 틀 비중(%)": round(counts.head(10).sum() / max(len(idx), 1) * 100, 1),
                     "틀 종류": len(counts)})
    top = attack_x.loc[keep_idx, "template"].value_counts().head(10)

    length = kept.assign(length=kept["text"].str.len())
    lines = [
        "## 이유별 제외 건수 (KEPT = 남은 문장, 먼저 걸린 이유 하나만 기록)", table.to_string(), "",
        "## 라벨별 남은 건수", kept.groupby("label").size().to_string(), "",
        f"## xTRam1 공격 템플릿 상한 비교 (적용값: {TEMPLATE_CAP})",
        pd.DataFrame(scen).to_string(index=False), "",
        "적용 후 상위 10개 틀 (첫 세 단어):", top.to_string(), "",
        "## 남은 문장 길이 (글자 수)",
        length.groupby(["source", "label"])["length"].describe(percentiles=[0.5, 0.9])
              [["count", "mean", "50%", "90%", "max"]].round(0).astype(int).to_string(), "",
        "## 번역 대상 (koalpaca 제외) 글자 수",
        length[length["source"].isin(TRANSLATE_SOURCES)].groupby("label")["length"]
              .agg(["count", "sum"]).to_string(),
    ]
    OUT_SUMMARY.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\n저장: {OUT_CLEAN.relative_to(ROOT.parent)}, {OUT_DROPPED.relative_to(ROOT.parent)}, "
          f"{OUT_SUMMARY.relative_to(ROOT.parent)}")


if __name__ == "__main__":
    main()