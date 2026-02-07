from langgraph.graph import StateGraph, END
from agent.states import AgentState
from agent.nodes import planner_node, research_router_node, researcher_node, research_merge_node, writer_node, reviewer_node, human_review_node

def should_continue(state: AgentState):
    critique = state.get("critique", "")
    if isinstance(critique, str) and critique.strip().upper().startswith("RESEARCH:"):
        return "research_router"
    if critique == "APPROVE":
        return "human_review_node"
    return "writer"

def human_should_continue(state: AgentState):
    action = state.get("human_action", "")
    if action == "reject":
        return "writer"
    return "end"

def build_graph(checkpointer, visualize: bool = False):
    workflow = StateGraph(AgentState)

    workflow.add_node("planner", planner_node)
    workflow.add_node("research_router", research_router_node)
    workflow.add_node("researcher", researcher_node)
    workflow.add_node("research_merge", research_merge_node)
    workflow.add_node("writer", writer_node)
    workflow.add_node("reviewer", reviewer_node)
    workflow.add_node("human_review_node", human_review_node)

    workflow.set_entry_point("planner")
    workflow.add_edge("planner", "research_router")
    workflow.add_edge("research_router", "researcher")
    workflow.add_edge("researcher", "research_merge")
    workflow.add_edge("research_merge", "writer")
    workflow.add_edge("writer", "reviewer")

    workflow.add_conditional_edges(
        "reviewer",
        should_continue,
        {"human_review_node": "human_review_node", "writer": "writer", "research_router": "research_router"}
    )

    workflow.add_conditional_edges(
        "human_review_node",
        human_should_continue,
        {"writer": "writer", "end": END}
    )

    return workflow.compile(
        checkpointer=checkpointer,
        interrupt_before=["human_review_node"]
    )
