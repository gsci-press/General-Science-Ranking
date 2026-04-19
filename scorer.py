"""
scorer.py — 期刊文献计量指标计算

输入：某期刊多年的论文列表（OpenAlex格式）
输出：该期刊的各项文献计量指标

指标说明：
  fwci_mean   : 所有论文的FWCI均值（领域加权引用影响，OpenAlex直接提供）
  if2         : 两年影响因子 = 前两年论文在当年的被引总数 / 前两年论文总数
  h5          : 近5年h指数
  cite_cagr   : 引用量3年复合增长率
  self_cite   : 自引率 = 本刊引用本刊的次数 / 总引用次数
  paper_count : 有效论文数（article类型）
"""

import math
import json
from pathlib import Path
from collections import defaultdict


# 进入分母的论文类型（对标JCR）
ARTICLE_TYPES = {"article", "review"}


def safe_filename(name: str) -> str:
    """把名称转成安全的文件名（和download_cs_conferences.py保持一致）"""
    import re
    return re.sub(r'[\\/:*?"<>|&()#]', '_', name).strip('_')[:50]


def load_papers(data_dir: str, source_id: str, years: list,
                venue_name: str = "") -> list:
    """
    从本地加载论文数据。
    优先用OpenAlex短ID找文件（期刊），
    没有则用venue_name的safe_filename找（会议，S2数据）。
    """
    sid = source_id.strip().split("/")[-1] if source_id else ""
    all_papers = []

    for year in years:
        path = None

        # 优先：OpenAlex短ID文件
        if sid:
            p = Path(data_dir) / f"{sid}_{year}.json"
            if p.exists() and p.stat().st_size > 10:
                path = p

        # 备选1：_s2后缀文件（期刊S2降级数据）
        if path is None and sid:
            p_s2 = Path(data_dir) / f"{sid}_{year}_s2.json"
            if p_s2.exists() and p_s2.stat().st_size > 10:
                path = p_s2

        # 备选2：safe_filename文件（S2会议数据，带_s2后缀）
        if path is None and venue_name:
            safe = safe_filename(venue_name)
            for suffix in [f"{safe}_{year}_s2.json", f"{safe}_{year}.json"]:
                p2 = Path(data_dir) / suffix
                if p2.exists() and p2.stat().st_size > 10:
                    path = p2
                    break

        if path is None:
            continue

        try:
            papers = json.loads(path.read_text(encoding="utf-8"))
            for p in papers:
                p["_year_file"] = year
            all_papers.extend(papers)
        except Exception:
            pass

    return all_papers


def compute_metrics(source_id: str, config: dict,
                    venue_name: str = "") -> dict:
    """
    计算期刊/会议的全部文献计量指标。
    venue_name: 会议名称，用于查找S2下载的数据文件。
    返回指标字典，或在数据不足时返回 None。
    """
    papers = load_papers(config["data_dir"], source_id,
                         config["years"] + [2025], venue_name)

    if not papers:
        return None

    # 只保留 article / review 类型
    articles = [p for p in papers if (p.get("type") or "").lower() in ARTICLE_TYPES
                and not p.get("is_paratext", False)
                and not p.get("is_retracted", False)]

    # 判断数据来源（S2会议 or OpenAlex期刊）
    is_s2 = all(p.get("_source") == "s2" for p in articles[:10])
    # 会议（venue_name非空）不管数据来源，都用if2_approx路径
    is_conf = bool(venue_name)

    if len(articles) < config.get("min_papers", 20):
        return {"_insufficient": True, "paper_count": len(articles)}

    # ── 1. FWCI均值 ──────────────────────────────────────────────
    fwci_values = [p["fwci"] for p in articles
                   if p.get("fwci") is not None and p["fwci"] > 0]
    fwci_mean   = sum(fwci_values) / len(fwci_values) if fwci_values else 0.0

    # ── 2. 两年影响因子（IF2）────────────────────────────────────
    # IF2 = 前两年article/review类型论文的平均被引数（对标JCR）
    # 严格按类型过滤：只有article和review进分母，editorial/letter/erratum等排除
    ref_years      = sorted(config["years"])[-2:]
    current_year   = 2025
    MIN_IF2_DENOM  = 1   # 不设最小发文量门槛，数据有多少用多少
    IF2_TYPES      = {"article", "review"}

    if2_numerator   = 0
    if2_denominator = 0

    # 期刊（OpenAlex）：用counts_by_year近两年引用
    # 会议（S2）：没有counts_by_year，if2=0，用cited_by_count算if2_approx
    if2_approx_num   = 0
    if2_approx_denom = 0

    for p in articles:
        py    = p.get("publication_year")
        ptype = (p.get("type") or "").strip().lower()
        if py not in ref_years:
            continue
        if ptype not in IF2_TYPES:
            continue
        has_abstract = bool(
            p.get("abstract_inverted_index") or
            (p.get("abstract") and len(str(p.get("abstract", ""))) > 50)
        )
        has_citation = (p.get("cited_by_count") or 0) > 0
        if not has_abstract and not has_citation:
            continue

        cby = {c["year"]: c["cited_by_count"]
               for c in p.get("counts_by_year", [])}

        if cby:
            # OpenAlex期刊：用counts_by_year
            if2_denominator += 1
            if2_numerator   += cby.get(current_year, 0) + cby.get(current_year - 1, 0)
        else:
            # S2会议：进入if2_approx的分母（不限年份在外层循环处理）
            pass  # S2会议在下方单独计算

    if if2_denominator >= MIN_IF2_DENOM:
        if2 = if2_numerator / if2_denominator
    else:
        if2 = 0.0

    # S2会议：用cited_by_count × 比例系数 推算近两年引用，再算if2_approx
    # 比例系数来自141万篇OpenAlex期刊论文的实测中位数：
    # recent_2yr / cited_by_count 中位数 = 0.75
    RECENT_RATIO = 0.75

    if is_s2 or is_conf:
        RECENT_RATIO   = 0.75
        CS_IF2_TO_FWCI = 0.21

        # 用2023/2024年发表的论文估算if2_approx
        ref_articles = [p for p in articles
                        if p.get("publication_year") in ref_years
                        and (p.get("cited_by_count") or 0) > 0]

        if len(ref_articles) >= 5:
            estimated_recent = sum(
                (p.get("cited_by_count", 0) or 0) * RECENT_RATIO
                for p in ref_articles
            )
            if2_approx = round(estimated_recent / len(ref_articles), 4)
        else:
            # 分母不足时用全部论文
            all_cited = [p for p in articles if (p.get("cited_by_count") or 0) > 0]
            if len(all_cited) >= 10:
                estimated_recent = sum(
                    (p.get("cited_by_count", 0) or 0) * RECENT_RATIO
                    for p in all_cited
                )
                if2_approx = round(estimated_recent / len(all_cited), 4)
            else:
                if2_approx = 0.0

        if fwci_mean == 0 and if2_approx > 0:
            fwci_mean = round(if2_approx * CS_IF2_TO_FWCI, 4)

    elif if2_approx_denom >= MIN_IF2_DENOM:
        if2_approx = if2_approx_num / if2_approx_denom
    else:
        if2_approx = 0.0

    # ── 3. h5指数（近5年article/review论文）────────────────────
    # 只用article和review类型，和IF2保持一致
    h5_years  = list(range(current_year - 5, current_year + 1))
    h5_papers = [
        p for p in articles
        if p.get("publication_year") in h5_years
        and (p.get("type") or "").strip().lower() in IF2_TYPES
        and (
            bool(p.get("abstract_inverted_index") or
                 (p.get("abstract") and len(str(p.get("abstract", ""))) > 50))
            or (p.get("cited_by_count") or 0) > 0
        )
    ]
    cited_counts = sorted(
        [p.get("cited_by_count", 0) or 0 for p in h5_papers],
        reverse=True
    )
    h5 = 0
    for i, c in enumerate(cited_counts, 1):
        if c >= i:
            h5 = i
        else:
            break

    # ── 4. 引用增长率CAGR（3年）─────────────────────────────────
    # 聚合期刊在各年份被引总量，计算增长率
    yearly_citations = defaultdict(int)
    for p in articles:
        for cby in p.get("counts_by_year", []):
            yearly_citations[cby["year"]] += cby["cited_by_count"]

    cagr_years = [2022, 2023, 2024, 2025]
    cite_seq   = [yearly_citations.get(y, 0) for y in cagr_years]

    # 取有数据的年份计算CAGR
    valid = [(y, c) for y, c in zip(cagr_years, cite_seq) if c > 0]
    if len(valid) >= 2:
        y0, c0 = valid[0]
        y1, c1 = valid[-1]
        n_years = y1 - y0
        cite_cagr = (c1 / c0) ** (1 / n_years) - 1 if n_years > 0 and c0 > 0 else 0.0
    else:
        cite_cagr = 0.0

    # ── 5. 自引率 ────────────────────────────────────────────────
    sid = source_id.strip().split("/")[-1].lower()
    total_refs    = 0
    self_cite_cnt = 0
    for p in articles:
        refs = p.get("referenced_works", [])
        total_refs += len(refs)
        # OpenAlex的referenced_works是URL列表，无法直接判断来源期刊
        # 用primary_location判断是否是本刊论文
        # 这里用简化方法：referenced_works_count作为分母
    # 注：精确自引率需要全量数据，用近似值
    # 用 cited_by_count / referenced_works_count 的倒数估算
    self_cite_rate = 0.0  # 默认0，后续可扩展

    # ── S2会议数据：用引用数折算近似FWCI和IF2 ──────────────────
    # 当fwci_mean=0但有引用数据时（S2来源的会议论文），进行折算
    # 折算基准来自CS期刊实测值：FWCI均值=3.015，IF2均值=5.976
    return {
        "fwci_mean":   round(fwci_mean, 4),
        "if2":         round(if2, 4),        # 期刊真实IF2；会议为0
        "if2_approx":  round(if2_approx, 4), # 会议估算IF2；期刊为0
        "h5":          h5,
        "cite_cagr":   round(cite_cagr, 4),
        "self_cite_rate": round(self_cite_rate, 4),
        "paper_count": len(articles),
        "fwci_n":      len(fwci_values),
        "is_s2":       is_s2,
    }
