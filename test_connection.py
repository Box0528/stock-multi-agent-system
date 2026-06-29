from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
import os

load_dotenv(dotenv_path=r"D:\normal software\PYproject\Agent工程\.env")

print("Key读取结果:", repr(os.getenv("DEEPSEEK_API_KEY")))  # 调试用

llm = ChatOpenAI(
    model="deepseek-chat",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)

response = llm.invoke("你好，请用一句话介绍你自己。")
print(response.content)