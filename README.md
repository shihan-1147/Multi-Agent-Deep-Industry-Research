# 基于 LangGraph 的多智能体深度行业研报生成系统

这是一个基于 LangGraph 的多智能体系统，能够自动完成行业研报的规划、检索、写作与审核，并支持“人在回路 (Human-in-the-loop)”的人工反馈与迭代优化。

## 架构

- **Agent 框架**：LangGraph（StateGraph、Checkpoint）
- **LLM**：DeepSeek-V3.1（DashScope 兼容模式）
- **搜索工具**：Tavily Search（优先）/ DuckDuckGo Search（回退）
- **后端**：FastAPI（异步、SSE 流式输出）
- **前端**：Streamlit（实时日志、人工审核交互）
- **持久化**：SQLite（checkpoints.sqlite / history.sqlite）

## 前置条件

- Python 3.10+
- DashScope API Key（在 `.env` 或环境变量中设置 `DASHSCOPE_API_KEY`）
- Tavily API Key（在 `.env` 或环境变量中设置 `TAVILY_API_KEY`，可选但推荐）

## 安装

1. **安装依赖**
   ```bash
   pip install -r requirements.txt
   ```

2. **配置环境变量**
   在项目根目录创建 `.env` 文件：
   ```
   DASHSCOPE_API_KEY=sk-your-api-key
   TAVILY_API_KEY=tvly-your-api-key
   ```

## 启动方式

需要分别在两个终端启动后端与前端。

### 1. 启动后端 API
```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```
后端接口地址：`http://localhost:8000`

### 2. 启动前端 UI
```bash
streamlit run frontend/app.py
```
前端页面地址：`http://localhost:8501`

## 使用方式

1. 打开 Streamlit 页面。
2. 在侧边栏输入研究主题（例如 “生成式 AI 趋势 2025”）。
3. 点击 **开始研究**。
4. 实时观看 Agent 执行流程：规划 → 检索 → 写作 → 评审 → 人工确认。
5. **AI 评审**：需要补充资料会回到检索，需要改写会回到写作；最多评审 2 次，超过上限会直接进入人工审核。
6. **人工审核**：系统会在最终确认前暂停，你可以：
   - **Approve**：通过并结束流程
   - **Reject**：提供反馈，引导系统改写
7. **历史记录**：侧边栏展示所有历史记录，点击可查看详情；可基于该记录继续追问或删除记录。

## 项目结构

- `agent/`：核心 Agent 逻辑（图、节点、Prompt）
- `backend/`：FastAPI 后端
- `frontend/`：Streamlit 前端
- `test_agent.py`：Agent 流程测试脚本（不依赖 UI）

## LangGraph Dev

如果你想用 LangGraph CLI 运行/调试图，请在项目根目录执行：

```bash
langgraph dev --config langgraph.json
```

默认图：`research_graph`（对应 `agent/dev_graph.py:graph`）
