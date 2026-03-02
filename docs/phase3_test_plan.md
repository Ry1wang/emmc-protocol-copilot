# Phase 3 Agent 测试方案

## 1. 测试目标
在 Phase 3 (Agent 化) 开发完成后，通过本测试方案系统性地验证基于 LangGraph 构建的多工具 Agent 是否能够按预期进行意图识别、正确调用对应的 Tool、解决复杂类型的协议查阅问题，并正常处理多轮跨版本的上下文追问。

## 2. 测试环境及准备
1. **基础数据**：确保 `data/vectorstore/chroma` 及 `data/vectorstore/bm25` 已构建完毕，包含 eMMC 4.51、5.0、5.1 三个版本的 chunk。
2. **测试脚本**：使用 `emmc_copilot.agent.cli` 提供的 `ask` (单轮独立测试) 与 `chat` (多轮上下文测试) 命令进行测试。
3. **日志观测**：运行测试时使用 `--verbose` / `-v` 标志，终端会以 `[tool] name(args...)` 格式打印每次工具调用及结果摘要，用于核对大模型是否触发了正确的工具。

---

## 3. 核心工具选路测试 (单轮问答)

本轮测试验证大模型是否能准确从 4 个 Tool (文档检索、术语解释、版本对比、规范计算) 中做出选择，以及各 Tool 自身返回机制的健壮性。

### Case 1: 复杂协议细节检索 (工具选择预期: `search_emmc_docs`)
*   **输入**: `"在 HS200 模式下，主机需要遵循什么样的 Tuning 流程？请详细列出。"`
*   **验收标准**:
    *   明确触发了 `search_emmc_docs` 工具。
    *   正确列出基于 CMD21 的 Tuning 流程（如需要检查哪几块寄存器、发送多少次 CMD21 等）。
    *   附带了以 `[B51 §X.X p.N]` 或类似格式说明文档出处。

### Case 2: 专业术语首字母缩写解释 (工具选择预期: `explain_term` → (可选) `search_emmc_docs`)
*   **输入**: `"BKOPS 是什么意思？它在 eMMC 里主要解决什么痛点？"`
*   **验收标准**:
    *   优先触发了 `explain_term("BKOPS")` 以获取精准短定义。
    *   根据返回情况，如定义不够解决“用途/痛点”，大模型自主发起了第二次工具调用 `search_emmc_docs` 获取背景故事。
    *   最终回答明确指出 BKOPS 指 Background Operations（后台操作），用于在闲暇时执行垃圾回收（GC）和磨损均衡以避免性能抖动。

### Case 3: 跨越多个规范版本的差异比对 (工具选择预期: `compare_versions`)
*   **输入**: `"eMMC 5.1 和 5.0 在 HS400 模式的定义与支持上有什么区别？"`
*   **验收标准**:
    *   明确触发了 `compare_versions(feature="HS400")` 工具。
    *   输出中展示了 **eMMC 5.0**（首次引入 HS400, Data Strobe 等）与 **eMMC 5.1**（引入 HS400 增强选通 Enhanced Strobe 等）的差异对比。
    *   不缺失版本号标识。

### Case 4: 规范中的寄存器数值换算 (工具选择预期: `calculate`)
*   **输入**: `"当前设备读取到的 BOOT_SIZE_MULT 寄存器值为 0x10，请问它的 Boot 分区实际有多大？"`
*   **验收标准**:
    *   明确触发了 `calculate(formula="boot_size", boot_size_mult=16)` 工具。（大模型应自动将 0x10 转换为整数 16 传入参数）
    *   回答给出了计算过程："128 KB × 16 = 2048 KB = 2 MB"。

---

## 4. 多轮对话能力测试 (REPL 交互)

使用 `chat` 模式，验证 `AgentState` 消息历史的管理、线程记忆 (`thread_id`) 以及跨版本的无缝追问。

### 连续追问组 1：上下文继承与记忆
*   **User**: `"什么是 FFU？"`
    *   *AI*: (使用 `explain_term` 回答 FFU 是 Field Firmware Update)。
*   **User**: `"进入这种模式需要配置哪个寄存器的哪个位？"`
    *   *AI*: (继承上次的 FFU 主题，调用 `search_emmc_docs("FFU mode register config")`，回答 MODE_CONFIG [161] 需设置为 0x01)。
*   **User**: `"那这个操作最大需要等待多久（即超时时间怎么算）？"`
    *   *AI*: (依然继承 FFU 主题，检索 FFU timeout 相关字段如 FFU_TIMEOUT 等)。

### 连续追问组 2：从单点事实发散为版本比对
*   **User**: `"CACHE_CTRL [33] 寄存器有什么用？"`
    *   *AI*: (解答 Bit 0 用于开/关缓存)。
*   **User**: `"eMMC 4.51 版本也有这个功能吗？"`
    *   *AI*: (自动调用 `compare_versions("CACHE_CTRL")` 或带有 `version="4.51"` 的 `search_emmc_docs`，并明确回复 4.51 版本是否存在此功能)。

---

## 5. 极端场景边界测试 (降压测试)

### Case 5: 无法回答的瞎编诱导 (幻觉防御验证)
*   **输入**: `"在 eMMC 5.2 协议中，是否存在名叫 SUPER_TURBO_SPEED 的寄存器？"`
*   **验收标准**:
    *   AI 调用了查询工具，但在未召回有效内容的情况下，**坚决承认**规范中（截止 5.1）没有此寄存器。
    *   绝对不伪造一段莫须有的寄存器说明。

### Case 6: 并发/复合指令
*   **输入**: `"请帮我解释 RPMB 是什么，顺便对比一下 eMMC 4.51 和 5.1 中 RPMB 分区大小的计算方法是否有变化。"`
*   **验收标准**:
    *   大模型发出两个工具调用：`explain_term("RPMB")` 以及 `compare_versions("RPMB size calculation", "4.51,5.1")`。
    *   **首选**：在单次 AIMessage 中并行（Parallel）发出两个 tool_calls，LangGraph ToolNode 并发执行。
    *   **降级可接受**：若 DeepSeek 不支持单次并行调用，改为两次顺序调用，最终答案同样需合并两个工具结果，不视为失败。
    *   合并工具结果，有条理地输出最终合并答案。

---

## 6. 回归保障指标 (与 Phase 2 对齐)

除了验证能够调用工具，回答必须依然满足 Phase 2 建立的”刚需标准”：
1.  **引用准确度**: 回答中依然具备类似于 `[B51 §7.4.22 p.123]` 的内联标号（由工具返回的 Cite-as 标签直接引用）。
2.  **内容完整度**: 若遇类似表格形式列举的多个配置位，不能中途截断（如仅解释了 bit 0，丢失了 bit 1），需把 `0x0`, `0x1` ...等可能的取值一并反馈。
3.  **Phase 2 基线回归**：将以下 Phase 2 已通过的代表性问题通过 `agent.cli ask` 运行，答案质量不低于 Phase 2 基线：
    *   Q3：`”eMMC 的 Boot 分区大小是多少？”` (触发 `search_emmc_docs` → 含 BOOT_SIZE_MULT 公式)
    *   Q6：`”HS_TIMING 寄存器各取值代表什么含义？”` (触发 `search_emmc_docs` → 正确列出 0x00/0x01/0x02/0x03)
    *   Q10：`”CSD 寄存器的结构是什么？”` (触发 `search_emmc_docs` → 含 CSD 字段描述)

## 7. 测试执行步骤总结

1. 将上述独立问答整理进 Python 脚本 `tools/test_agent_pipeline.py`（参考 Phase 2 的 `tools/test_rag_pipeline.py` 结构）。
2. 执行批量自动化测试，输出为 `docs/agent_full_test_results.md`。
3. 手动 `chat` 执行多轮追问测试。
4. 核对各个 Case 验收标准后，方可宣布 Phase 3 Agent 化开发达成。
