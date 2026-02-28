# eMMC Protocol Copilot V2

eMMC 协议智能问答 Agent.

## 总体架构思路
```
eMMC 文档（PDF/规范书）
        ↓
   文档解析 & 切片
        ↓
   向量化 & 存储（RAG核心）
        ↓
   检索增强生成（LLM回答）
        ↓
   Agent 编排（工具调用、多轮对话）
        ↓
   前端界面（可选）
```

