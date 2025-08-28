import os
from datetime import datetime
from typing_extensions import Literal

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, AIMessage, get_buffer_string
from langgraph.graph import StateGraph, START, END
from langgraph.types import Command

from prompts import clarify_trend_request_instructions, transform_messages_into_research_topic_prompt
from state_scope import AgentState, ClarifyWithUser, ResearchQuestion, AgentInputState
from utils import get_today_str
from dotenv import load_dotenv


load_dotenv()


def create_llm():
    provider = os.getenv("LLM_PROVIDER", "google_genai")
    model = os.getenv("LLM_MODEL", "gemini-2.5-flash")
    temperature = float(os.getenv("LLM_TEMPERATURE", "0.1"))

    return init_chat_model(
        model=model,
        model_provider=provider,
        temperature=temperature
    )

# Initialize LLM
model = create_llm() 


def clarify_trend_request(state: AgentState) -> Command[Literal["write_trend_research_brief", "__end__"]]:
    """
    Determine if the user's trend research request contains enough detail to proceed.

    Ensures deterministic, structured output:
    - If sufficient details are present, proceed to trend research brief generation.
    - If critical details are missing (e.g., timeframe, geography, industry), return a clarification question instead.
    - Prevents hallucination by strictly routing to either clarification or research initiation.
    """
    structured_output_model = model.with_structured_output(ClarifyWithUser)

    response = structured_output_model.invoke([
        HumanMessage(content=clarify_trend_request_instructions.format(
            messages=get_buffer_string(messages=state["messages"]), 
            date=get_today_str()
        ))
    ])

    if response.need_clarification:
        return Command(
            goto=END, 
            update={"messages": [AIMessage(content=response.question)]}
        )
    else:
        return Command(
            goto="write_trend_research_brief", 
            update={"messages": [AIMessage(content=response.verification)]}
        )

def write_trend_research_brief(state: AgentState):
    """
    Transform the conversation history into a comprehensive trend research brief.

    Ensures structured output by:
    - Converting user messages into a clear, detailed brief focused on trend analysis.
    - Including all stated user preferences (timeframe, geography, industry, audience).
    - Explicitly noting any unspecified but important dimensions as open considerations.
    - Guaranteeing the final brief follows the required format for effective trend research.
    """
    # Set up structured output model
    structured_output_model = model.with_structured_output(ResearchQuestion)

    # Generate research brief from conversation history
    response = structured_output_model.invoke([
        HumanMessage(content=transform_messages_into_research_topic_prompt.format(
            messages=get_buffer_string(state.get("messages", [])),
            date=get_today_str()
        ))
    ])

    # Update state with generated research brief and pass it to the supervisor
    return {
        "research_brief": response.research_brief,
        "supervisor_messages": [HumanMessage(content=f"{response.research_brief}.")]
    }

workflow = StateGraph(AgentState, input_schema=AgentInputState)

workflow.add_node("clarify_trend_request", clarify_trend_request)
workflow.add_node("write_trend_research_brief", write_trend_research_brief)

workflow.add_edge(START, "clarify_trend_request")
workflow.add_edge("write_trend_research_brief", END)

graph = workflow.compile()
