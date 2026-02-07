import os
import json
from pathlib import Path
from typing import Dict, Any

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_community.tools import DuckDuckGoSearchRun
from tavily import TavilyClient

from agent.states import AgentState
from agent.prompts import PLANNER_SYSTEM_PROMPT, WRITER_PROMPT_TEMPLATE, REVIEWER_PROMPT_TEMPLATE, SECTION_WRITER_PROMPT_TEMPLATE, FINAL_WRITER_PROMPT_TEMPLATE

env_path = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(env_path, override=False)

# Auto-enable LangSmith tracing if API key is present and tracing not set.
if os.getenv("LANGSMITH_API_KEY") and not os.getenv("LANGSMITH_TRACING"):
    os.environ["LANGSMITH_TRACING"] = "true"

# Initialize LLM
llm = ChatOpenAI(
    model="deepseek-v3.1",
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)

# Fallback search tool
search_tool = DuckDuckGoSearchRun()


def planner_node(state: AgentState) -> Dict[str, Any]:
    print("--- PLANNER NODE ---")
    task = state["task"]
    history_context = state.get("history_context", "")

    system_msg = SystemMessage(content=PLANNER_SYSTEM_PROMPT)
    if history_context:
        user_msg = HumanMessage(content=f"任务：{task}\n\n已有研报内容（供参考）：\n{history_context}")
    else:
        user_msg = HumanMessage(content=f"任务：{task}")

    try:
        response = llm.invoke([system_msg, user_msg])
        content = response.content.replace("```json", "").replace("```", "").strip()
        plan_data = json.loads(content)
        plan = plan_data.get("plan", [])
    except Exception as e:
        print(f"Planner Error: {e}")
        plan = [f"梳理 {task} 的现状与范围", "识别关键趋势与驱动因素", "总结核心结论与建议"]

    return {"plan": plan, "messages": [SystemMessage(content=f"Plan generated: {plan}")]}


def research_router_node(state: AgentState) -> Dict[str, Any]:
    print("--- RESEARCH ROUTER NODE ---")
    plan = state.get("plan", [])
    critique = state.get("critique", "")
    history_context = state.get("history_context", "")
    task = state.get("task", "")

    tasks = []
    if isinstance(critique, str) and critique.strip().upper().startswith("RESEARCH:"):
        focus = critique.split(":", 1)[1].strip()
        if focus:
            tasks = [focus]
    if not tasks and plan:
        tasks = plan[:3]
    if not tasks:
        tasks = [task]

    return {"research_tasks": tasks, "research_task": tasks[0]}


def researcher_node(state: AgentState) -> Dict[str, Any]:
    print("--- RESEARCHER NODE ---")
    plan = state.get("plan", [])
    task = state.get("task", "")

    research_task = state.get("research_task", "").strip()
    search_query = research_task if research_task else f"{task} {plan[0] if plan else ''}".strip()
    print(f"Searching for: {search_query}")

    sources = []
    search_result = ""
    try:
        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            raise RuntimeError("TAVILY_API_KEY 未配置，无法使用 Tavily。")

        client = TavilyClient(api_key=api_key)
        resp = client.search(
            search_query,
            max_results=6,
            search_depth="basic",
            include_answer=False,
            include_raw_content=False,
        )
        results = resp.get("results", []) if isinstance(resp, dict) else []
        summary_lines = []
        for r in results:
            title = r.get("title") or "无标题"
            url = r.get("url") or ""
            snippet = r.get("content") or r.get("snippet") or ""
            sources.append({"title": title, "url": url, "snippet": snippet})
            if snippet:
                summary_lines.append(f"- {title}：{snippet}")
            else:
                summary_lines.append(f"- {title}")
        if summary_lines:
            search_result = "检索到的资料摘要：\n" + "\n".join(summary_lines)
        else:
            search_result = "未检索到有效结果。"
    except Exception as e:
        print(f"Tavily Search Error: {e}")
        try:
            search_result = search_tool.run(search_query)
        except Exception as e2:
            print(f"Search Fallback Error: {e2}")
            search_result = "检索失败，暂时依赖模型内部知识。"

    return {
        "research_chunks": [search_result],
        "sources": sources,
        "messages": [SystemMessage(content=f"Research completed for: {search_query}")]
    }


def research_merge_node(state: AgentState) -> Dict[str, Any]:
    print("--- RESEARCH MERGE NODE ---")
    chunks = state.get("research_chunks", [])
    content = "\n\n".join([c for c in chunks if isinstance(c, str) and c.strip()])
    if not content:
        content = "未检索到有效资料。"
    return {"content": content}


def writer_node(state: AgentState) -> Dict[str, Any]:
    print("--- WRITER NODE ---")
    task = state["task"]
    plan = state["plan"]
    content = state["content"]
    critique = state.get("critique", "")
    human_feedback = state.get("human_feedback", "")
    history_context = state.get("history_context", "")
    revision_number = state.get("revision_number", 0)
    sources = state.get("sources", [])
    history_context = state.get("history_context", "")

    sources_text = ""
    if sources:
        lines = []
        for idx, s in enumerate(sources[:8], start=1):
            title = s.get("title") or "无标题"
            url = s.get("url") or ""
            if url:
                lines.append(f"{idx}. {title} - {url}")
            else:
                lines.append(f"{idx}. {title}")
        sources_text = "\n".join(lines)
    else:
        sources_text = "无"

    try:
        if isinstance(plan, list):
            plan_items = [str(p).strip() for p in plan if str(p).strip()]
        else:
            plan_items = [str(plan).strip()] if plan else []
        if not plan_items:
            plan_items = ["背景与现状", "关键发现", "影响与建议", "结论"]

        sections = []
        for section in plan_items:
            section_prompt = SECTION_WRITER_PROMPT_TEMPLATE.format(
                task=task,
                section=section,
                content=content,
                critique=critique,
                sources=sources_text,
                human_feedback=human_feedback,
                history_context=history_context
            )
            response = llm.invoke([HumanMessage(content=section_prompt)])
            section_body = response.content.strip()
            if not section_body:
                section_body = "本节内容生成失败，请稍后重试。"
            sections.append(f"## {section}\n{section_body}")

        sections_text = "\n\n".join(sections)
        final_prompt = FINAL_WRITER_PROMPT_TEMPLATE.format(
            task=task,
            plan=plan_items,
            sections=sections_text,
            critique=critique,
            sources=sources_text,
            human_feedback=human_feedback,
            history_context=history_context
        )
        response = llm.invoke([HumanMessage(content=final_prompt)])
        draft = response.content
    except Exception as e:
        print(f"Writer Error: {e}")
        try:
            fallback_prompt = WRITER_PROMPT_TEMPLATE.format(
                task=task,
                plan=plan,
                content=content,
                critique=critique,
                sources=sources_text,
                human_feedback=human_feedback,
                history_context=history_context
            )
            response = llm.invoke([HumanMessage(content=fallback_prompt)])
            draft = response.content
        except Exception as e2:
            print(f"Writer Fallback Error: {e2}")
            draft = "生成失败，请稍后重试。"

    return {
        "content": draft,
        "revision_number": revision_number + 1,
        "human_action": "",
        "messages": [HumanMessage(content=f"Draft written (Rev {revision_number+1})")]
    }


def reviewer_node(state: AgentState) -> Dict[str, Any]:
    print("--- REVIEWER NODE ---")
    content = state["content"]
    revision_number = state.get("revision_number", 0)
    max_revisions = state.get("max_revisions", 2)

    if revision_number >= max_revisions:
        return {"critique": "APPROVE"}

    prompt = REVIEWER_PROMPT_TEMPLATE.format(content=content)

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        result = response.content.strip()
    except Exception as e:
        print(f"Reviewer Error: {e}")
        result = "APPROVE"

    lines = [line.strip() for line in result.splitlines() if line.strip()]
    normalized = ""
    for line in lines:
        upper = line.upper()
        if upper == "APPROVE" or upper.startswith("APPROVE "):
            normalized = "APPROVE"
            break
        if upper.startswith("RESEARCH:"):
            normalized = line
            break
        if upper.startswith("REVISE:"):
            normalized = line
            break
    if not normalized and lines:
        normalized = f"REVISE: {lines[0]}"
    result = normalized if normalized else "REVISE: 请补充关键数据来源并优化结构。"

    return {"critique": result}


def human_review_node(state: AgentState) -> Dict[str, Any]:
    print("--- HUMAN REVIEW NODE ---")
    return {}
