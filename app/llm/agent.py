from sqlalchemy.orm import Session
from app.workflow.planner import build_day_context
from app.memory.store import retrieve_relevant_memories
import os
import requests

# Ollama endpoint
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://ollama:11434")

def get_ollama_response(prompt: str, model: str = "llama3.2") -> str:
    """Get response from Ollama"""
    try:
        response = requests.post(
            f"{OLLAMA_HOST}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False
            }
        )
        response.raise_for_status()
        return response.json()["response"]
    except Exception as e:
        raise RuntimeError(f"Ollama error: {str(e)}")

SYSTEM_PROMPT = """
You are a personal cognitive assistant. Your job is to:
1. Help the user plan their day based on tasks and priorities
2. Surface relevant memories when answering questions
3. Give direct, actionable recommendations — no fluff
4. Use the Eisenhower Matrix logic when prioritizing
Always be concise. Max 3-5 bullet points unless asked for more.
"""

def generate_daily_plan(db: Session) -> str:
    """Generate daily plan using Ollama"""
    context = build_day_context(db)
    
    full_prompt = f"""{SYSTEM_PROMPT}

Generate my daily plan based on this context:

{context}"""
    
    return get_ollama_response(full_prompt, model="llama3.2")

def query_with_memory(db: Session, user_query: str) -> str:
    """
    Retrieves relevant memories via FAISS,      
    injects them as context, then calls Ollama LLM.
    """
    # Detect casual greetings
    casual_greetings = ["hi", "hello", "hey", "yo", "sup", "what's up", "whats up", "howdy"]
    if user_query.strip().lower() in casual_greetings:
        return """Hey! 👋 I'm your cognitive assistant. I can help you:

• **Plan your day** based on tasks and energy levels
• **Remember important info** using semantic memory
• **Manage tasks** and prioritize effectively
• **Answer questions** using your stored memories

What would you like help with?"""
    
    # Normal query processing (keep existing code)
    relevant_memories = retrieve_relevant_memories(db, user_query, top_k=5)

    memory_context = "\n".join([
        f"- [{m.category}] {m.content}"
        for m in relevant_memories
    ]) or "No relevant memories found."

    full_prompt = f"""{SYSTEM_PROMPT}

User query: {user_query}

Relevant memories from user's history:
{memory_context}

Answer the query using the memories as context where relevant."""

    return get_ollama_response(full_prompt, model="llama3.2")
