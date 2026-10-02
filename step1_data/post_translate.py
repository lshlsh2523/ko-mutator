"""4단계: 번역 후 정리 (4-1 품질 점검, 4-2 정리 함수 재적용, 4-3 "prompt" 일관성,
4-4 KoAlpaca 추출, 4-5 한국어 기준 지름길·토큰 점검).

사용: 레포 루트에서  python step1_data/post_translate.py
      (토큰 점검까지 하려면: pip install transformers sentencepiece protobuf)

입력: step1_data/data/interim/translated.jsonl, step1_data/data/interim/clean.jsonl
결과: step1_data/data/interim/final_pool.jsonl         분할 전 최종 데이터 (git 제외)
      step1_data/data/reports/post_translate_review.txt 점검에 걸린 문장 예시 (git 제외)
      step1_data/reports/post_translate_summary.txt     숫자 요약 (커밋 가능)

자동 제외는 "빈 번역"과 "원문과 똑같은 번역(번역 안 됨)"만. 나머지 점검 항목은 표시만 하고 남긴다.
"""
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from clean import dedup_key, normalize  # 2단계와 같은 정리 함수·중복 판정 키
from sample_normals import ks_stat, largest_remainder, make_bins  # 같은 구간·KS 계산

ROOT = Path(__file__).resolve().parent
IN_TRANSLATED = ROOT / "data" / "interim" / "translated.jsonl"
IN_CLEAN = ROOT / "data" / "interim" / "clean.jsonl"
OUT_POOL = ROOT / "data" / "interim" / "final_pool.jsonl"
OUT_REVIEW = ROOT / "data" / "reports" / "post_translate_review.txt"
OUT_SUMMARY = ROOT / "reports" / "post_translate_summary.txt"

SEED = 20261002
N_KOALPACA = 331
KW_MAX_SHARE = 0.5      # KoAlpaca 각 길이 구간에서 키워드 질문이 차지할 수 있는 최대 비율
RATIO_LOW, RATIO_HIGH = 0.2, 1.2   # 한국어/영어 글자 수 비율이 이 범위 밖이면 표시
MIN_HANGUL_RATIO = 0.3  # 번역문 글자 중 한글 비율이 이보다 낮으면 "영어가 많이 남음"으로 표시
MAX_TOKENS = 128
TOKENIZERS = {  # 채원님 학습 코드와 같은 모델인지 확인 필요
    "KoELECTRA": "monologg/koelectra-base-v3-discriminator",
    "mDeBERTa": "microsoft/mdeberta-v3-base",
}

HANGUL = re.compile(r"[가-힣]")
EN_PROMPT = re.compile(r"\bprompts?\b", re.IGNORECASE)
# 한국어 키워드 (gandalf 공격에 많은 단어의 한국어 대응)
KO_KW = re.compile(r"비밀번호|패스워드|암호|비밀|지시|지침|명령|프롬프트|무시|이전|잊|반복")
# KoAlpaca 질문 중 실제 인젝션처럼 보이는 것 (정상 라벨로 쓰면 안 됨)
_TGT = r"(?:지시|명령|프롬프트|지침|규칙|대화|역할)"
KO_INJECTION = re.compile(rf"(?:무시|잊).{{0,15}}{_TGT}|{_TGT}.{{0,15}}(?:무시|잊)")
# KoAlpaca 질문 중 상대(챗봇)의 비밀 정보를 요구하는 것 (xTRam1 공격과 같은 의미)
KO_SECRET_ASK = re.compile(
    r"(?:너|네|당신)(?:의)?\s*\S{0,10}\s*(?:아이디|비밀번호|계정)"
    r"|(?:아이디|비밀번호)(?:와|랑|하고)?\s*(?:비밀번호)?\s*(?:를|좀)?\s*(?:알려|말해)\s*(?:줘|주세요|줄래)"
    r"|비밀번호(?:는|가)\s*\??\s*$"
)


def hangul_ratio(text):
    letters = [c for c in text if c.isalpha()]
    return sum(bool(HANGUL.match(c)) for c in letters) / len(letters) if letters else 0.0


# ---------------------------------------------------------------- 4-1, 4-2, 4-3
def check_translations(tr, review):
    tr["text"] = [normalize(t, s) for t, s in zip(tr["text"], tr["source"])]  # 4-2
    tr["ratio"] = tr["text"].str.len() / tr["text_en"].str.len()
    has_prompt = tr["text_en"].str.contains(EN_PROMPT)
    checks = {
        "empty": tr["text"].str.strip() == "",
        "identical": tr["text"].str.strip() == tr["text_en"].str.strip(),
        "mostly_latin": tr["text"].map(hangul_ratio) < MIN_HANGUL_RATIO,
        "detected_not_en": tr["detected_source_lang"].str.upper() != "EN",
        "length_ratio": (tr["ratio"] < RATIO_LOW) | (tr["ratio"] > RATIO_HIGH),
        "prompt_not_kept": has_prompt & ~tr["text"].str.contains("프롬프트"),  # 4-3
    }
    tr["flag"] = [",".join(k for k in checks if checks[k].iloc[i]) for i in range(len(tr))]

    for name in ["empty", "identical", "mostly_latin", "detected_not_en", "length_ratio", "prompt_not_kept"]:
        rows = tr[tr["flag"].str.contains(name)]
        review.append(f"===== {name}: {len(rows)}건 (최대 15건 표시)")
        for _, r in rows.head(15).iterrows():
            review += [f"[{r['id']}] label={r['label']} ratio={r['ratio']:.2f}", f"  EN: {r['text_en']}", f"  KO: {r['text']}", ""]

    drop = checks["empty"] | checks["identical"]
    stats = {
        "has_prompt_en": int(has_prompt.sum()),
        "prompt_kept": int((has_prompt & tr["text"].str.contains("프롬프트")).sum()),
    }
    return tr[~drop].copy(), tr, stats


# ---------------------------------------------------------------- 4-4
def sample_koalpaca(g_att_ko, pool, review):
    rng = np.random.RandomState(SEED)
    pool = pool.copy()
    pool["length"] = pool["text"].str.len()

    inj = pool["text"].map(lambda t: bool(KO_INJECTION.search(t)))
    ask = pool["text"].map(lambda t: bool(KO_SECRET_ASK.search(t)))
    suspicious = inj | ask
    review.append(f"===== KoAlpaca 제외: 인젝션 의심 {int(inj.sum())}건, 비밀 정보 요구 {int(ask.sum())}건 (전부 표시)")
    for t in pool.loc[suspicious, "text"]:
        review.append(f"  {t}")
    review.append("")
    pool = pool[~suspicious]

    edges = make_bins(g_att_ko)
    edges[-1] = g_att_ko.max()  # 번역된 gandalf 공격보다 긴 질문은 쓰지 않음
    a_bin = pd.cut(g_att_ko, edges, include_lowest=True, labels=False)
    targets = largest_remainder(a_bin.value_counts().reindex(range(len(edges) - 1), fill_value=0), N_KOALPACA)

    pool["bin"] = pd.cut(pool["length"], edges, include_lowest=True, labels=False)
    pool = pool[pool["bin"].notna()].sample(frac=1, random_state=rng)
    pool["kw"] = pool["text"].str.contains(KO_KW)

    chosen, log = [], []
    for b, t in enumerate(targets):
        cand = pool[pool["bin"] == b]
        kw = cand[cand["kw"]].head(int(np.floor(t * KW_MAX_SHARE)))
        rest = cand[~cand.index.isin(kw.index)].head(t - len(kw))
        got = pd.concat([kw, rest])
        chosen.append(got)
        log.append({"구간": b, "범위": f"{edges[b]:.0f}~{edges[b + 1]:.0f}", "목표": int(t),
                    "뽑음": len(got), "키워드": len(kw), "부족": int(t) - len(got)})
    ko = pd.concat(chosen).sort_values(["orig_split", "orig_row"], kind="stable")
    ko["id"] = "koalpaca_" + pd.Series(range(1, len(ko) + 1), index=ko.index).map("{:05d}".format)
    ko["pair"], ko["text_en"] = "gandalf", ""
    return ko, pd.DataFrame(log), int(suspicious.sum())


# ---------------------------------------------------------------- 4-5
def ks_line(name, a, n):
    crit = 1.36 * np.sqrt((len(a) + len(n)) / (len(a) * len(n)))
    return (f"{name}: 공격 평균 {a.mean():.0f} / 중앙값 {a.median():.0f}  |  정상 평균 {n.mean():.0f} / "
            f"중앙값 {n.median():.0f}  |  KS {ks_stat(a.to_numpy(), n.to_numpy()):.3f} (임계값 {crit:.3f})")


def token_check(final):
    try:
        from transformers import AutoTokenizer
    except ImportError:
        return ["(transformers가 없어 건너뜀: pip install transformers sentencepiece protobuf)"]
    lines = []
    for name, model in TOKENIZERS.items():
        try:
            tok = AutoTokenizer.from_pretrained(model)
        except Exception as e:
            lines.append(f"{name} ({model}): 불러오기 실패 {type(e).__name__}: {e}")
            continue
        n_tok = final["text"].map(lambda t: len(tok(t, add_special_tokens=True)["input_ids"]))
        over = final.assign(over=n_tok > MAX_TOKENS, n_tok=n_tok)
        table = over.groupby(["source", "label"]).agg(
            건수=("over", "size"), 초과=("over", "sum"), 토큰_중앙값=("n_tok", "median"), 토큰_최대=("n_tok", "max"))
        table["초과(%)"] = (table["초과"] / table["건수"] * 100).round(1)
        lines += [f"{name} ({model}): 전체 {int(over['over'].sum())}/{len(over)}건이 {MAX_TOKENS}토큰 초과",
                  table.to_string(), ""]
    return lines


def main():
    review, lines = [], []
    tr_raw = pd.read_json(IN_TRANSLATED, lines=True)
    tr, tr_all, pstats = check_translations(tr_raw, review)

    clean = pd.read_json(IN_CLEAN, lines=True)
    ko_pool = clean[clean["source"] == "koalpaca"]
    g_att_ko = tr[(tr["source"] == "gandalf")]["text"].str.len()
    ko, ko_log, n_susp = sample_koalpaca(g_att_ko, ko_pool, review)

    cols = ["id", "source", "label", "text", "pair", "text_en", "orig_split", "orig_row"]
    final = pd.concat([tr[cols], ko[cols]], ignore_index=True)
    final["length"] = final["text"].str.len()
    assert final["id"].is_unique, "id 중복"
    # 번역 후 같은 문장이 된 행: 라벨이 같으면 첫 행만 남기고, 다르면 양쪽 제외
    final["key"] = final["text"].map(dedup_key)
    n_label = final.groupby("key")["label"].transform("nunique")
    dup_conflict = n_label > 1
    dup_same = ~dup_conflict & final.duplicated("key", keep="first")
    dup_note = (f"번역 후 중복: 같은 라벨 {int(dup_same.sum())}건 제거 "
                f"(공격 {int((dup_same & (final['label'] == 1)).sum())} / 정상 {int((dup_same & (final['label'] == 0)).sum())}), "
                f"라벨 충돌 {int(dup_conflict.sum())}건 제외")
    final = final[~dup_same & ~dup_conflict].drop(columns="key").reset_index(drop=True)
    n_dup = int(final["text"].map(dedup_key).duplicated().sum())

    OUT_POOL.parent.mkdir(parents=True, exist_ok=True)
    final[cols].to_json(OUT_POOL, orient="records", lines=True, force_ascii=False)

    # ---- 요약
    flag_counts = {n: int(tr_all["flag"].str.contains(n).sum()) for n in
                   ["empty", "identical", "mostly_latin", "detected_not_en", "length_ratio", "prompt_not_kept"]}
    final["kw"] = final["text"].str.contains(KO_KW)
    kw_tab = final.groupby(["pair", "label"])["kw"].agg(["sum", "count"])
    kw_tab["비율(%)"] = (kw_tab["sum"] / kw_tab["count"] * 100).round(1)

    xa = final[(final["pair"] == "xtram1") & (final["label"] == 1)]["length"]
    xn = final[(final["pair"] == "xtram1") & (final["label"] == 0)]["length"]
    ga = final[(final["pair"] == "gandalf") & (final["label"] == 1)]["length"]
    gn = final[(final["pair"] == "gandalf") & (final["label"] == 0)]["length"]
    gn_en = final[(final["pair"] == "gandalf") & (final["label"] == 0) & (final["source"] != "koalpaca")]["length"]
    gn_ko = final[final["source"] == "koalpaca"]["length"]

    lines += [
        "## 4-1. 번역 품질 점검 (empty, identical만 자동 제외 / 나머지는 표시만)",
        *[f"  {k}: {v}건" for k, v in flag_counts.items()],
        f"  한국어/영어 글자 수 비율: 중앙값 {tr_all['ratio'].median():.2f}, 5% {tr_all['ratio'].quantile(.05):.2f}, "
        f"95% {tr_all['ratio'].quantile(.95):.2f}", "",
        "## 4-3. 'prompt' 번역 일관성",
        f"  원문에 prompt가 있는 문장 {pstats['has_prompt_en']}건 중 '프롬프트'로 번역 {pstats['prompt_kept']}건", "",
        "## 4-4. KoAlpaca 추출 (번역된 gandalf 공격의 한국어 길이에 맞춤)",
        f"  인젝션 의심·비밀 정보 요구로 제외: {n_susp}건 (목록은 검토 파일)",
        ko_log.to_string(index=False), "",
        "## 최종 구성",
        final.groupby(["pair", "source", "label"]).size().rename("건수").to_string(),
        f"공격 {int((final['label'] == 1).sum())} / 정상 {int((final['label'] == 0).sum())}"
        f" / 남은 중복 {n_dup}건", dup_note, "",
        "## 4-5. 한국어 기준 지름길 점검",
        "길이 (한국어 글자 수):",
        ks_line("  xtram1 짝", xa, xn),
        ks_line("  gandalf 짝 (전체)", ga, gn),
        ks_line("  gandalf 짝 (영어 번역 정상만)", ga, gn_en),
        ks_line("  gandalf 짝 (KoAlpaca만)", ga, gn_ko), "",
        "한국어 키워드 포함 비율:", kw_tab.rename(columns={"sum": "포함", "count": "전체"}).to_string(), "",
        f"토큰 수 ({MAX_TOKENS} 초과 비율):", *token_check(final),
    ]
    OUT_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    OUT_SUMMARY.write_text("\n".join(lines) + "\n", encoding="utf-8")
    OUT_REVIEW.parent.mkdir(parents=True, exist_ok=True)
    OUT_REVIEW.write_text("\n".join(review) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\n저장: {OUT_POOL.relative_to(ROOT.parent)}, {OUT_SUMMARY.relative_to(ROOT.parent)}, "
          f"{OUT_REVIEW.relative_to(ROOT.parent)}")


if __name__ == "__main__":
    main()