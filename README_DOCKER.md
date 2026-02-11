# eMMC RAG Agent - Docker 部署指南

## 🚀 快速开始

### 前置要求

- Docker 20.10+
- Docker Compose 2.0+
- 至少 4GB 可用内存

### 方法 1：使用 Docker Compose（推荐）

```bash
# 1. 确保 .env 文件存在并包含 DEEPSEEK_API_KEY
cp .env.example .env  # 如果还没有 .env
vim .env  # 编辑并添加你的 API key

# 2. 构建并启动
docker-compose up -d

# 3. 查看日志
docker-compose logs -f

# 4. 停止服务
docker-compose down
```

### 方法 2：使用 Docker 命令

```bash
# 1. 构建镜像
docker build -t emmc-rag-agent .

# 2. 运行容器
docker run -d \
  --name emmc-rag-agent \
  -p 8000:8000 \
  -p 8501:8501 \
  -v $(pwd)/vector_db:/app/vector_db:ro \
  -v $(pwd)/test_cases:/app/test_cases \
  -e DEEPSEEK_API_KEY=your_api_key_here \
  emmc-rag-agent

# 3. 查看日志
docker logs -f emmc-rag-agent

# 4. 停止容器
docker stop emmc-rag-agent
docker rm emmc-rag-agent
```

## 📦 访问服务

启动成功后，访问：

- **Streamlit 前端**: http://localhost:8501
- **FastAPI 文档**: http://localhost:8000/docs
- **健康检查**: http://localhost:8000/health

## 🔧 配置说明

### 环境变量

| 变量名 | 说明 | 必需 |
|--------|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | ✅ |

### 数据卷

| 宿主机路径 | 容器路径 | 说明 |
|-----------|---------|------|
| `./vector_db` | `/app/vector_db` | 向量数据库（只读） |
| `./test_cases` | `/app/test_cases` | 生成的测试用例 |
| `./.env` | `/app/.env` | 环境变量文件 |

## 🐛 故障排查

### 容器无法启动

```bash
# 查看详细日志
docker-compose logs

# 检查端口占用
lsof -i :8000
lsof -i :8501
```

### 模型下载慢

首次启动时，容器会从 HuggingFace 下载模型（约 200MB），可能需要几分钟。

可以设置 HuggingFace 镜像加速：

```bash
docker run -d \
  -e HF_ENDPOINT=https://hf-mirror.com \
  ...
```

### 内存不足

确保 Docker 分配了至少 4GB 内存：

```bash
# macOS/Windows: Docker Desktop -> Settings -> Resources
```

## 📊 性能优化

### 使用预构建镜像（未来）

```bash
docker pull your-registry/emmc-rag-agent:latest
```

### 多阶段构建优化

当前 Dockerfile 已使用多阶段构建，镜像大小约 2GB（主要是 PyTorch）。

## 🔄 更新部署

```bash
# 1. 拉取最新代码
git pull

# 2. 重新构建
docker-compose build

# 3. 重启服务
docker-compose up -d
```

## 📝 开发模式

如果需要在容器中进行开发：

```bash
docker-compose run --rm emmc-rag-agent bash
```

## 🌐 生产部署建议

1. **使用反向代理**（Nginx/Caddy）
2. **启用 HTTPS**
3. **配置日志轮转**
4. **设置资源限制**：

```yaml
services:
  emmc-rag-agent:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 4G
```

5. **使用 Docker Secrets 管理敏感信息**

## 📄 许可证

MIT License
