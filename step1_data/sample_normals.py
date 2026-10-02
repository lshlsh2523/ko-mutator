"""2-4: 정상 데이터 뽑기 (짝 맞추기 + 길이 구간 맞춤) + 2-5: 번역용 파일 만들기.

사용: 레포 루트에서  python step1_data/sample_normals.py
입력: step1_data/data/interim/clean.jsonl

짝 맞추기
  xtram1 공격  ↔  xtram1 정상          (같은 수, xtram1 공격의 길이 분포에 맞춤)
  gandalf 공격 ↔  hhrlhf + promptschat  (gandalf 수의 2/3, gandalf 길이 분포에 맞춤)
                  + koalpaca            (gandalf 수의 1/3, 번역 후 4단계에서 한국어 길이에 맞춰 추출)

길이 맞춤: 공격 길이를 10개 구간(10%씩)으로 나누고, 정상도 구간별로 같은 비율만큼 무작위 추출.
           구간에 정상이 모자라면 부족 범위 바로 아래·위에서 가까운 순으로 채우되,
           아래·위 개수는 공격과의 KS가 가장 작아지게 정함.
키워드:    password/secret/instruction/prompt/ignore/previous/forget/disregard/repeat가 들어간 정상은
           우선 모두 포함 (키워드 오탐 방지용 hard negative).
id:        출처별 원본 순서로만 번호를 매김 (라벨 순서가 드러나지 않게).
검사:      같은 원본 행·같은 문장이 두 번 들어가면 오류로 중단.
길이 보정용 복제는 하지 않는다 (6단계 분할 후 train 안에서만 적용).

결과
- step1_data/data/interim/to_translate.jsonl  번역할 문장 (공격 전체 + 뽑힌 정상, id 부여)
- step1_data/reports/sample_summary.txt        구간별 추출 내역, 길이 비교, 번역 글자 수 (문장 없음)
"""
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
IN_CLEAN = ROOT / "data" / "interim" / "clean.jsonl"
OUT_TRANSLATE = ROOT / "data" / "interim" / "to_translate.jsonl"
OUT_SUMMARY = ROOT / "reports" / "sample_summary.txt"

SEED = 20261002
N_BINS = 10
KOALPACA_SHARE = 1 / 3   # gandalf 짝 중 KoAlpaca 몫
PC_MAX_SHARE = 0.3       # gandalf 짝의 각 구간에서 promptschat이 차지할 수 있는 최대 비율
MAX_LEN = 300
# gandalf 공격에 많이 나오는 단어. 이 단어가 있는 정상(hard negative)은 우선 포함 (키워드 오탐 방지)
KEYWORDS = re.compile(
    r"\b(?:passwords?|secrets?|instructions?|prompts?|ignor(?:e|es|ed|ing)|previous(?:ly)?"
    r"|forget|forgot|forgotten|disregard(?:s|ed|ing)?|repeat(?:s|ed|ing)?)\b",
    re.IGNORECASE,
)


def largest_remainder(weights, total):
    """비율대로 total을 정수로 나눔 (합이 정확히 total)"""
    raw = np.asarray(weights, dtype=float) / sum(weights) * total
    out = np.floor(raw).astype(int)
    for i in np.argsort(-(raw - out))[: total - out.sum()]:
        out[i] += 1
    return out


def make_bins(attack_len):
    """공격 길이의 10분위 경계. 맨 앞은 0, 맨 뒤는 MAX_LEN으로 넓혀 정상 문장도 모두 들어가게."""
    edges = np.unique(np.quantile(attack_len, np.linspace(0, 1, N_BINS + 1)))
    edges[0], edges[-1] = 0, MAX_LEN
    return edges


def ks_stat(a, b):
    """두 길이 분포의 최대 누적분포 차이 (0이면 같음, 1이면 완전히 다름)"""
    grid = np.union1d(a, b)
    ca = np.searchsorted(np.sort(a), grid, side="right") / len(a)
    cb = np.searchsorted(np.sort(b), grid, side="right") / len(b)
    return float(np.max(np.abs(ca - cb)))


def take_in_order(cand, need, pc_room):
    """cand 순서대로 need건을 고르되 promptschat은 pc_room건까지만"""
    keep = []
    for idx, is_pc in zip(cand.index, cand["is_pc"]):
        if len(keep) == need:
            break
        if is_pc:
            if pc_room == 0:
                continue
            pc_room -= 1
        keep.append(idx)
    return pd.Index(keep)


def sample_matched(attacks, pool, total, rng, pc_cap=False):
    """attacks의 길이 구간 비율대로 pool에서 total건을 뽑는다.

    1) 키워드(password 등) 정상은 우선 모두 포함 (키워드 지름길 방지)
    2) 나머지는 구간별 목표만큼 무작위 추출 (promptschat은 구간 목표의 PC_MAX_SHARE까지)
    3) 구간에 후보가 모자라면, 그 구간 길이에 가장 가까운 문장부터 채움 (같은 상한 적용)
    """
    edges = make_bins(attacks["length"])
    n_bins = len(edges) - 1
    a_bin = pd.cut(attacks["length"], edges, include_lowest=True, labels=False)
    targets = largest_remainder(a_bin.value_counts().reindex(range(n_bins), fill_value=0), total)

    pool = pool.sample(frac=1, random_state=rng).copy()  # 무작위 순서 (시드 고정)
    pool["bin"] = pd.cut(pool["length"], edges, include_lowest=True, labels=False).values
    pool["is_pc"] = pool["source"] == "promptschat"
    pc_limit = {b: int(np.floor(targets[b] * PC_MAX_SHARE)) if pc_cap else 10**9 for b in range(n_bins)}

    used = pd.Series(False, index=pool.index)
    got = {b: 0 for b in range(n_bins)}
    got_pc = {b: 0 for b in range(n_bins)}

    def pick(idx, b):
        used.loc[idx] = True
        got[b] += len(idx)
        got_pc[b] += int(pool.loc[idx, "is_pc"].sum())

    # 1) 키워드 정상 우선 포함 (자기 구간 몫으로 계산)
    prio = pool[pool["text"].str.contains(KEYWORDS)]
    for b, g in prio.groupby("bin"):
        pick(g.index, int(b))

    # 2) 구간별 무작위 추출
    for b in range(n_bins):
        need = targets[b] - got[b]
        if need <= 0:
            continue
        cand = pool[~used & (pool["bin"] == b)]
        cand = pd.concat([cand[cand["is_pc"]], cand[~cand["is_pc"]]])  # promptschat을 상한까지 먼저 (역할 지시형 hard negative)
        pick(take_in_order(cand, need, max(pc_limit[b] - got_pc[b], 0)), b)

    log = [{"구간": b, "범위": f"{edges[b]:.0f}~{edges[b + 1]:.0f}", "공격": int((a_bin == b).sum()),
            "목표": int(targets[b]), "뽑음": got[b], "부족": max(int(targets[b]) - got[b], 0)} for b in range(n_bins)]

    # 3) 부족분: 부족한 구간들의 길이 범위 [lo, hi] 바로 아래·위에서 가까운 순으로 채움.
    #    아래에서 k건, 위에서 (부족 합계 - k)건을 가져오되, k는 공격과의 KS가 가장 작아지는 값으로 정함.
    #    고른 문장은 짧은 것부터 짧은 구간에 배정. (fill 단계에서는 promptschat을 쓰지 않음)
    moved = []
    short = {b: int(targets[b]) - got[b] for b in range(n_bins) if int(targets[b]) - got[b] > 0}
    if short:
        need = sum(short.values())
        lo = min(edges[b] for b in short)
        hi = max(edges[b + 1] for b in short)
        free = pool[~used & ~pool["is_pc"]]
        inside = free[(free["length"] >= lo) & (free["length"] <= hi)].index[:need]
        rest = need - len(inside)
        below = free[free["length"] < lo].sort_values("length", ascending=False, kind="stable").index
        above = free[free["length"] > hi].sort_values("length", kind="stable").index

        base = pool.loc[used, "length"].to_numpy()
        best = None
        for k in range(max(0, rest - len(above)), min(rest, len(below)) + 1):
            idx = inside.append(below[:k]).append(above[:rest - k])
            ks = ks_stat(attacks["length"].to_numpy(), np.concatenate([base, pool.loc[idx, "length"].to_numpy()]))
            if best is None or ks < best[0]:
                best = (ks, k, idx)
        _, k_best, keep = best
        moved.append(f"부족분 {need}건: 범위 {lo:.0f}~{hi:.0f}자 안 {len(inside)}건, 아래 {k_best}건, 위 {rest - k_best}건 (KS 최소)")

        keep = pool.loc[keep].sort_values("length", kind="stable").index
        pos = 0
        for b in sorted(short):
            part = keep[pos: pos + short[b]]
            pos += len(part)
            pick(part, b)
            if len(part):
                lengths = pool.loc[part, "length"]
                moved.append(f"구간 {b}({edges[b]:.0f}~{edges[b + 1]:.0f}) 부족분 {len(part)}건 "
                             f"-> 길이 {lengths.min()}~{lengths.max()}자 문장으로 채움")
            if len(part) < short[b]:
                moved.append(f"!! 구간 {b}: {short[b] - len(part)}건을 채우지 못함")

    result = pool[used].drop(columns=["bin", "is_pc"])
    return result, pd.DataFrame(log), moved, len(prio)


def assign_ids(df):
    """출처별로 원본 순서대로 번호를 붙임: xtram1_00001 ..."""
    df = df.sort_values(["source", "orig_split", "orig_row"], kind="stable").copy()  # 라벨로 정렬하지 않음 (id로 라벨이 드러나지 않게)
    df["id"] = df["source"] + "_" + (df.groupby("source").cumcount() + 1).map("{:05d}".format)
    return df


def length_line(name, a, n):
    # 유의수준 5% 임계값: KS가 이보다 작으면 "두 길이 분포가 다르다"고 볼 근거가 없음
    crit = 1.36 * np.sqrt((len(a) + len(n)) / (len(a) * len(n)))
    return (f"{name}: 공격 평균 {a.mean():.0f} / 중앙값 {a.median():.0f}  |  "
            f"정상 평균 {n.mean():.0f} / 중앙값 {n.median():.0f}  |  KS {ks_stat(a, n):.3f} (임계값 {crit:.3f})")


def kw_table(out):
    has = out["text"].str.contains(KEYWORDS)
    t = out.assign(kw=has).groupby(["pair", "label"])["kw"].agg(["sum", "count"])
    t["비율(%)"] = (t["sum"] / t["count"] * 100).round(1)
    return t.rename(columns={"sum": "키워드 포함", "count": "전체"})


def main():
    rng = np.random.RandomState(SEED)
    data = pd.read_json(IN_CLEAN, lines=True)
    data["length"] = data["text"].str.len()

    x_att = data[(data["source"] == "xtram1") & (data["label"] == 1)]
    g_att = data[data["source"] == "gandalf"]
    x_pool = data[(data["source"] == "xtram1") & (data["label"] == 0)]
    g_pool = data[data["source"].isin(["hhrlhf", "promptschat"])]

    n_koalpaca = round(len(g_att) * KOALPACA_SHARE)
    n_g_en = len(g_att) - n_koalpaca

    x_norm, x_log, x_moved, x_prio = sample_matched(x_att, x_pool, len(x_att), rng)
    g_norm, g_log, g_moved, g_prio = sample_matched(g_att, g_pool, n_g_en, rng, pc_cap=True)

    out = pd.concat([
        x_att.assign(pair="xtram1"), x_norm.assign(pair="xtram1"),
        g_att.assign(pair="gandalf"), g_norm.assign(pair="gandalf"),
    ])
    out = assign_ids(out)

    # ---- 검사: 같은 원문이 두 번 들어가면 중단
    dup_row = out.duplicated(subset=["source", "orig_split", "orig_row"], keep=False)
    norm_key = out["text"].str.replace(r"[^\w\s]", " ", regex=True).str.split().str.join(" ").str.lower()
    dup_text = norm_key.duplicated(keep=False)
    assert not dup_row.any(), f"같은 원본 행이 두 번 선택됨: {int(dup_row.sum())}건"
    assert not dup_text.any(), f"같은 문장이 두 번 선택됨: {int(dup_text.sum())}건"
    assert out["id"].is_unique, "id 중복"
    assert len(x_norm) == len(x_att) and len(g_norm) == n_g_en, "목표 건수와 다름"
    OUT_TRANSLATE.parent.mkdir(parents=True, exist_ok=True)
    out[["id", "source", "label", "text", "pair", "orig_split", "orig_row"]].to_json(
        OUT_TRANSLATE, orient="records", lines=True, force_ascii=False)

    # ---- 요약
    counts = out.groupby(["pair", "source", "label"]).size().rename("건수")
    chars = out.groupby("label")["length"].agg(["count", "sum"])
    lines = [
        "## 1. 구성",
        counts.to_string(), "",
        f"KoAlpaca (4단계에서 번역된 gandalf 공격의 한국어 길이에 맞춰 추출 예정): {n_koalpaca}건",
        f"최종 예상: 공격 {int((out['label'] == 1).sum())} / 정상 {int((out['label'] == 0).sum()) + n_koalpaca}", "",
        "## 2. 구간별 추출 — xtram1 짝", x_log.to_string(index=False), *x_moved, "",
        "## 3. 구간별 추출 — gandalf 짝 (hhrlhf + promptschat)", g_log.to_string(index=False), *g_moved, "",
        "gandalf 짝 출처별:", g_norm["source"].value_counts().to_string(), "",
        "## 4. 길이 비교 (KS: 0에 가까울수록 비슷. 임계값보다 작으면 길이 분포 차이가 통계적으로 유의하지 않음)",
        length_line("xtram1 짝", x_att["length"], x_norm["length"]),
        length_line("gandalf 짝 (KoAlpaca 제외)", g_att["length"], g_norm["length"]),
        length_line("전체 (참고: KoAlpaca가 빠져 gandalf 짝 정상이 2/3뿐이라 차이가 날 수 있음)", out[out["label"] == 1]["length"], out[out["label"] == 0]["length"]), "",
        "## 5. 키워드(password, secret, instruction, prompt, ignore, previous, forget, disregard, repeat) 포함 비율",
        kw_table(out).to_string(),
        f"우선 포함된 키워드 정상: xtram1 짝 {x_prio}건, gandalf 짝 {g_prio}건", "",
        "## 6. 번역 글자 수",
        chars.rename(columns={"count": "문장 수", "sum": "글자 수"}).to_string(),
        f"합계: {int(out['length'].sum()):,}자 / 문장 {len(out):,}건",
    ]
    OUT_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    OUT_SUMMARY.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\n저장: {OUT_TRANSLATE.relative_to(ROOT.parent)}, {OUT_SUMMARY.relative_to(ROOT.parent)}")


if __name__ == "__main__":
    main()