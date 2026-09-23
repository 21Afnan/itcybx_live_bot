# src/agent/graph.py

from typing import TypedDict, Annotated, Sequence, Literal
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_mistralai import ChatMistralAI
from langgraph.graph import StateGraph, END, START
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver

from src.config.settings import MISTRAL_API_KEY, LLM_MODEL
from src.tools.faq_tool import search_knowledge_base
from src.tools.booking_tool import check_availability, book_meeting
from src.agent.prompts_en import SYSTEM_PROMPT_EN
from src.agent.prompts_ar import SYSTEM_PROMPT_AR
from src.utils.logger import get_logger

logger = get_logger("AgentGraph")


class AgentState(TypedDict):
    """LangGraph state schema representing conversation messages and metadata."""
    messages: Annotated[Sequence[BaseMessage], add_messages]
    language: str  # 'en' or 'ar'


class ItCybxAgent:
    """
    Orchestrates the LangGraph agent for IT Cybx with tool calling,
    multi-turn memory checkpointing, and bilingual support.
    """

    def __init__(self):
        logger.info(f"Initializing ChatMistralAI (model: '{LLM_MODEL}')...")
        self.llm = ChatMistralAI(
            model=LLM_MODEL,
            api_key=MISTRAL_API_KEY,
            temperature=0.1,  # Low temperature for factual precision
        )

        # Registered tools for FAQ RAG and Meeting Booking
        self.tools = [search_knowledge_base, check_availability, book_meeting]
        self.llm_with_tools = self.llm.bind_tools(self.tools)

        # Build and compile graph
        self.memory = MemorySaver()
        self.graph = self._build_graph()
        logger.info("LangGraph IT Cybx Agent compiled successfully.")

    def _call_model(self, state: AgentState) -> dict:
        """Invokes Mistral LLM with system prompt and message history."""
        messages = list(state["messages"])
        language = state.get("language", "en")

        # If the last message is a ToolMessage from check_availability or book_meeting,
        # return the pre-formatted message directly to guarantee all slots & links are presented.
        if messages and isinstance(messages[-1], ToolMessage):
            last_tool = messages[-1]
            tool_name = getattr(last_tool, "name", None)
            if not tool_name and last_tool.tool_call_id:
                for msg in reversed(messages[:-1]):
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        for tc in msg.tool_calls:
                            if tc.get("id") == last_tool.tool_call_id:
                                tool_name = tc.get("name")
                                break
                    if tool_name:
                        break

            if tool_name in ["check_availability", "book_meeting"]:
                logger.info(f"Directly returning formatted output for tool '{tool_name}'")
                return {"messages": [AIMessage(content=last_tool.content)]}

        # Select matching system prompt
        system_prompt = SYSTEM_PROMPT_AR if language == "ar" else SYSTEM_PROMPT_EN

        # Ensure SystemMessage is at the top of context
        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=system_prompt)] + messages
        else:
            # Update system prompt if language changed
            messages[0] = SystemMessage(content=system_prompt)

        response = self.llm_with_tools.invoke(messages)
        return {"messages": [response]}

    def _should_continue(self, state: AgentState) -> Literal["tools", "__end__"]:
        """Determines whether to call a tool or finish the turn."""
        last_message = state["messages"][-1]

        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            logger.info(f"LLM decided to call {len(last_message.tool_calls)} tool(s): {[tc['name'] for tc in last_message.tool_calls]}")
            return "tools"
        return END

    def _build_graph(self):
        """Constructs the state machine graph nodes and edges."""
        workflow = StateGraph(AgentState)

        # 1. Define Nodes
        workflow.add_node("agent", self._call_model)
        workflow.add_node("tools", ToolNode(self.tools))

        # 2. Define Edges
        workflow.add_edge(START, "agent")
        workflow.add_conditional_edges(
            "agent",
            self._should_continue,
            {
                "tools": "tools",
                END: END,
            }
        )
        workflow.add_edge("tools", "agent")

        # 3. Compile with in-memory checkpointer
        return workflow.compile(checkpointer=self.memory)

    def chat(self, user_message: str, thread_id: str = "default_session", language: str = "auto") -> str:
        """
        Processes a user turn and returns the final assistant response string.
        Automatically detects Arabic script if language is 'auto'.
        """
        # Auto-detect language if requested or if Arabic characters exist
        if language == "auto":
            has_arabic = any('\u0600' <= char <= '\u06FF' or '\u0750' <= char <= '\u077F' for char in user_message)
            detected_lang = "ar" if has_arabic else "en"
        else:
            detected_lang = language.lower()

        config = {"configurable": {"thread_id": thread_id}}
        inputs = {
            "messages": [HumanMessage(content=user_message)],
            "language": detected_lang,
        }

        logger.info(f"Processing chat turn for thread '{thread_id}' [lang={detected_lang}]: '{user_message}'")
        output = self.graph.invoke(inputs, config=config)
        
        last_msg = output["messages"][-1]
        return last_msg.content


# Reusable singleton instance
_agent_instance: ItCybxAgent = None


def get_agent() -> ItCybxAgent:
    """Returns or creates the singleton ItCybxAgent instance."""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = ItCybxAgent()
    return _agent_instance


if __name__ == "__main__":
    agent = get_agent()
    print("\n=======================================================")
    print("             LANGGRAPH AGENT TEST RUN                  ")
    print("=======================================================")
    
    response = agent.chat("Hi! Can you tell me what the Growth Audit is and how much it costs?", thread_id="test_run_1", language="en")
    print("\n[BOT RESPONSE]:\n" + response + "\n")
