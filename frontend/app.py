import json
import http.client
import html
import requests
import sseclient
import streamlit as st
from requests.exceptions import ChunkedEncodingError, RequestException

BASE_URL = "http://localhost:8000"

st.set_page_config(page_title="研报生成系统", layout="wide")
st.markdown(
    """
<style>
:root {
  --bg1: #f4f1ea;
  --bg2: #e7efe9;
  --card: rgba(255, 255, 255, 0.88);
  --ink: #1f2428;
  --muted: #5e6a71;
  --border: #e3ddd2;
}
body, .stApp {
  font-family: "Source Han Sans SC", "Noto Sans SC", "Microsoft YaHei", "Segoe UI", sans-serif;
  color: var(--ink);
}
.stApp {
  background: radial-gradient(1200px 800px at 10% -10%, #fbeede 0%, transparent 55%),
              radial-gradient(900px 700px at 90% 10%, #e3f2ea 0%, transparent 60%),
              linear-gradient(135deg, var(--bg1) 0%, var(--bg2) 100%);
}
section[data-testid="stSidebar"] {
  background: var(--card);
  border-right: 1px solid var(--border);
  backdrop-filter: blur(6px);
}
.hero {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 18px 22px;
  margin-bottom: 12px;
  box-shadow: 0 10px 24px rgba(0,0,0,0.06);
}
.hero-title {
  font-size: 26px;
  font-weight: 700;
  margin: 0 0 6px 0;
}
.hero-sub {
  color: var(--muted);
  margin: 0;
}
.status-chip {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  border: 1px solid var(--border);
  background: #ffffff;
  color: var(--muted);
}
.status-running { color: #1b6d5a; border-color: #cfe7df; background: #ecf7f3; }
.status-waiting { color: #8a4b17; border-color: #f1d3b5; background: #fff4e8; }
.status-finished { color: #1f5d2e; border-color: #cfe7d6; background: #eef8f1; }
.status-idle { color: #586069; border-color: #e1e4e8; background: #f6f8fa; }
.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px 16px;
  margin-bottom: 12px;
  box-shadow: 0 6px 18px rgba(0,0,0,0.05);
}
.report-card {
  background: #ffffff;
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 18px 20px;
  margin-bottom: 8px;
}
.source-snippet {
  font-size: 14px;
  line-height: 1.6;
  color: var(--ink);
  white-space: pre-wrap;
  word-break: break-word;
}
div.stButton > button {
  border-radius: 10px;
  border: 1px solid var(--border);
}
section[data-testid="stSidebar"] [data-testid="stTextInput"] > div > div > input {
  border: 2px solid var(--border);
  background: #ffffff;
  border-radius: 12px;
  padding: 10px 12px;
  font-size: 15px;
  box-shadow: 0 6px 14px rgba(0, 0, 0, 0.06);
}
section[data-testid="stSidebar"] [data-testid="stTextInput"] label {
  font-weight: 700;
  color: var(--ink);
}
</style>
""",
    unsafe_allow_html=True,
)

st.markdown(
    """
<div class="hero">
  <div class="hero-title">多智能体行业研报生成系统</div>
  <div class="hero-sub">规划 → 检索 → 写作 → 评审 → 人工确认</div>
</div>
""",
    unsafe_allow_html=True,
)


def short_text(text: str, max_len: int = 240) -> str:
    if not text:
        return ""
    return text if len(text) <= max_len else text[:max_len] + "…"


def render_snippet(text: str, max_len: int = 260) -> str:
    if not text:
        return ""
    compact = " ".join(text.split())
    return html.escape(short_text(compact, max_len))


def format_log(node: str, payload, raw: bool = False) -> str:
    if raw:
        return f"{node}: {json.dumps(payload, ensure_ascii=False)}"
    if isinstance(payload, dict):
        if node == "planner":
            plan = payload.get("plan", [])
            if plan:
                lines = "\n".join([f"{i+1}. {p}" for i, p in enumerate(plan)])
                return f"规划完成：\n{lines}"
            return "规划完成。"
        if node == "researcher":
            summary = payload.get("content", "")
            return f"检索完成：\n{short_text(summary, 400)}"
        if node == "writer":
            content = payload.get("content", "")
            return f"写作完成：约 {len(content)} 字。"
        if node == "reviewer":
            critique = payload.get("critique", "")
            return f"评审意见：{critique}"
        if node == "human_review_node":
            return "进入人工审核节点。"
    return str(payload)


def render_logs(messages):
    if not messages:
        return "暂无日志。"
    return "\n".join([f"- {m}" for m in messages])


def fetch_history_list():
    try:
        resp = requests.get(f"{BASE_URL}/history/list", params={"limit": 50})
        if resp.status_code == 200:
            return resp.json().get("items", [])
    except Exception:
        pass
    return []


def fetch_history_detail(history_id: int):
    try:
        resp = requests.get(f"{BASE_URL}/history/{history_id}")
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def save_history(thread_id: str, topic: str, report: str, sources):
    try:
        resp = requests.post(
            f"{BASE_URL}/history/save",
            json={
                "thread_id": thread_id,
                "topic": topic,
                "report": report,
                "sources": sources or []
            }
        )
        return resp.status_code == 200
    except Exception:
        return False


with st.sidebar:
    st.header("任务输入")
    topic = st.text_input("研究主题", "大模型发展趋势")
    start_btn = st.button("开始研究")
    show_raw_logs = st.checkbox("显示详细日志", value=False)

    st.divider()
    st.subheader("历史记录")
    refresh_history = st.button("刷新历史记录")
    clear_history = st.button("清空历史记录")


if "thread_id" not in st.session_state:
    st.session_state.thread_id = None
if "messages" not in st.session_state:
    st.session_state.messages = []
if "waiting_for_feedback" not in st.session_state:
    st.session_state.waiting_for_feedback = False
if "current_content" not in st.session_state:
    st.session_state.current_content = ""
if "finished" not in st.session_state:
    st.session_state.finished = False
if "final_report" not in st.session_state:
    st.session_state.final_report = ""
if "sources" not in st.session_state:
    st.session_state.sources = []
if "history_list" not in st.session_state:
    st.session_state.history_list = fetch_history_list()
if "history_selected_id" not in st.session_state:
    st.session_state.history_selected_id = None
if "history_view" not in st.session_state:
    st.session_state.history_view = None
if "history_details" not in st.session_state:
    st.session_state.history_details = {}
if "history_saved_ids" not in st.session_state:
    st.session_state.history_saved_ids = set()
if "current_topic" not in st.session_state:
    st.session_state.current_topic = ""
if "display_mode" not in st.session_state:
    st.session_state.display_mode = "current"


if refresh_history:
    st.session_state.history_list = fetch_history_list()
    st.session_state.history_details = {}
    st.session_state.history_selected_id = None
    st.session_state.history_view = None
if clear_history:
    try:
        resp = requests.post(f"{BASE_URL}/history/clear")
        if resp.status_code == 200:
            st.session_state.history_list = []
            st.session_state.history_selected_id = None
            st.session_state.history_view = None
            st.session_state.history_details = {}
    except Exception:
        pass

if st.session_state.history_list:
    for item in st.session_state.history_list:
        history_id = item.get("id")
        if not history_id:
            continue
        label = f"{(item.get('created_at') or '')[:19]} | {item.get('topic') or ''} | {short_text(item.get('summary') or '', 40)}"
        if st.sidebar.button(label, key=f"history_btn_{history_id}"):
            detail = st.session_state.history_details.get(history_id)
            if detail is None:
                detail = fetch_history_detail(history_id)
                if detail:
                    st.session_state.history_details[history_id] = detail
            st.session_state.history_selected_id = history_id
            st.session_state.history_view = detail
            st.session_state.display_mode = "history"
else:
    st.sidebar.caption('暂无历史记录。')

if st.session_state.current_content or st.session_state.final_report:
    if st.sidebar.button("查看最新生成", key="view_latest_btn"):
        st.session_state.display_mode = "current"


if start_btn:
    try:
        resp = requests.post(f"{BASE_URL}/start", json={"topic": topic})
        if resp.status_code == 200:
            data = resp.json()
            st.session_state.thread_id = data["thread_id"]
            st.session_state.current_topic = topic
            st.session_state.messages = []
            st.session_state.waiting_for_feedback = False
            st.session_state.current_content = ""
            st.session_state.finished = False
            st.session_state.final_report = ""
            st.session_state.sources = []
            st.session_state.display_mode = "current"
            st.success(f"任务已启动，线程 ID：{st.session_state.thread_id}")
            st.rerun()
        else:
            st.error(f"启动失败：{resp.text}")
    except Exception as e:
        st.error(f"后端连接失败：{e}")


if st.session_state.thread_id:
    status = "运行中"
    status_class = "status-running"
    if st.session_state.waiting_for_feedback:
        status = "等待人工审核"
        status_class = "status-waiting"
    elif st.session_state.finished:
        status = "已完成"
        status_class = "status-finished"
else:
    status = "未开始"
    status_class = "status-idle"

st.markdown(
    f"""
<div class="card">
  <span class="status-chip {status_class}">{status}</span>
  <div style="margin-top:8px; color: var(--muted); font-size:13px;">
    线程 ID：{st.session_state.thread_id or "—"}
  </div>
</div>
""",
    unsafe_allow_html=True,
)

tab_report, tab_logs, tab_sources = st.tabs(["研报", "执行日志", "资料来源"])

with tab_logs:
    log_placeholder = st.empty()
    log_placeholder.markdown(render_logs(st.session_state.messages))


if st.session_state.thread_id and not st.session_state.waiting_for_feedback and not st.session_state.finished:
    with st.spinner("正在生成研报..."):
        try:
            messages = st.session_state.messages
            needs_feedback = False
            url = f"{BASE_URL}/stream/{st.session_state.thread_id}"
            response = requests.get(
                url,
                stream=True,
                headers={"Accept": "text/event-stream"},
                timeout=(3, 120),
            )
            client = sseclient.SSEClient(response)
            had_events = False

            try:
                for event in client.events():
                    had_events = True
                    if event.data == "[DONE]":
                        break

                    try:
                        data = json.loads(event.data)
                        node = data.get("node")
                        payload = data.get("data")

                        log_text = format_log(node, payload, raw=show_raw_logs)
                        messages.append(f"【{node}】{log_text}")
                        log_placeholder.markdown(render_logs(messages))

                        if node == "writer" and isinstance(payload, dict):
                            content = payload.get("content", "")
                            if content:
                                st.session_state.current_content = content
                                st.session_state.final_report = content
                        if node == "researcher" and isinstance(payload, dict):
                            sources = payload.get("sources") or []
                            if sources:
                                st.session_state.sources = sources
                        if node == "__interrupt__":
                            needs_feedback = True

                    except json.JSONDecodeError:
                        pass
            except (ChunkedEncodingError, http.client.IncompleteRead, RequestException) as e:
                if not had_events and "InvalidChunkLength" not in str(e):
                    raise
            finally:
                try:
                    response.close()
                except Exception:
                    pass

            st.session_state.waiting_for_feedback = needs_feedback
            st.session_state.finished = not needs_feedback
            if needs_feedback:
                st.rerun()
            else:
                st.session_state.display_mode = "current"
                st.success("流程已完成，已生成最终研报。")

        except Exception as e:
            st.error(f"流式连接错误：{e}")


if st.session_state.finished and st.session_state.final_report and st.session_state.thread_id:
    if st.session_state.thread_id not in st.session_state.history_saved_ids:
        saved = save_history(
            st.session_state.thread_id,
            st.session_state.current_topic or topic,
            st.session_state.final_report,
            st.session_state.sources,
        )
        if saved:
            st.session_state.history_saved_ids.add(st.session_state.thread_id)
            st.session_state.history_list = fetch_history_list()


with tab_report:
    if st.session_state.display_mode == "history" and st.session_state.history_view:
        st.subheader("历史记录详情")
        detail = st.session_state.history_view
        st.markdown(f"**主题**：{detail.get('topic', '')}")
        st.markdown(f"**时间**：{detail.get('created_at', '')}")
        st.markdown(f"**摘要**：{detail.get('summary', '')}")
        st.markdown('<div class="report-card">', unsafe_allow_html=True)
        st.markdown(detail.get("report", ""))
        st.markdown('</div>', unsafe_allow_html=True)

        st.subheader("继续追问")
        followup_question = st.text_input("输入追问内容", key=f"followup_question_{detail.get('id')}")
        col_q1, col_q2 = st.columns(2)
        with col_q1:
            followup_btn = st.button("基于该记录继续追问", key=f"followup_btn_{detail.get('id')}")
        with col_q2:
            delete_btn = st.button("删除该记录", key=f"delete_btn_{detail.get('id')}")

        if followup_btn and followup_question.strip():
            try:
                resp = requests.post(
                    f"{BASE_URL}/history/followup",
                    json={
                        "history_id": detail.get("id"),
                        "question": followup_question.strip()
                    }
                )
                if resp.status_code == 200:
                    data = resp.json()
                    st.session_state.thread_id = data["thread_id"]
                    st.session_state.current_topic = followup_question.strip()
                    st.session_state.messages = []
                    st.session_state.waiting_for_feedback = False
                    st.session_state.current_content = ""
                    st.session_state.finished = False
                    st.session_state.final_report = ""
                    st.session_state.sources = detail.get("sources", [])
                    st.session_state.display_mode = "current"
                    st.success("已开始基于历史记录继续追问。")
                    st.rerun()
                else:
                    st.error(f"操作失败：{resp.text}")
            except Exception as e:
                st.error(f"请求失败：{e}")
        if delete_btn:
            try:
                resp = requests.delete(f"{BASE_URL}/history/{detail.get('id')}")
                if resp.status_code == 200:
                    st.session_state.history_list = fetch_history_list()
                    st.session_state.history_selected_id = None
                    st.session_state.history_view = None
                    st.session_state.history_details.pop(detail.get("id"), None)
                    st.session_state.display_mode = "current"
                    st.success("已删除该记录。")
                    st.rerun()
                else:
                    st.error(f"删除失败：{resp.text}")
            except Exception as e:
                st.error(f"请求失败：{e}")
    elif st.session_state.final_report:
        st.markdown(st.session_state.final_report)
        st.markdown('</div>', unsafe_allow_html=True)
        st.download_button(
            '下载研报（Markdown）',
            st.session_state.final_report,
            file_name='report.md'
        )
    elif st.session_state.current_content:
        st.markdown('<div class="report-card">', unsafe_allow_html=True)
        st.markdown(st.session_state.current_content)
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.info('暂无研报内容，请点击“开始研究”。')

    if st.session_state.waiting_for_feedback:
        st.divider()
        st.subheader("人工审核")
        with st.form("feedback_form"):
            st.info("请审阅上方草稿，如需修改请填写意见。")

            col1, col2 = st.columns(2)
            with col1:
                approve = st.form_submit_button("通过")
            with col2:
                reject = st.form_submit_button("驳回")

            feedback_text = st.text_area(
                "修改意见（驳回时必填）",
                placeholder="例如：补充市场规模数据，优化结论结构。"
            )

            if approve:
                try:
                    resp = requests.post(
                        f"{BASE_URL}/feedback",
                        json={
                            "thread_id": st.session_state.thread_id,
                            "action": "approve"
                        }
                    )
                    if resp.status_code == 200:
                        st.success("已通过，继续执行。")
                        st.session_state.waiting_for_feedback = False
                        st.session_state.finished = False
                        st.rerun()
                    else:
                        st.error(f"操作失败：{resp.text}")
                except Exception as e:
                    st.error(f"请求失败：{e}")

            if reject:
                if not feedback_text:
                    st.warning("请填写驳回原因。")
                else:
                    try:
                        resp = requests.post(
                            f"{BASE_URL}/feedback",
                            json={
                                "thread_id": st.session_state.thread_id,
                                "action": "reject",
                                "feedback": feedback_text
                            }
                        )
                        if resp.status_code == 200:
                            st.warning("已驳回，正在回滚并重写。")
                            st.session_state.waiting_for_feedback = False
                            st.session_state.finished = False
                            st.rerun()
                        else:
                            st.error(f"操作失败：{resp.text}")
                    except Exception as e:
                        st.error(f"请求失败：{e}")

with tab_sources:
    if st.session_state.sources:
        for idx, s in enumerate(st.session_state.sources, start=1):
            title = s.get("title") or "无标题"
            url = s.get("url") or ""
            snippet = s.get("snippet") or ""
            st.markdown(f"**{idx}. {title}**")
            if url:
                st.markdown(url)
            if snippet:
                st.markdown(f'<div class="source-snippet">{render_snippet(snippet, 260)}</div>', unsafe_allow_html=True)
            st.markdown("---")
    else:
        st.info("暂无来源数据。")
