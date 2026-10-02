"""5단계 kg_test 만들기 + 6단계 분할 (그룹 분할 + 라벨x출처 층화 + train 길이 보정).

사용: 레포 루트에서  python step1_data/split.py
입력: step1_data/data/interim/final_pool.jsonl
      screening/candidates.jsonl, screening/excluded.jsonl, screening/holdout_ids.txt (T1 결과)
결과 (모두 git 제외 폴더):
      step1_data/data/final/{train,valid,test,kg_test}.jsonl   필드: id, text, label, source
      step1_data/data/final/assignments.jsonl                 id별 분할·그룹 (재현용)
      step1_data/reports/split_summary.txt                     데이터 카드용 숫자 (커밋 가능)

그룹 분할: 공격끼리 영어 원문 단어 집합의 Jaccard 유사도가 0.6 이상이면 같은 그룹으로 묶고(gandalf·xtram1 함께),
           같은 그룹은 train/valid/test 중 한 곳에만 넣는다. 정상은 한 문장이 한 그룹.
층화: TRAIN_FIX_MIN건 이상인 큰 그룹은 train에 고정하고, 나머지 그룹을 라벨 x 출처마다 8:1:1이 되도록
      큰 것부터 '목표 대비 가장 모자란 분할'에 배정.
길이 보정: train 안에서만, xtram1 짝의 한국어 길이 구간별로 정상을 줄이거나 복제해 공격 분포에 맞춤.
           복제 행 id는 '<원래 id>_dup<번호>'. valid/test에는 적용하지 않음.
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from clean import dedup_key, normalize
from sample_normals import ks_stat, make_bins

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
IN_POOL = ROOT / "data" / "interim" / "final_pool.jsonl"
KG_CAND = REPO / "screening" / "candidates.jsonl"
KG_EXCL = REPO / "screening" / "excluded.jsonl"
KG_HOLDOUT = REPO / "screening" / "holdout_ids.txt"
OUT_DIR = ROOT / "data" / "final"
OUT_SUMMARY = ROOT / "reports" / "split_summary.txt"

SEED = 20261002
RATIO = {"train": 0.8, "valid": 0.1, "test": 0.1}
JACCARD = 0.6
TRAIN_FIX_MIN = 30         # 이 크기 이상인 공격 그룹은 train에 고정 (valid/test가 템플릿 하나에 지배되지 않게)
LENGTH_CORRECTION = True   # 채원님 학습 코드가 복제 행(_dup)을 받지 못하면 False
FIELDS = ["id", "text", "label", "source"]


# ---------------------------------------------------------------- 5단계: kg_test
def pick(df, names):
    for n in names:
        if n in df.columns:
            return n
    raise KeyError(f"다음 컬럼을 찾지 못함: {names} (실제: {list(df.columns)})")


def build_kg_test():
    cand = pd.read_json(KG_CAND, lines=True)
    excl = pd.read_json(KG_EXCL, lines=True)
    kg = pd.concat([cand, excl], ignore_index=True)
    id_col = pick(kg, ["id", "seed_id"])
    text_col = pick(kg, ["text", "prompt", "input"])
    src_col = pick(kg, ["source"])
    holdout = set(KG_HOLDOUT.read_text(encoding="utf-8").split())

    non_template = kg[kg[src_col] != "template_v1"]
    test = non_template[~non_template[id_col].isin(holdout)].copy()
    if "subtype" in test.columns:  # 외국어 공격(E2)은 연구 범위(한국어) 밖이라 제외
        test = test[test["subtype"] != "language_switch"]
    out = pd.DataFrame({
        "id": "kg_" + test[id_col].astype(str),
        "text": [normalize(t, "kg") for t in test[text_col]],
        "label": test[id_col].astype(str).str.startswith("bng").map({True: 0, False: 1}),
        "source": "koreanguardrail",
    })
    meta = test.drop(columns=[text_col]).rename(columns={id_col: "kg_original_id"})
    meta = meta.rename(columns={c: f"kg_{c}" for c in meta.columns if c in ("label", "source", "category")})  # kg_test의 label/source와 헷갈리지 않게
    meta.insert(0, "id", "kg_" + test[id_col].astype(str))
    info = {"전체": len(kg), "템플릿 아님": len(non_template), "holdout 제외 후": len(out),
            "holdout 중 실제로 빠진 수": int(non_template[id_col].isin(holdout).sum())}
    return out, meta, kg[text_col].map(lambda t: dedup_key(normalize(t, "kg"))), info


# ---------------------------------------------------------------- 그룹
def attack_groups(att):
    """영어 원문 단어 집합 Jaccard >= JACCARD 인 공격끼리 연결 (union-find)"""
    sets = [set(dedup_key(t).split()) for t in att["text_en"]]
    vocab = {w: i for i, w in enumerate(sorted(set().union(*sets)))}
    X = np.zeros((len(sets), len(vocab)), dtype=np.float32)
    for r, s in enumerate(sets):
        X[r, [vocab[w] for w in s]] = 1
    inter = X @ X.T
    size = X.sum(1)
    jac = inter / (size[:, None] + size[None, :] - inter + 1e-9)

    parent = list(range(len(sets)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    rows, cols = np.where(np.triu(jac >= JACCARD, k=1))
    for a, b in zip(rows, cols):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
    return [f"atk_g{find(i)}" for i in range(len(sets))]


# ---------------------------------------------------------------- 층화 그룹 분할
def assign_splits(df, rng):
    df = df.copy()
    df["stratum"] = df["label"].astype(str) + "_" + df["source"]
    # 그룹의 층 = 그룹 안 다수 출처
    g_stratum = df.groupby("group")["stratum"].agg(lambda s: s.value_counts().index[0])
    g_size = df.groupby("group").size()
    groups = pd.DataFrame({"stratum": g_stratum, "size": g_size})
    groups["rand"] = rng.rand(len(groups))
    groups = groups.sort_values(["size", "rand"], ascending=[False, True])

    target = {s: {k: v * n for k, v in RATIO.items()} for s, n in df.groupby("stratum").size().items()}
    got = {s: {k: 0 for k in RATIO} for s in target}
    split_of = {}
    for g, row in groups[groups["size"] >= TRAIN_FIX_MIN].iterrows():  # 큰 그룹은 train 고정
        split_of[g] = "train"
        got[row["stratum"]]["train"] += row["size"]
    for g, row in groups[groups["size"] < TRAIN_FIX_MIN].iterrows():
        s = row["stratum"]
        deficit = {k: (target[s][k] - got[s][k]) / target[s][k] for k in RATIO}
        best = max(deficit, key=deficit.get)
        split_of[g] = best
        got[s][best] += row["size"]
    df["split"] = df["group"].map(split_of)
    return df.drop(columns="stratum")


# ---------------------------------------------------------------- train 길이 보정
def length_correct(train, rng, log):
    xa = train[(train["pair"] == "xtram1") & (train["label"] == 1)]
    xn = train[(train["pair"] == "xtram1") & (train["label"] == 0)]
    edges = make_bins(xa["length"])
    edges[-1] = max(edges[-1], xn["length"].max(), xa["length"].max())
    a_bin = pd.cut(xa["length"], edges, include_lowest=True, labels=False)
    n_bin = pd.cut(xn["length"], edges, include_lowest=True, labels=False)

    keep_parts = []
    for b in range(len(edges) - 1):
        norm = xn[n_bin == b]
        n_a, n_n = int((a_bin == b).sum()), len(norm)
        if n_n == 0:
            continue
        m = n_a / n_n
        full, frac = int(np.floor(m)), m - np.floor(m)
        parts = [norm] if full >= 1 else []
        for k in range(2, full + 1):  # 2배 이상이면 통째로 복제
            parts.append(norm.assign(id=norm["id"] + f"_dup{k - 1}"))
        extra = norm.sample(int(round(frac * n_n)), random_state=rng)
        if full >= 1:
            parts.append(extra.assign(id=extra["id"] + f"_dup{full}"))
        else:
            parts.append(extra)  # 1배 미만이면 일부만 남김 (축소)
        part = pd.concat(parts)
        keep_parts.append(part)
        log.append({"구간": b, "범위": f"{edges[b]:.0f}~{edges[b + 1]:.0f}", "공격": n_a,
                    "정상(원래)": n_n, "배수": round(m, 2), "정상(보정 후)": len(part)})
    corrected = pd.concat(keep_parts)
    rest = train[~((train["pair"] == "xtram1") & (train["label"] == 0))]
    out = pd.concat([rest, corrected], ignore_index=True)
    return out, ks_stat(xa["length"].to_numpy(), xn["length"].to_numpy()), \
        ks_stat(xa["length"].to_numpy(), corrected["length"].to_numpy())


# ---------------------------------------------------------------- 실행
def main():
    rng = np.random.RandomState(SEED)
    pool = pd.read_json(IN_POOL, lines=True)
    pool["length"] = pool["text"].str.len()
    pool["translated"] = pool["source"] != "koalpaca"
    lines = []

    # ---- 5단계
    kg_test, kg_meta, kg_keys, kg_info = build_kg_test()
    pool_keys = pool["text"].map(dedup_key)
    overlap = int(pool_keys.isin(set(kg_keys)).sum())
    assert overlap == 0, f"학습 데이터와 KoreanGuardrail이 겹침: {overlap}건"

    # ---- 그룹
    att = pool[pool["label"] == 1]
    pool["group"] = "n_" + pool["id"]
    pool.loc[att.index, "group"] = attack_groups(att)
    sizes = pool.loc[att.index, "group"].value_counts()

    # ---- 분할
    pool = assign_splits(pool, rng)
    for a in ["train", "valid"], ["train", "test"], ["valid", "test"]:
        shared = set(pool.loc[pool["split"] == a[0], "group"]) & set(pool.loc[pool["split"] == a[1], "group"])
        assert not shared, f"{a} 사이에 같은 그룹이 있음"

    # ---- train 길이 보정
    train = pool[pool["split"] == "train"]
    corr_log = []
    if LENGTH_CORRECTION:
        train, ks_before, ks_after = length_correct(train, rng, corr_log)
    splits = {"train": train, "valid": pool[pool["split"] == "valid"], "test": pool[pool["split"] == "test"]}

    # ---- 저장
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, df in {**splits, "kg_test": kg_test}.items():
        df = df.sample(frac=1, random_state=rng)  # 파일 안 순서 섞기 (라벨·출처 순서가 드러나지 않게)
        df[FIELDS].to_json(OUT_DIR / f"{name}.jsonl", orient="records", lines=True, force_ascii=False)
        assert df["id"].is_unique, f"{name}: id 중복"
    pool[["id", "split", "group", "source", "label"]].to_json(OUT_DIR / "assignments.jsonl", orient="records", lines=True)
    kg_meta.to_json(OUT_DIR / "kg_test_meta.jsonl", orient="records", lines=True, force_ascii=False)

    # ---- 요약
    def comp(df):
        t = df.groupby(["label", "source"]).size().unstack(0, fill_value=0)
        t.columns = [f"label{c}" for c in t.columns]
        return t

    lines += ["## 5단계: kg_test", *[f"  {k}: {v}" for k, v in kg_info.items()],
              f"  라벨: 공격 {int((kg_test['label'] == 1).sum())} / 정상 {int((kg_test['label'] == 0).sum())}",
              f"  학습 풀과 겹치는 문장: {overlap}건", "",
              "## 그룹 (공격, 영어 원문 Jaccard >= %.1f)" % JACCARD,
              f"  공격 {len(att)}건 -> 그룹 {len(sizes)}개, 2건 이상 그룹 {int((sizes > 1).sum())}개, "
              f"가장 큰 그룹 {sizes.max()}건, 상위 5개 {sizes.head(5).tolist()}", ""]
    lines += [f"  {TRAIN_FIX_MIN}건 이상 그룹 {int((sizes >= TRAIN_FIX_MIN).sum())}개({int(sizes[sizes >= TRAIN_FIX_MIN].sum())}건)는 train 고정", ""]
    lines += ["## 분할별 공격 중 가장 큰 그룹 비중"]
    for name in ["train", "valid", "test"]:
        a = pool[(pool["split"] == name) & (pool["label"] == 1)]
        top = a["group"].value_counts()
        lines.append(f"  {name}: {top.iloc[0]}/{len(a)}건 ({top.iloc[0] / len(a) * 100:.1f}%)")
    lines += ["", "## 분할별 구성 (보정 전 원문 기준)"]
    for name in ["train", "valid", "test"]:
        df = pool[pool["split"] == name]
        lines += [f"[{name}] {len(df)}건 (공격 {int((df['label'] == 1).sum())} / 정상 {int((df['label'] == 0).sum())})",
                  comp(df).to_string(), ""]
    lines += ["## 분할별 번역/한국어 원본 비율 (정상 기준, 공격은 전부 번역)"]
    for name in ["train", "valid", "test"]:
        df = pool[(pool["split"] == name) & (pool["label"] == 0)]
        lines.append(f"  {name}: 번역 {int(df['translated'].sum())} ({df['translated'].mean() * 100:.1f}%) / "
                     f"원본(koalpaca) {int((~df['translated']).sum())} ({(~df['translated']).mean() * 100:.1f}%)")
    lines.append(f"  kg_test: 전부 비번역(AI 생성 한국어) {len(kg_test)}건")
    lines.append("")
    if LENGTH_CORRECTION:
        n_dup = int(train["id"].str.contains("_dup").sum())
        lines += ["## train 길이 보정 (xtram1 짝, 한국어 글자 수)", pd.DataFrame(corr_log).to_string(index=False),
                  f"  KS {ks_before:.3f} -> {ks_after:.3f} / 복제 행 {n_dup}건 / "
                  f"train 최종 {len(train)}건 (공격 {int((train['label'] == 1).sum())} / 정상 {int((train['label'] == 0).sum())})", ""]
    lines += ["## 분할별 xtram1 짝 길이 KS (test·valid는 보정 없음)"]
    for name, df in splits.items():
        a = df[(df["pair"] == "xtram1") & (df["label"] == 1)]["length"].to_numpy()
        n = df[(df["pair"] == "xtram1") & (df["label"] == 0)]["length"].to_numpy()
        lines.append(f"  {name}: KS {ks_stat(a, n):.3f}")
    lines += ["", f"저장 폴더: {OUT_DIR}"]

    OUT_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    OUT_SUMMARY.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()