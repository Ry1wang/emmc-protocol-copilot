import subprocess
from pathlib import Path
import os
import time

questions = [
    # 维度 1: 寄存器与位定义定位 (针对先前 Q2/Q5 失败点)
    "找到 EXT_CSD 寄存器索引为 185 的字段名（HS_TIMING），并列出其 bit [3:0] 每一个取值的含义。",
    "What is the bit definition of the CACHE_CTRL [33] register? Focus on what bit 0 and bit 1 control.",
    "EXT_CSD 寄存器中的 PARTITIONING_SUPPORT [160] 每一个 bit 分别代表支持什么分区功能？",
    "Explain the purpose of BKOPS_EN [163] and list the difference between setting it to 0x01 vs 0x02.",
    "在 CSD 寄存器中，哪一个字段占用了 [21:15] 位？它的作用是什么？",

    # 维度 2: 技术术语与固定数值 (针对先前 Q4/Q1 失败点)
    "根据协议中关于 TRAN_SPEED 的描述，解释频率单位编码 3 代表多少 MHz，以及乘数编码 0xA (10) 对应哪个具体的乘数值？",
    "What does the value 0x07 in DEVICE_LIFE_TIME_EST_TYP_A represent in terms of percentage?",
    "FFU_ARG 寄存器占用了多少个字节？它的字节顺序（Endianness）是怎样的？",
    "Identify the maximum current for VCC during Sleep Mode if the S_C_VCC register value is 0x05.",
    "PWR_CL_52_180 中 PWR_CL_52_180 字段在 EXT_CSD 中的索引是多少？它描述了什么工作频率下的功耗？",

    # 维度 3: 复杂协议命令细节 (针对先前 Q13/Q20 失败点)
    "详细对比 CMD0 参数为 0x00000000 和 0xF0F0F0F0 时，协议中对“设备复位”状态机转换的文字描述。",
    "What specific error bit in the Device Status register is set if CMD46 is sent with a non-existent Task ID?",
    "当 CMD6 返回 SWITCH_ERROR 时，可能的原因有哪些？请至少列举 4 种。",
    "For FFU (Field Firmware Update), what is the exact required value for the MODE_CONFIG [161] register to enter FFU mode?",
    "解释 CMDQ_MODE_EN [15] 位被置 1 后，原来的 CMD17 和 CMD18 命令是否还能使用？",

    # 维度 4: 版本演进与规格上限 (针对先前 Q17/Q5 失败点)
    "Which fields were deprecated or became 'Reserved' in eMMC 5.1 compared to 5.0?",
    "在 eMMC 5.1 协议中，Command Queuing 的队列深度最大是多少？引用具体章节说明。",
    "List all the CARD_TYPE bits defined for HS400. Which bit corresponds to HS400 1.8V support?",
    "找到 eMMC 4.51 文档，对于“Sanitize”操作描述的最小超时时间是多少？",
    "Explain the Cache Barrier enablement. Which register and bit must be set, and what is the default state after power-up?"
]

output_file = Path("docs/hybrid_rag_test_results_v2.md")

def run_test():
    if output_file.exists():
        output_file.unlink()
        
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("# eMMC Protocol Copilot: Hybrid RAG Test Results (V2)\n\n")
        f.write("Testing the link: Hybrid Retrieval (Dense + BM25) -> format_docs_with_citations -> Prompt -> DeepSeek -> Answer with Citations\n")
        f.write(f"- n_results: 10\n")
        f.write(f"- Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")

    for i, q in enumerate(questions, 1):
        print(f"[{i}/20] Running test: {q}")
        cmd = [
            "uv", "run", "python3", "-m", "emmc_copilot.qa.cli", "ask", q
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        
        with open(output_file, "a", encoding="utf-8") as f:
            f.write(f"## Q{i}: {q}\n\n")
            if result.returncode == 0:
                output = result.stdout
                if "[回答]" in output:
                    answer = output.split("[回答]")[1].strip()
                    f.write(answer)
                else:
                    f.write(output)
            else:
                f.write(f"**Error during execution:**\n```\n{result.stderr}\n```")
            f.write("\n\n---\n\n")

    print(f"\nDone! Full test report saved to: {output_file}")

if __name__ == "__main__":
    run_test()
