"""
config.py — 学科配置

评分公式（绝对分，不归一化）：
  score = 0.35 * fwci_mean
        + 0.25 * if2
        + 0.25 * log(1+h5)
        + 0.15 * log(1+max(cite_cagr,0))

  自引率>30%时乘以0.8惩罚系数。

分区规则（固定名额）：
  Q1: 排名第 1-50
  Q2: 排名第 51-150
  Q3: 排名第 151-300
  Q4: 排名第 301+
  不够不强行填满。

绝对分的意义：
  分数不随期刊池变化，新期刊加入后已有期刊分数不变，
  可直接按分数插入排名，稳定可复现。
"""

CS_CONFIG = {
    "field":      "computer science",
    "field_type": "cs",
    "years":      [2022, 2023, 2024],
    "data_dir":   "data/papers",

    "weights": {
        "fwci_mean":  0.35,
        "if2":        0.25,
        "h5":         0.25,
        "cite_cagr":  0.15,
    },

    "self_cite_threshold": 0.30,
    "self_cite_penalty":   0.80,
    "min_papers":          20,
}

MEDICAL_CONFIG = {
    "field":      "medicine",
    "field_type": "medical",
    "years":      [2022, 2023, 2024],
    "data_dir":   "data/papers",

    "weights": {
        "fwci_mean":  0.35,
        "if2":        0.25,
        "h5":         0.25,
        "cite_cagr":  0.15,
    },

    "self_cite_threshold": 0.30,
    "self_cite_penalty":   0.80,
    "min_papers":          20,
}
