# eMMC RAG Agent

基于 RAG (Retrieval-Augmented Generation) 的 eMMC 协议智能问答系统，支持自动生成测试用例。

## 🌟 特性

- **混合检索**：语义搜索 + 关键词过滤 + Cross-Encoder 重排序
- **流式对话**：ChatGPT 风格的打字机效果
- **代码生成**：基于 Function Calling 自动生成 Python 测试用例
- **多模态展示**：文本、表格、图片、代码高亮
- **容器化部署**：Docker + Docker Compose 一键部署
- **微服务架构**：FastAPI 后端 + Streamlit 前端

## 📋 系统架构

```
┌─────────────────────────────────────────┐
│  Streamlit 前端 (localhost:8501)        │
│  - 聊天界面                              │
│  - 参数配置                              │
│  - 流式显示                              │
└──────────────┬──────────────────────────┘
               │ HTTP/SSE
               ↓
┌─────────────────────────────────────────┐
│  FastAPI 后端 (localhost:8000)          │
│  - /chat_stream (流式问答)               │
│  - /generate_code (代码生成)             │
│  - /health (健康检查)                    │
└──────────────┬──────────────────────────┘
               │
               ↓
┌─────────────────────────────────────────┐
│  RAG Engine (rag_chat_v3.py)            │
│  - Hybrid Search (向量 + 关键词)         │
│  - Cross-Encoder Reranking              │
│  - LLM Streaming (逐字输出)              │
│  - Function Calling (代码生成)           │
└─────────────────────────────────────────┘
```

## 🚀 快速开始

### 方法 1: Docker 部署（推荐）

```bash
# 1. 克隆项目
git clone <your-repo-url>
cd eMMC_RAG_Agent

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 文件，添加你的 DEEPSEEK_API_KEY

# 3. 启动服务
docker-compose up -d

# 4. 访问服务
# Streamlit 前端: http://localhost:8501
# FastAPI 文档: http://localhost:8000/docs
```

### 方法 2: 本地开发

```bash
# 1. 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env 文件

# 4. 构建向量数据库（首次运行）
python data_processing_v3.py  # 解析 PDF
python build_vector_db.py     # 构建向量库

# 5. 启动服务
# 终端 1: 启动 FastAPI
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 终端 2: 启动 Streamlit
streamlit run streamlit_app.py --server.port 8501
```

## 📦 项目结构

```
eMMC_RAG_Agent/
├── app/                      # FastAPI 应用
│   ├── main.py              # API 入口
│   ├── models.py            # 数据模型
│   └── rag_engine.py        # RAG 引擎单例
├── docs/                     # 文档
│   ├── QA.md                # 面试问答
│   ├── v3_modify.md         # v3 版本说明
│   └── v4_target.md         # v4 目标规划
├── vector_db/               # 向量数据库（需自行构建）
├── test_cases/              # 生成的测试用例
├── data_processing_v3.py    # PDF 解析脚本
├── build_vector_db.py       # 向量库构建脚本
├── rag_chat_v3.py          # RAG 核心逻辑
├── streamlit_app.py        # Streamlit 前端
├── test_api_client.py      # API 测试客户端
├── Dockerfile              # Docker 镜像定义
├── docker-compose.yml      # Docker Compose 配置
├── start.sh                # 容器启动脚本
├── requirements.txt        # Python 依赖
└── README.md              # 本文件
```

## 🔧 配置说明

### 环境变量

| 变量名 | 说明 | 必需 |
|--------|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | ✅ |

### 参数调优

在 Streamlit 界面中可以调整：
- **Top-K**: 检索文档数量（推荐 8-10）
- **打字速度**: 流式显示速度（0-200ms）

## 📊 技术栈

- **后端**: FastAPI, Uvicorn
- **前端**: Streamlit
- **向量数据库**: ChromaDB
- **Embedding 模型**: sentence-transformers/all-MiniLM-L6-v2
- **Reranking 模型**: cross-encoder/ms-marco-MiniLM-L6-v2
- **LLM**: DeepSeek Chat
- **PDF 解析**: PyMuPDF, pdfplumber
- **容器化**: Docker, Docker Compose

## 📝 使用示例

### 1. 查询协议信息

```
Q: eMMC 支持配置哪些分区？
A: eMMC 支持以下分区类型：
   - Boot Partitions (启动分区)
   - General Purpose Partitions (通用分区)
   - User Data Area (用户数据区)
   - RPMB Partition (重放保护内存块)
```

### 2. 生成测试代码

```
Q: 生成 CMD6 切换分区的测试代码
A: [自动生成 Python 测试用例]
```

## 🐛 故障排查

### Docker 相关

```bash
# 查看日志
docker-compose logs -f

# 重启服务
docker-compose restart

# 重新构建
docker-compose build --no-cache
```

### 本地开发

```bash
# 检查端口占用
lsof -i :8000
lsof -i :8501

# 清理 Python 缓存
find . -type d -name __pycache__ -exec rm -r {} +
```

## 📄 许可证

MIT License

