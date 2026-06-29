import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import HumanMessage, SystemMessage
from config import get_llm

llm = get_llm(temperature=0.1)

SYSTEM_PROMPT = """你是一位严格的风控经理，负责对投资建议进行最终风险审核。

你会收到综合报告、技术数据，以及可能包含的历史风控记录。

职责：
1. 如果有历史风控记录，必须参考历史风险模式
2. 评估当前风险等级（低/中/高/极高）
3. 扫描五大风险信号
4. 给出仓位上限和最终结论

输出格式：

## 风控评估报告

### 风险等级：🟢低 / 🟡中 / 🔴高 / ⛔极高

### 历史风险回顾（如有历史记录必填）
（该股票历史上的风险模式，与本次对比）

### 风险信号扫描
| 风险项 | 状态 | 说明 |
|--------|------|------|
| 换手率过热 | ✅正常 / ⚠️警告 | ... |
| 追高风险   | ✅正常 / ⚠️警告 | ... |
| ST风险     | ✅正常 / ⚠️警告 | ... |
| 资金流向   | ✅正常 / ⚠️警告 | ... |
| 舆情风险   | ✅正常 / ⚠️警告 | ... |

### 仓位上限建议
- 风控允许最高仓位：XX%
- 理由：（一句话）

### 风控结论
（维持买入建议 / 下调至观望 / 建议回避）
"""

def run_risk_manager(
    stock_name:       str,
    supervisor_summary: str,
    technical_report: str,
    risk_history:     str = "",
) -> str:
    history_block = ""
    if risk_history:
        history_block = f"\n---\n## 历史风控记录（请重点参考）\n{risk_history}\n"

    user_content = f"""
请对【{stock_name}】的投资建议进行风控审核：

---
## 基金经理综合报告
{supervisor_summary}

---
## 技术分析原始数据
{technical_report[:1000]}
{history_block}
"""
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=user_content),
    ]
    response = llm.invoke(messages)
    return response.content


if __name__ == "__main__":
    result = run_risk_manager(
        stock_name="有研新材",
        supervisor_summary="综合评级3星，建议观望。",
        technical_report="换手率8%，涨幅2.3%。",
        risk_history="历史上有1次高风险记录：追高风险。",
    )
    print(result)