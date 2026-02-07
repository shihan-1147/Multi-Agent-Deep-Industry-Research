# 项目规范：基于 LangGraph 的多智能体深度研报系统

## 1. 项目目标
构建一个能够自动进行互联网搜索、规划大纲、撰写长文，并支持“人在回路 (Human-in-the-loop)”审核的 AI Agent 系统。

## 2. 技术栈
- **LLM**: 阿里云 DashScope API (模型: qwen-max)
- **Agent 框架**: LangGraph (用于构建 StateGraph, Nodes, Edges)
- **后端 API**: FastAPI (异步处理, SSE 流式输出)
- **持久化**: SQLite (通过 LangGraph 的 SqliteSaver 保存 Checkpoint)
- **前端**: Streamlit (用于展示流式日志和人工审核界面)
- **工具**: Tavily Search API (或是模拟的搜索工具)

## 3. 核心架构
采用微服务架构：
1. **Agent Layer**: 包含 Planner, Researcher, Writer, Reviewer 四个节点。
2. **API Layer**: 通过 HTTP 接口暴露 Agent 能力，管理 thread_id。
3. **UI Layer**: 连接 API，渲染 Markdown，提供 "Approve/Reject" 按钮。

## 4. 目录结构
- agent/ (图逻辑, 状态定义, Prompt)
- backend/ (FastAPI app, 路由)
- frontend/ (Streamlit app)
- .env (环境变量)