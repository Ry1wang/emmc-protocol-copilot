# RAGAS 评测报告

**生成时间**: 2026-03-02 17:54  
**评测样本数**: 20  
**评测 Pipeline**: dense_rag, hybrid_rag, agent  

---

## 一、汇总指标对比（各 Pipeline）

| Pipeline | Faithfulness | AnswerRelevancy | ContextPrecision | ContextRecall |
|----------|:------------:|:---------------:|:----------------:|:-------------:|
| Dense-only RAG (baseline) | 0.5923 | 0.8377 | 0.5910 | 0.3492 |
| Hybrid RAG (BGE-M3 + BM25 + RRF) | 0.6452 | 0.7878 | 0.6736 | 0.2900 |
| LangGraph Agent (4 tools) | 0.8495 | 0.8082 | 0.8321 | 0.6303 |


## 二、按问题类型聚合（hybrid_rag）

*注：计算题和边界题的 Recall 指标可能因答案较短而偏低，重点关注 factual / comparison 类。*

| Type | N | Faithfulness | AnswerRelevancy | ContextPrecision | ContextRecall |
|------|:-:|:------------:|:---------------:|:----------------:|:-------------:|
| `factual` | 9 | 0.6377 | 0.7796 | 0.6130 | 0.2148 |
| `calculation` | 4 | 0.6489 | 0.6115 | 0.9389 | 0.6292 |
| `comparison` | 4 | 0.6292 | 0.9263 | 0.7500 | 0.2125 |
| `edge_case` | 3 | 0.6842 | 0.8627 | 0.4000 | 0.1667 |


## 三、Hybrid vs Dense 提升量（Δ）

| 指标 | Dense-only | Hybrid RAG | Δ |
|------|:----------:|:----------:|:-:|
| Faithfulness | 0.5923 | 0.6452 | +0.0529 |
| AnswerRelevancy | 0.8377 | 0.7878 | -0.0499 |
| ContextPrecision | 0.5910 | 0.6736 | +0.0826 |
| ContextRecall | 0.3492 | 0.2900 | -0.0592 |


## 四、逐题评分明细（hybrid_rag）

| ID | Type | Faithfulness | AnswerRelevancy | ContextPrecision | ContextRecall | 问题摘要 |
|----|------|:------------:|:---------------:|:----------------:|:-------------:|----------|
| Q01 | `factual` | 0.9592 | 0.8104 | 1.0000 | 0.0000 | 在 HS200 模式下，主机需要遵循什么样的 Tuning … |
| Q02 | `factual` | 0.1667 | 0.8981 | 0.2000 | 0.0000 | BKOPS 是什么意思？它在 eMMC 里主要解决什么痛点？ |
| Q03 | `comparison` | 0.2667 | 0.9744 | 0.5000 | 0.0000 | eMMC 5.1 和 5.0 在 HS400 模式的定义与支… |
| Q04 | `calculation` | 0.8750 | 0.0000 | 1.0000 | 0.6667 | 当前设备读取到的 BOOT_SIZE_MULT 寄存器值为 … |
| Q05 | `edge_case` | 0.8000 | 0.8229 | 0.3333 | 0.0000 | 在 eMMC 5.2 协议中，是否存在名叫 SUPER_TU… |
| Q06 | `comparison` | 0.7500 | 0.8447 | 1.0000 | 0.2500 | 请帮我解释 RPMB 是什么，顺便对比一下 eMMC 4.5… |
| Q07 | `calculation` | 0.4706 | 0.9003 | 0.9500 | 0.6000 | eMMC 的 Boot 分区大小怎么计算？ |
| Q08 | `factual` | 0.4286 | 0.6248 | 1.0000 | 0.0000 | HS_TIMING 寄存器各取值代表什么含义？在操作上有什么… |
| Q09 | `factual` | 0.7200 | 0.6736 | 0.7500 | 0.3333 | CSD 寄存器的结构是什么？它包含哪些主要字段？ |
| Q10 | `factual` | 0.6875 | 0.6486 | 1.0000 | 0.4000 | CACHE_CTRL [33] 寄存器 Bit 0 的含义是… |
| Q11 | `factual` | 0.6400 | 0.8714 | 0.2000 | 0.5000 | MODE_CONFIG [30] 寄存器进入 FFU 模式的… |
| Q12 | `calculation` | 0.2500 | 0.6836 | 1.0000 | 0.7500 | 设备 GENERIC_CMD6_TIME [248] 寄存器… |
| Q13 | `factual` | 0.6053 | 0.8066 | 0.0000 | 0.2000 | eMMC 的 Command Queuing（CQ）功能是什… |
| Q14 | `comparison` | 0.6667 | 0.9124 | 0.5000 | 0.0000 | RPMB_SIZE_MULT 在 eMMC 4.51 和 5… |
| Q15 | `factual` | 0.6875 | 0.7246 | 0.5000 | 0.2500 | S_C_VCC [143] 寄存器如何编码睡眠模式电流？最大… |
| Q16 | `calculation` | 1.0000 | 0.8622 | 0.8056 | 0.5000 | 某设备的 S_C_VCC [143] 值为 5，该设备睡眠模… |
| Q17 | `factual` | 0.8444 | 0.9583 | 0.8667 | 0.2500 | eMMC 设备的 Sanitize 操作是什么？它与普通 E… |
| Q18 | `edge_case` | 0.5385 | 0.9637 | 0.0000 | 0.2500 | eMMC 4.51 协议中是否支持 HS400 模式？ |
| Q19 | `comparison` | 0.8333 | 0.9739 | 1.0000 | 0.6000 | eMMC 5.0 和 5.1 在 Enhanced Stro… |
| Q20 | `edge_case` | 0.7143 | 0.8015 | 0.8667 | 0.2500 | 如果主机在切换到 HS200 模式后不执行 Tuning 直… |


---

## 免责声明

> 本评测中担任 Judge（裁判）和 Generator（生成器）的模型均为 **DeepSeek**，
> 指标可能包含一定的「自我偏好偏差」（Self-Preference Bias）。
> 本报告的核心价值在于：**相同模型基座下，不同检索策略之间的相对性能提升（Δ）对比**，
> 绝对分值仅供参考，不代表在独立第三方 Judge 下的客观评分。
