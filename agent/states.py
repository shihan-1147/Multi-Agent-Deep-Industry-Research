from typing import TypedDict, List, Annotated, Dict
import operator
from langchain_core.messages import BaseMessage

class AgentState(TypedDict):
    task: str
    plan: List[str]
    research_tasks: List[str]
    research_task: str
    research_chunks: Annotated[List[str], operator.add]
    content: str
    critique: str
    human_action: str
    human_feedback: str
    history_context: str
    max_revisions: int
    revision_number: int
    messages: Annotated[List[BaseMessage], operator.add]
    sources: Annotated[List[Dict[str, str]], operator.add]
