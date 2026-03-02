# eMMC 协议智能问答助手

基于 JEDEC JESD84 规范（4.51 / 5.0 / 5.1），提供：

- **寄存器/字段查询**：EXT_CSD、CSD、CID 任意字段含义与位定义
- **命令与流程**：CMD6、CMD46、HS200/HS400 调谐、RPMB 访问流程等
- **跨版本对比**：自动检索多版本规范并并排比较
- **公式计算**：Boot 分区大小、RPMB 容量、TRAN_SPEED 解码等
- **术语解释**：BKOPS、FFU、HPI、CMDQ 等缩写一键查询

## 示例问题

- `EXT_CSD[33] CACHE_CTRL 第 0 位的含义是什么？`
- `eMMC 5.0 和 5.1 在 Command Queuing 上有何区别？`
- `EXT_CSD[226]=32 时 Boot 分区有多大？`

右上角 ⚙️ 可切换规范版本（默认 5.1）。
