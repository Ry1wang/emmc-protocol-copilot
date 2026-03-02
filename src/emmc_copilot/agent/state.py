"""AgentState for the eMMC LangGraph agent."""

from __future__ import annotations

from typing import Annotated

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class AgentState(TypedDict):
    """State schema for the eMMC agent graph.

    messages uses the add_messages reducer so each invocation appends
    rather than overwrites — naturally supports multi-turn conversation.
    """

    messages: Annotated[list[BaseMessage], add_messages]
