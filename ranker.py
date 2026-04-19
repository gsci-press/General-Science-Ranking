"""
ranker.py — 期刊排名与分区

评分设计：
  不做归一化，直接用各指标的加权线性组合作为绝对分数。
  这样新期刊加入时，已有期刊的分数不变，可以直接插入排名。

分区规则（固定名额，不按比例）：
  Q1: 前50本
  Q2: 第51-150本
  Q3: 第151-300本
  Q4: 300名以后
  不够就空着，不强行填满。
"""

import numpy as np
import pandas as pd
from scorer import compute_metrics

# 固定分区名额
Q1_LIMIT  = 50    # Q1: 1-50
Q2_LIMIT  = 100   # Q2: 51-100
Q3_LIMIT  = 200   # Q3: 101-200
# Q4: 201及以后


def score_all_journals(journal_list: list, config: dict,
                       progress_callback=None) -> pd.DataFrame:
    rows  = []
    total = len(journal_list)

    for i, j in enumerate(journal_list):
        source_id = j.get("id", "")
        name      = j.get("name", "")

        if not source_id or not source_id.startswith("http"):
            continue

        metrics = compute_metrics(source_id, config)

        row = {
            "openalex_id": source_id,
            "name":        name,
            "issn":        j.get("issn", ""),
            "eissn":       j.get("eissn", ""),
        }

        if metrics is None:
            row["data_status"] = "no_data"
        elif metrics.get("_insufficient"):
            row["data_status"] = "insufficient_data"
            row["paper_count"] = metrics.get("paper_count", 0)
        else:
            row["data_status"] = "ok"
            row.update(metrics)

        rows.append(row)

        if progress_callback:
            progress_callback(i + 1, total, name)

    return pd.DataFrame(rows)


def compute_score(row: pd.Series, config: dict) -> float:
    """
    计算单本期刊的绝对得分（不归一化）。

    各指标直接加权求和：
      score = w_fwci * fwci_mean + w_if2 * if2 + w_h5 * h5_norm + w_cagr * cite_cagr

    h5做对数缩放（避免量纲差异过大）：log(1+h5)
    cite_cagr做对数缩放：log(1+max(cagr,0))

    自引率超过阈值打折。
    """
    weights   = config["weights"]
    threshold = config.get("self_cite_threshold", 0.30)
    penalty   = config.get("self_cite_penalty",   0.80)

    fwci_mean  = float(row.get("fwci_mean",  0) or 0)
    # 期刊用if2（真实值），会议用if2_approx（估算值）；两者互斥，取非零那个
    if2_real   = float(row.get("if2",        0) or 0)
    if2_approx = float(row.get("if2_approx", 0) or 0)
    if2        = if2_real if if2_real > 0 else if2_approx
    h5         = float(row.get("h5",         0) or 0)
    cite_cagr  = float(row.get("cite_cagr",  0) or 0)
    self_cite  = float(row.get("self_cite_rate", 0) or 0)

    # 对数缩放，让h5和cagr与fwci/if2在同一量纲
    h5_scaled   = np.log1p(h5)
    cagr_scaled = np.log1p(max(cite_cagr, 0))

    score = (
        weights.get("fwci_mean", 0) * fwci_mean +
        weights.get("if2",       0) * if2       +
        weights.get("h5",        0) * h5_scaled  +
        weights.get("cite_cagr", 0) * cagr_scaled
    )

    # 自引率惩罚
    if self_cite > threshold:
        score *= penalty

    return round(float(score), 4)


def assign_quartiles(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """
    固定名额分区：Q1≤50本，Q2≤100本（第51-150），Q3≤150本（第151-300），Q4=其余。
    数据不足时不强行填满。
    """
    valid = df[df["data_status"] == "ok"].copy()
    other = df[df["data_status"] != "ok"].copy()

    if valid.empty:
        df["quartile"] = "暂无数据"
        df["score"]    = None
        return df

    # 计算绝对得分
    valid["score"] = valid.apply(lambda row: compute_score(row, config), axis=1)

    # 按分数降序排名
    valid = valid.sort_values("score", ascending=False).reset_index(drop=True)
    valid["rank"] = valid.index + 1  # 从1开始

    # 固定名额分区
    def assign_q(rank):
        if rank <= Q1_LIMIT:  return "Q1"
        if rank <= Q2_LIMIT:  return "Q2"
        if rank <= Q3_LIMIT:  return "Q3"
        return "Q4"
    valid["quartile"] = valid["rank"].apply(assign_q)

    # 其他期刊标注状态
    other["score"]   = None
    other["rank"]    = None
    other["quartile"] = other["data_status"].map({
        "no_data":          "暂无数据",
        "insufficient_data":"数据不足",
        "blacklisted":      "非期刊实体",
    }).fillna("暂无数据")

    result = pd.concat([valid, other], ignore_index=True)
    result = result.sort_values(
        ["rank", "score"],
        ascending=[True, False],
        na_position="last"
    ).reset_index(drop=True)

    return result
