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
from src.tools.lead_tool import capture_lead
from src.tools.escalation_tool import escalate_to_human
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
            max_retries=6,
            timeout=30,
        )

        # Registered tools for FAQ RAG, Lead Capture, Escalation, and Booking
        self.tools = [search_knowledge_base, capture_lead, escalate_to_human, check_availability, book_meeting]
        self.llm_with_tools = self.llm.bind_tools(self.tools)

        # Build and compile graph
        self.memory = MemorySaver()
        self.graph = self._build_graph()
        logger.info("LangGraph IT Cybx Agent compiled successfully.")

    def _call_model(self, state: AgentState) -> dict:
        """Invokes Mistral LLM with system prompt and message history."""
        import time
        messages = list(state["messages"])
        language = state.get("language", "en")

        # If the last message is a ToolMessage from action tools,
        # return the pre-formatted message directly to guarantee exact rendering.
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

            if tool_name in ["capture_lead", "escalate_to_human", "check_availability", "book_meeting"]:
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

        # Robust execution with exponential backoff on 429 rate limits
        for attempt in range(5):
            try:
                response = self.llm_with_tools.invoke(messages)
                return {"messages": [response]}
            except Exception as e:
                err_str = str(e).lower()
                if "429" in err_str or "rate limit" in err_str:
                    wait_time = (attempt + 1) * 2.5
                    logger.warning(f"Mistral 429 rate limit hit. Retrying in {wait_time}s (attempt {attempt + 1}/5)...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Error invoking LLM: {e}")
                    raise e
        # Final attempt
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

    @staticmethod
    def _clean_closing_filler(text: str) -> str:
        """Strips out repetitive closing sales pitches, CTAs, and markdown divider dashes."""
        import re
        # 1. Strip trailing sales pitch/CTAs (English and Arabic)
        patterns = [
            r"(?:\n+|^)(?:[-*—_]{2,}\s*)?\s*(?:Would you like to explore|Let me know if you(?:'re|’re| are) interested|How would you like to proceed|How can I assist you further|Feel free to reach out).*$",
            r"(?:\n+|^)(?:[-*—_]{2,}\s*)?\s*(?:هل ترغب في استكشاف|أخبرني إذا كنت مهتماً|كيف يمكنني مساعدتك أكثر|هل تود).*$",
        ]
        cleaned = text
        for p in patterns:
            cleaned = re.sub(p, "", cleaned, flags=re.DOTALL | re.IGNORECASE)

        # 2. Strip standalone horizontal divider lines (e.g. ---, ___, *** on their own line)
        cleaned = re.sub(r'^[ \t]*(?:-[ \t]*){3,}$', '', cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r'^[ \t]*(?:_[ \t]*){3,}$', '', cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r'^[ \t]*(?:\*[ \t]*){3,}$', '', cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r'^[ \t]*(?:---|\*\*\*|___)(?:[ \t]+(?:---|\*\*\*|___))*[ \t]*$', '', cleaned, flags=re.MULTILINE)

        # 3. Collapse excess consecutive blank lines
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)

        return cleaned.strip()

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
        raw_content = last_msg.content
        return self._clean_closing_filler(raw_content) if isinstance(raw_content, str) else raw_content


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
