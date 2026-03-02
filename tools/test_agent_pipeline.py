import subprocess
from pathlib import Path
import time
import uuid

questions = [
    # Case 1: 复杂协议细节检索
    "在 HS200 模式下，主机需要遵循什么样的 Tuning 流程？请详细列出。",

    # Case 2: 专业术语首字母缩写解释
    "BKOPS 是什么意思？它在 eMMC 里主要解决什么痛点？",

    # Case 3: 跨越多个规范版本的差异比对
    "eMMC 5.1 和 5.0 在 HS400 模式的定义与支持上有什么区别？",

    # Case 4: 规范中的寄存器数值换算
    "当前设备读取到的 BOOT_SIZE_MULT 寄存器值为 0x10，请问它的 Boot 分区实际有多大？",

    # Case 5: 无法回答的瞎编诱导 (幻觉防御验证)
    "在 eMMC 5.2 协议中，是否存在名叫 SUPER_TURBO_SPEED 的寄存器？",

    # Case 6: 并发/复合指令
    "请帮我解释 RPMB 是什么，顺便对比一下 eMMC 4.51 和 5.1 中 RPMB 分区大小的计算方法是否有变化。",

    # 回归测试 - 基础 RAG 替代
    "eMMC 的 Boot 分区大小怎么计算？",
    "HS_TIMING 寄存器各取值代表什么含义？",
    "CSD 寄存器的结构是什么？"
]

output_file = Path("docs/agent_full_test_results_v2.md")

def run_test():
    if output_file.exists():
        output_file.unlink()
        
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("# eMMC Protocol Copilot: Phase 3 Agent Test Results (v2)\n\n")
        f.write("Testing the link: Agent Graph -> Tools -> RAG / Calculate -> Prompt -> DeepSeek\n")
        f.write(f"- Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")


    for i, q in enumerate(questions, 1):
        print(f"[{i}/{len(questions)}] Running test: {q}")
        cmd = [
            "uv", "run", "python3", "-m", "emmc_copilot.agent.cli", "ask", q, "--verbose"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        
        with open(output_file, "a", encoding="utf-8") as f:
            f.write(f"## Q{i}: {q}\n\n")
            if result.returncode == 0:
                f.write("```text\n")
                f.write(result.stdout)
                f.write("\n```\n")
            else:
                f.write(f"**Error during execution:**\n```\n{result.stderr}\n```\n")
            f.write("\n---\n\n")

    print(f"\nDone! Full test report saved to: {output_file}")

if __name__ == "__main__":
    run_test()
