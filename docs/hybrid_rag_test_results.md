# eMMC Protocol Copilot: Hybrid RAG Test Results

Testing the link: Hybrid Retrieval (Dense + BM25) -> format_docs_with_citations -> Prompt -> DeepSeek -> Answer with Citations
- n_results: 10
- Timestamp: 2026-03-01 20:34:26

## Q1: 找到 EXT_CSD 寄存器索引为 185 的字段名（HS_TIMING），并列出其 bit [3:0] 每一个取值的含义。

根据提供的上下文，EXT_CSD 寄存器索引 185 的字段名为 **HS_TIMING** [1][3][5][6][7]。关于其 bit [3:0] 每一个取值的含义，上下文仅提供了部分信息：

*   当取值为 **0x1** 时，表示 **High Speed** 时序接口 [4]。
*   当取值为 **0x2** 时，表示 **HS200** 时序接口 [2][6][7]。
*   当取值为 **0x3** 时，表示 **HS400** 时序接口 [10]。

上下文未提供 bit [3:0] 其他取值（如 0x0 等）的含义 [1][3][8][9]。

审核备注：Table 143 定义 HS_TIMING [185] 的 bit[3:0] 每一个取值的含义, 有 0x0 的定义，但是未检索到。
---

## Q2: What is the bit definition of the CACHE_CTRL [33] register? Focus on what bit 0 and bit 1 control.

Based on the provided context, the bit definition for the CACHE_CTRL [33] register is as follows:

- **Bit 0 (CACHE_EN)**: Controls turning the cache ON or OFF.
    - `0x0`: Cache is OFF [2][4][7]
    - `0x1`: Cache is ON [2][4][7]

- **Bit 1**: The context does not contain any information about what bit 1 of the CACHE_CTRL register controls. The excerpts only define bit 0 and state that bits 7-1 are reserved [8].

---

## Q3: EXT_CSD 寄存器中的 PARTITIONING_SUPPORT [160] 每一个 bit 分别代表支持什么分区功能？

根据提供的上下文，EXT_CSD 寄存器中 PARTITIONING_SUPPORT [160] 字段的 bit 定义如下：

*   **Bit 0 (PARTITIONING_EN)**：指示存储设备是否支持分区功能 [10]。
*   **Bit 1 (ENH_ATTRIBUTE_EN)**：指示存储设备是否在通用分区 (General Purpose Partitions) 和增强用户数据区 (Enhanced User Data Area) 中支持增强功能属性 [10]。
*   **Bit 2 (EXT_ATTRIBUTE_EN)**：指示存储设备是否在通用分区中支持扩展分区属性 [10]。
*   **Bit 7:3**：保留位 [9]。

对于 eMMC 4.51 设备，Bit 2-0 在 PARTITIONING_SUPPORT 中应设置为 1 [10]。eMMC 5.1 规范中的定义与此一致 [3][7]。

---

## Q4: Explain the purpose of BKOPS_EN [163] and list the difference between setting it to 0x01 vs 0x02.

Based on the provided context, the purpose of BKOPS_EN [163] is to allow the host to indicate to the device whether it is expected to periodically manually start background operations by writing to the BKOPS_START field [5][6][7].

Regarding the difference between setting it to 0x01 vs. 0x02:
- Setting BKOPS_EN to **0x01** means: "Host is indicating that it shall periodically write to BKOPS_START field to manually start background operations" [1][2][3].
- The provided context excerpts **do not contain any information** about the meaning or effect of setting BKOPS_EN to **0x02**. All descriptions only define the behavior for values 0x0 and 0x1.

---

## Q5: 在 CSD 寄存器中，哪一个字段占用了 [21:15] 位？它的作用是什么？

根据提供的上下文，CSD 寄存器中占用 [21:15] 位的字段信息未明确给出。上下文仅提到了 CSD 寄存器中位于 [21:21] 位的字段 `WRITE_BL_PARTIAL`（允许部分块写入）[2][4][6]，但没有说明 [21:15] 这整个位范围对应的字段名称和作用。

因此，基于提供的资料，无法回答 CSD 寄存器中 [21:15] 位字段的名称和作用。

---

## Q6: 根据协议中关于 TRAN_SPEED 的描述，解释频率单位编码 3 代表多少 MHz，以及乘数编码 0xA (10) 对应哪个具体的乘数值？

根据提供的上下文，TRAN_SPEED 字段中频率单位编码 3 代表 **100 MHz** [1][3][4]。乘数编码 0xA（十进制 10）对应的乘数值是 **4.5** [4][6]。

---

## Q7: What does the value 0x07 in DEVICE_LIFE_TIME_EST_TYP_A represent in terms of percentage?

根据提供的上下文，DEVICE_LIFE_TIME_EST_TYP_A 寄存器中值 0x07 表示设备寿命已使用 60% 至 70% [1][2][3][4][8][10]。

---

## Q8: FFU_ARG 寄存器占用了多少个字节？它的字节顺序（Endianness）是怎样的？

FFU_ARG 寄存器占用 4 个字节 [3][4][5][10]。根据提供的上下文，没有明确说明其字节顺序（Endianness）的具体信息。

---

## Q9: Identify the maximum current for VCC during Sleep Mode if the S_C_VCC register value is 0x05.

根据提供的上下文，当 S_C_VCC 寄存器值为 0x05 时，睡眠电流的计算公式为：睡眠电流 = 1µA × 2^X，其中 X 为寄存器值 [1][2][3]。

因此，对于寄存器值 0x05（即 X = 5）：
睡眠电流 = 1µA × 2^5 = 1µA × 32 = 32 µA。

最大定义的寄存器值为 0x0D，对应 8.192 mA [1][2][3][6][7][10]。值 0x05 在有效范围内，其对应的最大电流为 32 µA。

---

## Q10: PWR_CL_52_180 中 PWR_CL_52_180 字段在 EXT_CSD 中的索引是多少？它描述了什么工作频率下的功耗？

根据提供的上下文，没有信息表明存在名为“PWR_CL_52_180”的字段。上下文提到了以下相关的功耗类别字段：
- `PWR_CL_52_360`：位于EXT_CSD索引[202]，描述52MHz频率在3.6V下的功耗类别 [1][3][7]。
- `PWR_CL_52_195`：位于EXT_CSD索引[200]，描述52MHz频率在1.95V下的功耗类别 [5]。
- `PWR_CL_DDR_52_360`：位于EXT_CSD索引[239]，描述52MHz DDR模式在VCC=3.6V下的功耗类别 [9]。

因此，关于“PWR_CL_52_180”的索引及其描述的工作频率和电压，在提供的上下文中没有足够的信息来回答。

---

## Q11: 详细对比 CMD0 参数为 0x00000000 和 0xF0F0F0F0 时，协议中对“设备复位”状态机转换的文字描述。

根据提供的上下文，CMD0参数为0x00000000和0xF0F0F0F0时，关于“设备复位”状态机转换的文字描述对比如下：

### CMD0 参数为 0x00000000
*   **功能**：这是GO_IDLE_STATE命令。接收到此命令后，设备会进入Idle状态（Idle State）[1][2][3]。
*   **有效性**：该命令在所有状态下都有效，除了Inactive状态（Inactive State）。在Inactive状态下，设备不接受此命令[1][2][3]。
*   **状态转换**：
    *   在**非Inactive状态**下，接收此命令会使设备移动到Idle状态[1][2][3]。
    *   在**Boot状态（boot）** 下，如果主机使用了替代引导模式（alternative boot mode）且设备因读取完整个引导分区而自动进入Idle状态，则主机随后发出的**第一个**CMD0（arg=0x00000000）**不应**重置总线条件（如果RESET_BOOT_BUS_CONDITIONS设置为保留）。在其他情况下（如原始引导模式、或替代引导模式下此后的CMD0），此命令会将总线条件重置为x1 SDR模式[8]。
*   **特殊情况**：出于向后兼容性原因，如果设备在除Inactive状态外的任何状态下接收到参数不是0xFFFFFFFA或0xF0F0F0F0的CMD0，设备应将其视为设备复位命令并移动到Idle状态[1][2][3][6][7]。

### CMD0 参数为 0xF0F0F0F0
*   **功能**：此命令被描述为与硬件复位（Hardware Reset）效果相同[9][10]。在状态图（Figure 25）中，它与RESET信号并列，用于从除Inactive状态外的所有状态转换到Pre-idle状态（Pre-idle State）[4]。
*   **状态转换**：
    *   根据状态图（boot mode），此命令（或硬件复位）可以使设备从**除Inactive状态外的所有状态**转换到Pre-idle状态[9][10]。
    *   在设备识别模式（Device identification mode）的状态图中，此命令（或RESET信号）被标示为可以从Identification mode转换出来[4]。
*   **文字描述中的处理**：协议明确指出，如果设备在除Inactive状态外的任何状态下接收到参数为**其他值**（即不是0xFFFFFFFA或0xF0F0F0F0）的CMD0，才会被当作设备复位命令。这间接说明参数为0xF0F0F0F0的CMD0**不被视为**标准的“Device reset command”（即不会直接进入Idle状态），而是触发一个不同的复位路径（进入Pre-idle状态）[1][2][3][6][7]。

### 总结对比
| 特性 | CMD0 (arg=0x00000000) | CMD0 (arg=0xF0F0F0F0) |
| :--- | :--- | :--- |
| **主要功能** | GO_IDLE_STATE（设备复位）[1][2][3] | 等效于硬件复位[9][10] |
| **目标状态** | Idle状态（Idle State）[1][2][3] | Pre-idle状态（Pre-idle State）[9][10] |
| **有效性例外** | 在Inactive状态下无效[1][2][3] | 上下文未明确说明在Inactive状态下是否有效，但状态图显示从“所有状态除inactive”转换[9][10] |
| **在复位规则中的角色** | 是标准的设备复位命令[1][2][3] | 是特殊的复位命令，不被归类为上述“Device reset command”规则的一部分[1][2][3][6][7] |
| **对引导总线条件的影响** | 在特定条件下可能保留引导总线设置[8] | 上下文未提供具体描述，但作为硬件复位，很可能重置所有配置。 |

**关键区别**：CMD0(arg=0x00000000)直接使设备进入**Idle状态**，是常规的软件复位。而CMD0(arg=0xF0F0F0F0)模拟硬件复位，使设备回到更初始的**Pre-idle状态**，这通常是上电或硬件复位后的起点[9][10]。

---

## Q12: What specific error bit in the Device Status register is set if CMD46 is sent with a non-existent Task ID?

根据提供的上下文，当CMD46发送了一个不存在的Task ID时，设备会以“无响应”（No Response）和“非法命令”（Illegal Command）来处理此错误 [4, 6]。然而，上下文并未明确指出在Device Status寄存器中具体设置哪个错误位。提供的章节[7]、[8]、[10]描述了Device Status位的通用类型（错误位/状态位）和检测模式（响应模式/执行模式），但未列出与CMD46参数错误（如非存在的Task ID）相对应的具体位定义。

因此，基于所给信息，无法确定具体设置哪个错误位。

---

## Q13: 当 CMD6 返回 SWITCH_ERROR 时，可能的原因有哪些？请至少列举 4 种。

根据提供的上下文，当 CMD6 返回 SWITCH_ERROR 时，可能的原因包括：

1.  **请求切换到无效或不受支持的模式**：如果 SWITCH 命令尝试设置的参数值无效，例如在 CACHE_CTRL 或 POWER_OFF_NOTIFICATION 等扩展控制字中设置了保留位，将导致 SWITCH_ERROR [4][9]。
2.  **在非中断命令执行期间尝试切换**：根据 HPI 表格，对于大多数 SWITCH 命令（除了特定的字节和值，如 BKOPS_START、SANITIZE_START 等），CMD6 是不可中断的。如果在这些“不可中断”的 SWITCH 命令执行期间尝试发送另一个 CMD6 进行模式切换，可能会导致错误 [5][6][7][8][10]。虽然上下文未明确说明这会直接导致 SWITCH_ERROR，但这是 CMD6 执行失败的一个潜在场景。
3.  **设备未能切换到请求的模式**：这是 SWITCH_ERROR 状态位的直接定义。当设备未能按照 SWITCH 命令的要求切换到预期模式时，该位被置为“1” [1][2][3]。
4.  **尝试在特定不可中断的 SWITCH 操作期间进行切换**：例如，对于 POWER_OFF_NOTIFICATION 字节，除了值为 POWER_OFF_LONG 或 SLEEP_NOTIFICATION 的情况外，其他值的 SWITCH 操作都是不可中断的。在此期间尝试另一个 CMD6 可能导致问题 [6][7][10]。

**注意**：上下文没有提供导致 SWITCH_ERROR 的所有可能原因的完整列表。以上列举是基于所提供片段中明确提到的或可合理推断出的情况。特别是，原因 2 和 4 是基于命令中断性规则对并发操作影响的推断，上下文并未直接声明这些操作失败会设置 SWITCH_ERROR 位。

---

## Q14: For FFU (Field Firmware Update), what is the exact required value for the MODE_CONFIG [161] register to enter FFU mode?

根据提供的上下文，进入FFU模式时，需要将MODE_CONFIG寄存器设置为0x01。具体来说，在eMMC 5.0规范中，表170明确列出了MODE_CONFIG的有效值，其中0x01对应"FFU Mode" [8]。

---

## Q15: 解释 CMDQ_MODE_EN [15] 位被置 1 后，原来的 CMD17 和 CMD18 命令是否还能使用？

根据提供的上下文，当 CMDQ_MODE_EN [15] 位被置为 1（即命令队列模式启用）时，原来的 CMD17 和 CMD18 命令**不能使用**，它们被视为非法命令（Illegal）[1, 6, 8]。

具体规定如下：
- 当命令队列启用（CMDQ_MODE_EN 设为 1）且任务队列为空（Empty）时，CMD17 和 CMD18 的状态为 "Illegal" [1, 8]。
- 当命令队列启用且任务队列非空（Non-empty）时，"所有其他命令"（包括 CMD17 和 CMD18）的状态也为 "Illegal" [1, 8]。
- 上下文明确指出，当命令队列启用时，现有的数据传输命令（即 CMD18/CMD17 和 CMD25/CMD24）**不受支持**（are not supported）[6]。此时，只有类别 11（Class 11）命令是发出数据传输任务的唯一方法[6]。

---

## Q16: Which fields were deprecated or became 'Reserved' in eMMC 5.1 compared to 5.0?

根据提供的上下文，没有信息表明在 eMMC 5.1 与 5.0 的比较中有任何字段被弃用或变为“保留”。上下文仅列出了 eMMC 5.1 中新增的功能和澄清，例如命令队列、增强型选通等 [10]，但没有提及任何字段被移除或保留。因此，基于给定信息，无法回答哪些字段在 eMMC 5.1 中被弃用或变为保留。

---

## Q17: 在 eMMC 5.1 协议中，Command Queuing 的队列深度最大是多少？引用具体章节说明。

在 eMMC 5.1 协议中，Command Queuing 的队列深度最大是 32。根据 7.4.19 CMDQ_DEPTH [307] 的描述：“The maximum depth allowed by the standard is 32” [9]。

---

## Q18: List all the CARD_TYPE bits defined for HS400. Which bit corresponds to HS400 1.8V support?

根据提供的上下文，HS400 的 CARD_TYPE 位在 DEVICE_TYPE [196] 寄存器中定义。

- 位 6 对应 **HS400 Dual Data Rate e*MMC @ 200MHz - 1.8V I/O** [2]。
- 位 7 对应 **HS400 Dual Data Rate e*MMC @ 200MHz - 1.2V I/O** [2][5]。

因此，所有为 HS400 定义的 CARD_TYPE 位是位 6 和位 7。其中，位 6 对应 HS400 1.8V I/O 支持。

---

## Q19: 找到 eMMC 4.51 文档，对于“Sanitize”操作描述的最小超时时间是多少？

根据提供的上下文，没有信息表明 eMMC 4.51 文档中定义了“Sanitize”操作的最小超时时间。所提供的 eMMC 4.51 相关摘录仅列出了 Sanitize 命令的寄存器位置（SANITIZE_START[165]）[1][6][9]，但没有包含关于操作超时时间的描述。eMMC 5.0 和 5.1 的摘录详细说明了 Sanitize 操作的流程和中断条件，但同样未提及具体的超时时间值[3][5]。因此，基于给定资料，无法回答此问题。

---

## Q20: Explain the Cache Barrier enablement. Which register and bit must be set, and what is the default state after power-up?

To enable the Cache Barrier function, the host must set bit 0 of the BARRIER_EN register (EXT_CSD byte [31]) [7]. The default state of this bit after power-up is not explicitly stated in the provided context.

---

---

## 人工审核结论（2026-03-01）

### 总体评分

| 等级 | 题目 | 数量 |
|------|------|------|
| 正确 | Q2、Q3、Q6、Q7、Q9、Q11、Q14、Q15、Q16、Q17、Q18 | 11 |
| 轻微不足 | Q8、Q10、Q13 | 3 |
| 严重遗漏（检索未命中） | Q1、Q4、Q5、Q12、Q19、Q20 | 6 |

---

### 严重遗漏（检索未命中正确 chunk）

**Q1 — HS_TIMING [185] bit[3:0]**
缺少 `0x0 = Backwards compatible interface timings` 的定义（Table 143）。仅答出 0x1/0x2/0x3，漏掉默认值 0x0。

**Q4 — BKOPS_EN [163] 值 0x02**
答案声称"找不到 0x02 的含义"。eMMC 5.0/5.1 规范明确定义：
- `0x01`：Host 手动周期性触发 BKOPS_START（已答出）
- `0x02`：**Auto Background Operations 使能**（设备自动管理，无需 Host 定期干预）

**Q5 — CSD [21:15] 多字段未识别**
答案将 [21:15] 误当作单一字段查找，实际对应多个独立字段：
- [21:21] `WRITE_BL_PARTIAL`（答案提到但未作为答案输出）
- [20:20] `FILE_FORMAT_GRP`
- [19:19] `COPY`
- [18:18] `PERM_WRITE_PROTECT`
- [17:17] `TMP_WRITE_PROTECT`
- [16:15] `FILE_FORMAT`（2 bits）

**Q12 — CMD46 非法 Task ID 的 Device Status 错误位**
答案只说"返回 Illegal Command"但未给出具体 bit 编号。规范 Device Status 寄存器 **bit 22 = `ILLEGAL_COMMAND`**，这是 CMD46 收到非法参数时应置位的 bit。

**Q19 — eMMC 4.51 Sanitize 最小超时**
答案直接放弃。B451 文档中应有对应的超时描述，属于检索遗漏。

**Q20 — BARRIER_EN [31] 上电默认值**
答案称"未明确说明"，但规范明确：上电默认值为 **0（disabled）**。EXT_CSD 表的 Properties 列含 power-on value 信息，检索未命中。

---

### 轻微不足

**Q8 — FFU_ARG [491:488] 字节序**
答案称"未找到"。eMMC 规范对多字节 EXT_CSD 字段的统一约定为小端：低索引字节为 LSByte，即 byte 488 = LSByte，byte 491 = MSByte。

**Q10 — PWR_CL_52_180 不存在**
结论正确，但措辞过于模糊（"没有足够信息"）。应明确：**eMMC 规范中无此字段**，52MHz 功耗类寄存器仅有 `PWR_CL_52_360 [202]` 和 `PWR_CL_52_195 [200]`。

**Q13 — SWITCH_ERROR 成因**
列举的第 3 条（"设备未能切换到请求的模式"）是 SWITCH_ERROR 的**定义**而非成因，属于循环论证。遗漏了常见成因：**向只读字节（R 类型 EXT_CSD 字节）写入**。

---

### 根因分析

| 问题类别 | 受影响题目 | 原因 |
|---------|-----------|------|
| BM25 + Dense 均未命中目标 chunk | Q4、Q12、Q19 | 相关寄存器行级 chunk 未被召回 |
| 检索到表但 LLM 未正确逐行解析 | Q1、Q5 | 多字段表未逐行对应输出 |
| 检索到章节但缺少属性列（默认值） | Q20 | EXT_CSD 表 Properties 列 chunk 未命中 |
| LLM 推理不足（上下文已有但未利用） | Q8、Q10、Q13 | 需要跨 chunk 推断或使用领域通用约定 |

---

### 改进方向

1. **Q1/Q5 类（表格解析不足）**：TABLE chunk 的 `table_markdown` 字段应单独建 BM25 索引；或检索后对原始表格做精确字段匹配，确保逐行提取。
2. **Q4/Q12/Q19 类（召回遗漏）**：`n_candidates` 从 20 提升至 30–40；对含精确数值的查询（`0x02`、`bit 22`）考虑 query expansion 或关键字增强。
3. **Q20 类（属性列缺失）**：EXT_CSD 字段的 power-on value、R/W 属性应在 chunk metadata 中显式存储，而非依赖全文检索。
4. **Q8/Q10/Q13 类（LLM 推理不足）**：在 system prompt 中注入规范领域约定（如多字节字段小端规则、不存在字段应明确否定），引导 LLM 在上下文不足时利用领域知识补充。
