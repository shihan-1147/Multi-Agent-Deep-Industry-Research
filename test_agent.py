import asyncio
import uuid
import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from agent.graph import build_graph

async def run_test():
    conn = await aiosqlite.connect("checkpoints.sqlite")
    try:
        checkpointer = AsyncSqliteSaver(conn)
        graph = build_graph(checkpointer)

        thread_id = str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}

        print(f"Starting Thread ID: {thread_id}")

        initial_state = {
            "task": "Test HITL and Persistence",
            "plan": [],
            "research_tasks": [],
            "research_task": "",
            "research_chunks": [],
            "content": "",
            "critique": "",
            "human_action": "",
            "human_feedback": "",
            "max_revisions": 2,
            "revision_number": 0,
            "messages": [],
            "sources": []
        }

        # 1. Start the graph. It should run until interrupted before 'human_review_node'.
        print("\n--- Phase 1: Running until interruption ---")
        async for event in graph.astream(initial_state, config=config):
            for key, value in event.items():
                print(f"Finished Node: {key}")
                if "critique" in value:
                    print(f"Critique: {value['critique']}")

        # Check current state
        snapshot = await graph.aget_state(config)
        print("\n--- Snapshot after interruption ---")
        print(f"Next node to run: {snapshot.next}")
        print(f"Current content: {snapshot.values.get('content')}")
        print(f"Current critique: {snapshot.values.get('critique')}")

        if "human_review_node" in snapshot.next:
            print("SUCCESS: Graph paused before human_review_node.")
        else:
            print("FAILURE: Graph did not pause where expected.")
            return

        # 2. Simulate Human Approval (Resume)
        print("\n--- Phase 2: Resuming execution ---")
        async for event in graph.astream(None, config=config):
            for key, value in event.items():
                print(f"Finished Node: {key}")

        # Check final state
        snapshot = await graph.aget_state(config)
        if not snapshot.next:
            print("\nSUCCESS: Graph finished execution.")
        else:
            print(f"\nFAILURE: Graph still has next steps: {snapshot.next}")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(run_test())
