from pydantic import BaseModel
from typing import Optional, List, Dict

class ResearchRequest(BaseModel):
    topic: str

class FeedbackRequest(BaseModel):
    thread_id: str
    action: str  # 'approve' or 'reject'
    feedback: Optional[str] = None

class HistorySaveRequest(BaseModel):
    thread_id: str
    topic: str
    report: str
    sources: Optional[List[Dict[str, str]]] = None

class HistoryFollowupRequest(BaseModel):
    history_id: int
    question: str
