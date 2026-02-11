# Git 上传前检查清单

## ✅ 必须完成的项目

### 1. 敏感信息检查
- [ ] 确认 `.env` 文件已在 `.gitignore` 中
- [ ] 检查代码中是否有硬编码的 API Key
- [ ] 确认 `.env.example` 中没有真实的密钥

### 2. 大文件检查
- [ ] `vector_db/` 目录已在 `.gitignore` 中（约 100MB+）
- [ ] `output/` 目录已在 `.gitignore` 中
- [ ] `OldVersion/` 和 `practice_files/` 已在 `.gitignore` 中

### 3. 文档完整性
- [ ] `README.md` 已创建并完善
- [ ] `README_DOCKER.md` 存在
- [ ] `.env.example` 存在
- [ ] 所有重要功能都有文档说明

### 4. 代码质量
- [ ] 移除了所有 `print()` 调试语句（或改为 logging）
- [ ] 移除了临时测试文件
- [ ] 代码中没有 TODO 或 FIXME 标记（或已记录在 Issue 中）

### 5. 依赖管理
- [ ] `requirements.txt` 是最新的
- [ ] `Dockerfile` 可以成功构建
- [ ] `docker-compose.yml` 可以成功运行

## 📋 推荐完成的项目

### 1. 添加 LICENSE 文件
```bash
# 如果选择 MIT License
touch LICENSE
# 然后添加 MIT License 内容
```

### 2. 添加 CHANGELOG.md
记录版本更新历史

### 3. 添加 CONTRIBUTING.md
贡献指南

### 4. 添加 GitHub Actions
- CI/CD 自动测试
- Docker 镜像自动构建

## 🚀 Git 初始化步骤

```bash
# 1. 初始化 Git 仓库（如果还没有）
git init

# 2. 添加所有文件
git add .

# 3. 检查将要提交的文件
git status

# 4. 确认没有敏感信息
git diff --cached

# 5. 首次提交
git commit -m "Initial commit: eMMC RAG Agent v1.0

Features:
- FastAPI backend with streaming support
- Streamlit frontend with ChatGPT-like UI
- Hybrid search with Cross-Encoder reranking
- Docker containerization
- Function calling for code generation"

# 6. 添加远程仓库
git remote add origin <your-repo-url>

# 7. 推送到远程
git push -u origin main
```

## ⚠️ 注意事项

1. **不要上传的文件**：
   - `.env`（包含真实 API Key）
   - `vector_db/`（太大，需要用户自己构建）
   - `__pycache__/`（Python 缓存）
   - `.DS_Store`（macOS 系统文件）

2. **需要用户自己准备的**：
   - eMMC 协议 PDF 文件
   - DeepSeek API Key
   - 运行 `data_processing_v3.py` 和 `build_vector_db.py`

3. **README 中应该说明**：
   - 如何获取 PDF 文件
   - 如何申请 API Key
   - 首次运行的完整步骤

## 📝 提交信息规范

使用 Conventional Commits 格式：

```
feat: 添加新功能
fix: 修复 bug
docs: 文档更新
style: 代码格式调整
refactor: 代码重构
test: 测试相关
chore: 构建/工具链相关
```

示例：
```bash
git commit -m "feat: add streaming chat support"
git commit -m "fix: resolve ChromaDB readonly issue in Docker"
git commit -m "docs: update README with Docker instructions"
```
