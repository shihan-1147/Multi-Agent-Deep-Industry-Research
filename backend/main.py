import uuid
import json
import asyncio
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage

from backend.models import ResearchRequest, FeedbackRequest, HistorySaveRequest, HistoryFollowupRequest
from agent.graph import build_graph
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
import aiosqlite

@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = await aiosqlite.connect("checkpoints.sqlite")
    checkpointer = AsyncSqliteSaver(conn)
    app.state.graph = build_graph(checkpointer)
    history_conn = await aiosqlite.connect("history.sqlite")
    await history_conn.execute("PRAGMA journal_mode=WAL;")
    await history_conn.execute(
        """
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id TEXT UNIQUE,
            topic TEXT,
            report TEXT,
            summary TEXT,
            sources TEXT,
            created_at TEXT
        )
        """
    )
    # Backfill/ensure summary column exists if table was created earlier.
    async with history_conn.execute("PRAGMA table_info(history)") as cursor:
        cols = [row[1] for row in await cursor.fetchall()]
    if "summary" not in cols:
        await history_conn.execute("ALTER TABLE history ADD COLUMN summary TEXT")
    await history_conn.commit()
    app.state.history_conn = history_conn
    app.state.history_lock = asyncio.Lock()
    try:
        yield
    finally:
        await history_conn.close()
        await conn.close()

app = FastAPI(title="Research Agent API", lifespan=lifespan)

@app.post("/start")
async def start_research(request: ResearchRequest):
    """Start a new research task."""
    graph = app.state.graph
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    
    initial_state = {
        "task": request.topic,
        "plan": [],
        "research_tasks": [],
        "research_task": "",
        "research_chunks": [],
        "content": "",
        "critique": "",
        "human_action": "",
        "human_feedback": "",
        "history_context": "",
        "max_revisions": 2,
        "revision_number": 0,
        "messages": [],
        "sources": []
    }
    
    # Start the graph in background (conceptually)
    # Since LangGraph is stateful and checkpointed, we just need to init it.
    # However, for the stream endpoint to pick it up, we might want to trigger the first run here
    # or let the client connect to stream first.
    # A common pattern is to just return thread_id and let client connect to stream to start/watch.
    # But to ensure it starts, we can do a fire-and-forget or just return thread_id.
    # Let's verify if we need to 'kick' it. 
    # If we want the stream to show everything from start, the client should connect to stream immediately.
    # But typically /start initiates the process.
    # We will update the state with initial input using update_state (if we didn't start it yet)
    # OR we can just use invoke/stream. 
    # For a persistent graph, we can use update_state to set the initial state.
    
    # We'll use update_state to seed the initial state, 
    # then the stream endpoint will pick it up and run it?
    # Actually, graph.stream() runs the logic. 
    # If we want /stream to drive the execution, we should just return thread_id here
    # and let /stream call graph.stream().
    # BUT, the requirement says "call graph.invoke (or background task)".
    # Let's spawn a background task to start the process so it runs until the first interrupt.
    
    # Actually, if we use SSE, the /stream endpoint IS the runner.
    # If we run it here in background, /stream might miss events if not connected yet.
    # A better approach for this simple architecture:
    # 1. /start: returns thread_id.
    # 2. Client connects to /stream/{thread_id}.
    # 3. /stream triggers graph.stream(initial_state, ...) if it's new, or resumes if existing.
    
    # However, to strictly follow "POST /start ... call graph.invoke", let's do this:
    # We will use graph.update_state to initialize the state. 
    # Then the stream endpoint will detect the state and continue.
    
    # Let's just save the initial state to the checkpointer using update_state
    # This effectively "queues" the task.
    await graph.aupdate_state(config, initial_state)
    
    return {"thread_id": thread_id}

@app.post("/feedback")
async def submit_feedback(request: FeedbackRequest):
    """Handle human feedback (Approve/Reject)."""
    graph = app.state.graph
    config = {"configurable": {"thread_id": request.thread_id}}
    
    # Get current state to verify we are at human_review_node
    state = await graph.aget_state(config)
    if not state.next:
        raise HTTPException(status_code=400, detail="Workflow already finished or invalid state")
    
    if request.action == "approve":
        update = {
            "human_action": "approve",
            "messages": [HumanMessage(content="Human Feedback: approve")]
        }
        await graph.aupdate_state(config, update, as_node="human_review_node")
        return {"status": "approved", "message": "Feedback received. Connect to /stream to resume."}
        
    elif request.action == "reject":
        # Update state with feedback and pretend it came from reviewer to trigger rollback
        update = {
            "critique": f"REVISE: {request.feedback}",
            "human_action": "reject",
            "human_feedback": request.feedback,
            "messages": [HumanMessage(content=f"Human Feedback: {request.feedback}")]
        }
        
        await graph.aupdate_state(config, update, as_node="human_review_node")
        
        return {"status": "rejected", "message": "Feedback recorded. Connect to /stream to resume (rolling back to Writer)."}

@app.post("/history/save")
async def save_history(request: HistorySaveRequest):
    conn = app.state.history_conn
    sources_json = json.dumps(request.sources or [], ensure_ascii=False)
    summary = _make_summary(request.report)
    created_at = (datetime.now().astimezone() + timedelta(hours=8)).isoformat()

    async with app.state.history_lock:
        await conn.execute(
            """
            INSERT INTO history (thread_id, topic, report, summary, sources, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET
                topic=excluded.topic,
                report=excluded.report,
                summary=excluded.summary,
                sources=excluded.sources
            """,
            (request.thread_id, request.topic, request.report, summary, sources_json, created_at)
        )
        await conn.commit()

    return {"status": "ok"}

@app.get("/history/list")
async def list_history(limit: int = 20):
    conn = app.state.history_conn
    async with conn.execute(
        "SELECT id, thread_id, topic, summary, created_at FROM history ORDER BY id DESC LIMIT ?",
        (limit,)
    ) as cursor:
        rows = await cursor.fetchall()
    items = [
        {"id": r[0], "thread_id": r[1], "topic": r[2], "summary": r[3], "created_at": r[4]}
        for r in rows
    ]
    return {"items": items}

@app.get("/history/{history_id}")
async def get_history(history_id: int):
    conn = app.state.history_conn
    async with conn.execute(
        "SELECT id, thread_id, topic, report, summary, sources, created_at FROM history WHERE id = ?",
        (history_id,)
    ) as cursor:
        row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="History not found")
    sources = json.loads(row[5]) if row[5] else []
    return {
        "id": row[0],
        "thread_id": row[1],
        "topic": row[2],
        "report": row[3],
        "summary": row[4],
        "sources": sources,
        "created_at": row[6],
    }

@app.delete("/history/{history_id}")
async def delete_history(history_id: int):
    conn = app.state.history_conn
    async with app.state.history_lock:
        await conn.execute("DELETE FROM history WHERE id = ?", (history_id,))
        await conn.commit()
    return {"status": "ok"}

@app.post("/history/clear")
async def clear_history():
    conn = app.state.history_conn
    async with app.state.history_lock:
        await conn.execute("DELETE FROM history")
        await conn.commit()
    return {"status": "ok"}

@app.post("/history/followup")
async def followup_history(request: HistoryFollowupRequest):
    conn = app.state.history_conn
    async with conn.execute(
        "SELECT id, thread_id, topic, report, sources FROM history WHERE id = ?",
        (request.history_id,)
    ) as cursor:
        row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="History not found")

    sources = json.loads(row[4]) if row[4] else []
    graph = app.state.graph
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    initial_state = {
        "task": request.question,
        "plan": [],
        "research_tasks": [],
        "research_task": "",
        "research_chunks": [],
        "content": "",
        "critique": "",
        "human_action": "",
        "human_feedback": "",
        "history_context": row[3],
        "max_revisions": 2,
        "revision_number": 0,
        "messages": [],
        "sources": sources,
    }
    await graph.aupdate_state(config, initial_state)
    return {"thread_id": thread_id}

def _make_summary(report: str, max_len: int = 120) -> str:
    if not report:
        return ""
    text = report.replace("#", "").replace("*", "").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"

@app.get("/stream/{thread_id}")
async def stream_agent(thread_id: str):
    """Stream logs via SSE."""
    graph = app.state.graph
    config = {"configurable": {"thread_id": thread_id}}
    
    async def event_generator():
        # We want to stream updates. 
        # If the agent is running in background, we might miss events if we just use astream from scratch?
        # LangGraph astream can attach to existing thread? 
        # Actually astream runs the graph. 
        # If we have a background run, calling astream might conflict or just join?
        # LangGraph doesn't support multiple concurrent runs on the same thread_id easily 
        # (SqliteSaver locks).
        
        # So we should NOT run in background if we want to stream here?
        # OR we use a mechanism to broadcast events.
        # Given the requirements: "GET /stream ... Real-time output ... SSE".
        # And POST /start "invokes".
        
        # If POST /start starts it, and GET /stream watches it.
        # We need a way to watch.
        # LangGraph doesn't have a built-in "watch only" mode for a separate process yet 
        # (unless using LangSmith or custom callback broadcasting).
        
        # COMPROMISE for this task:
        # We assume the user calls /start, then immediately calls /stream.
        # OR /stream is the one that actually triggers the run if it's not running?
        # But /start already returns.
        
        # Let's change the strategy slightly to ensure reliability:
        # /start: Creates thread, sets initial state. DOES NOT RUN.
        # /stream: Runs `graph.astream(None, config)`. 
        # This way the browser connection drives the execution and receives events.
        
        # Wait, if /feedback is called, it triggers a run too.
        # If /stream is connected, how does it get those updates?
        # It's tricky with standard HTTP.
        # Ideally, /start runs it, and we use a shared queue or similar for SSE.
        
        # FOR SIMPLICITY:
        # We will make /stream the "Driver".
        # /start: inits state.
        # /stream: loops `async for event in graph.astream(None, config): yield event`.
        # This works for the initial run.
        # For /feedback: it updates state. The client (UI) will likely be polling or re-connecting to /stream?
        # Or the UI stays connected?
        # If UI stays connected to /stream, but /feedback triggers a background run... /stream won't see it.
        
        # Let's stick to the prompt's implied architecture which might assume
        # we can just "stream logs".
        # We will implement a simple generator that checks history?
        # No, "Real-time".
        
        # Let's assume the client connects to /stream and THAT triggers the run / resume.
        # So /start -> init.
        # /stream -> runs.
        # /feedback -> update state. Client (Streamlit) then re-connects to /stream or /stream picks it up?
        # Streamlit `st.write_stream` usually consumes a generator.
        
        # Revised Plan:
        # /start: aupdate_state (init).
        # /stream: astream(None, config). This runs the graph until interrupt/end.
        # /feedback: aupdate_state (feedback). 
        # After feedback, the frontend (Streamlit) typically re-runs the script. 
        # It will call /stream again. 
        # The new /stream call will resume execution from the new state.
        
        # This fits the "Stateless REST + Streamlit" model perfectly.
        # We don't need background tasks in /start or /feedback.
        
        async for event in graph.astream(None, config=config):
            # Format event for SSE
            # event is a dict of node outputs
            for node_name, node_content in event.items():
                if isinstance(node_content, dict):
                    payload = {}
                    for key in ("content", "critique", "plan", "revision_number", "sources", "task"):
                        if key in node_content:
                            payload[key] = node_content[key]
                else:
                    payload = node_content

                # We yield a JSON string
                data = json.dumps({"node": node_name, "data": payload}, ensure_ascii=False)
                yield f"data: {data}\n\n"
        
        # Send a "done" event or similar?
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# Update /start to NOT run background task, just init.
# Update /feedback to NOT run background task, just update.
