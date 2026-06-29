from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
import os

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

def get_llm(temperature: float = 0.1):
    return ChatOpenAI(
        model="deepseek-chat",
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com",
        temperature=temperature,
    )