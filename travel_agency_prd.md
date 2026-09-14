# PRD: AI Travel Planner (Multi-Agent Trip Recommendation System)

给 Claude Code 的实现说明文档。目标：把课堂学的 CrewAI Supervisor/Parallel 模式落地成一个真实能跑的 web app。

---

## 1. 产品目标

用户输入行程日期、同行人数、人均预算 → 系统用 5 个 agent（4 个 region researcher + 1 个 supervisor）并行调研 North America / Europe / Asia / Oceania 四个 region 的最优行程，supervisor 综合四份方案给出最终推荐 → 用户看到推荐结果，并可以跳转到一个独立的 trace 页面，看每个 agent 的完整思考过程和 output。

---

## 2. 架构设计：为什么这样分工（对应课堂的六个模式）

**先说清楚这不是纯 Supervisor/Workers（Pattern 4），而是 Parallel Fan-out（Pattern 3）+ 一个综合评判的 Synthesizer 步骤。**

原因：Pattern 4 的核心是 supervisor **动态决定**该派哪个 worker、派几次、什么时候停——这适合"不确定要问谁"的场景。但这里 4 个 region 是固定的、永远都是这 4 个，不需要 supervisor 动态判断"该找谁"，只需要 4 个 researcher 各自独立、同时跑，最后由一个 agent 做"从 4 份方案里选最优"。这更接近课件里 Pattern 3 的 Voting/Sectioning 变体：4 个 researcher 是 sectioning（各管一个 region），最后 supervisor 做的事更像一个轻量级 evaluator（挑最优，不是"生成→打回重写"的循环）。

**结论：用 CrewAI 的 `Process.sequential` + 4 个 `async_execution=True` 的 research task 并行跑 + 1 个 `context=[4个task]` 的 synthesis task 收尾。** 不用 `Process.hierarchical`。理由是 hierarchical 需要一个 manager_llm 去动态即兴分派，多一层不确定性、多几次 LLM 调用，而这里的分工本来就是确定的——这正是课件反复强调的"不要默认上最复杂的模式，从证据出发"。如果以后想让 region 数量可变（比如用户可以自定义想去哪几个大洲），再升级成 hierarchical 或 routing 模式。

---

## 3. Agent 设计

### 3.1 四个 Region Researcher（并行，Pattern 3 sectioning）

每个 agent 配置：

```python
from crewai import Agent
from crewai_tools import SerperDevTool

search_tool = SerperDevTool()

def make_researcher(region: str) -> Agent:
    return Agent(
        role=f"{region} Travel Researcher",
        goal=(
            f"Find the single best itinerary in {region} for the given dates, "
            f"traveler count, and per-person budget. Consider seasonal weather/climate "
            f"suitability, and realistic price estimates (flights + hotels + activities)."
        ),
        backstory=(
            f"A travel specialist who has planned hundreds of {region} trips. "
            f"Sceptical of generic recommendations — always checks actual seasonal "
            f"conditions for the specific travel dates before suggesting a destination."
        ),
        tools=[search_tool],
        verbose=True,
    )
```

四个 region 名：`North America`, `Europe`, `Asia`, `Oceania`（写死在代码里，不是 agent 自己决定的）。

### 3.2 每个 Researcher 的 Task

```python
from crewai import Task

def make_research_task(agent: Agent, region: str, trip: dict) -> Task:
    return Task(
        description=(
            f"Research {region} and propose ONE best itinerary for a trip with:\n"
            f"- Dates: {trip['start_date']} to {trip['end_date']}\n"
            f"- Travelers: {trip['travelers']}\n"
            f"- Budget: {trip['budget_per_person']} {trip['currency']} per person\n\n"
            f"Search for: seasonal weather/climate at the travel dates, typical flight "
            f"and hotel prices for that period, and 1-2 destination candidates within "
            f"{region} that best fit the season and budget. Pick ONE final destination "
            f"and build a day-by-day itinerary."
        ),
        expected_output=(
            "A JSON object with fields: region, destination_city_country, "
            "climate_summary, estimated_total_cost_per_person, budget_fit "
            "('under'/'on_target'/'over'), day_by_day_itinerary (list of "
            "{day, activities}), and a 2-3 sentence rationale for why this is "
            "the best pick in this region for these dates."
        ),
        agent=agent,
        async_execution=True,
    )
```

### 3.3 Supervisor（Synthesizer，最后一步，等 4 个 task 都完成）

```python
supervisor = Agent(
    role="Trip Supervisor",
    goal=(
        "Compare four regional itinerary proposals and select the single best "
        "one for the client, considering climate fit, budget fit, and overall value."
    ),
    backstory=(
        "A senior travel consultant who makes the final call across all regions. "
        "Rejects a proposal if it clearly overshoots budget or has bad seasonal timing, "
        "prefers the next-best option in that case."
    ),
    verbose=True,
)

final_task = Task(
    description=(
        "You have four regional itinerary proposals (North America, Europe, Asia, "
        "Oceania) as context. Compare them on: (1) climate/season suitability, "
        "(2) budget fit against the per-person budget, (3) overall value/experience. "
        "Pick the single best one. If the top choice is over budget by more than 15%, "
        "pick the next best instead and say why."
    ),
    expected_output=(
        "A JSON object: {recommended_region, destination, reasoning (why this beat "
        "the other three, referencing each briefly), itinerary (from the winning "
        "researcher, unchanged), estimated_total_cost_per_person, all_four_summaries "
        "(one-line verdict per region, including why the other three were not chosen)}."
    ),
    agent=supervisor,
    context=[na_task, eu_task, asia_task, oceania_task],  # 等四个并行task都完成
)
```

`context=[...]` 是 CrewAI 里"等异步任务完成再继续"的标准写法（对应课件 pipeline 里 wiring 的 `context=[research, angle]`，这里是 4 个并行任务的 fan-in 版本）。

### 3.4 Crew 组装

```python
from crewai import Crew, Process

crew = Crew(
    agents=[na_researcher, eu_researcher, asia_researcher, oceania_researcher, supervisor],
    tasks=[na_task, eu_task, asia_task, oceania_task, final_task],
    process=Process.sequential,
    verbose=True,
)

result = crew.kickoff(inputs=trip_requirements)
```

---

## 4. Trace 记录机制（跑完后完整展示，非实时流式）

**目的**：对应课件反复强调的"verbose log 是你唯一能看到 who decided what 的窗口"。这里要把这个 log 从终端搬到网页上。

**实现方式**：用 CrewAI 的 `step_callback`（每个 agent 每一步 thought/action/observation 触发一次）和 `task_callback`（每个 task 完成时触发一次，拿到该 task 的最终 output），把这些事件收集进一个结构化的 list，run 结束后整体存成一份 JSON，供前端读取展示。不做 WebSocket 实时推送（MVP 先跑通，这是能砍的复杂度）。

```python
trace_log = []

def on_step(step):
    trace_log.append({
        "type": "step",
        "agent": getattr(step, "agent", None),
        "thought": getattr(step, "thought", None) or str(step),
        "timestamp": datetime.utcnow().isoformat(),
    })

def on_task_done(task_output):
    trace_log.append({
        "type": "task_complete",
        "agent": task_output.agent,
        "output": task_output.raw,
        "timestamp": datetime.utcnow().isoformat(),
    })

crew = Crew(
    agents=[...],
    tasks=[...],
    process=Process.sequential,
    step_callback=on_step,
    task_callback=on_task_done,
    verbose=True,
)
```

跑完之后把 `trace_log` 和 `result` 一起存到一次 run 的记录里（内存 dict 或 SQLite 都行，MVP 用内存 + 一个 `run_id` 就够），前端拿 `run_id` 去查两个东西：最终推荐结果、完整 trace。

---

## 5. 技术栈 & 项目结构

- 后端：FastAPI（Python），直接跑 CrewAI，无需额外队列（MVP 阶段同步执行，请求可能等 30秒-2分钟，前端要有 loading 状态）
- 前端：原生 HTML + vanilla JS，两个页面，不引入框架
- 依赖：`crewai`, `crewai[tools]`（含 SerperDevTool）, `fastapi`, `uvicorn`, `python-dotenv`

```
travel-planner/
├── backend/
│   ├── main.py                 # FastAPI app + 路由
│   ├── crew.py                 # agent/task/crew 定义（第3、4节的代码）
│   ├── models.py                # Pydantic request/response models
│   ├── trace_store.py          # 内存存储 run_id -> {result, trace_log}
│   └── .env                    # SERPER_API_KEY, OPENAI_API_KEY (或其他LLM key)
├── frontend/
│   ├── index.html               # 输入表单 + 结果展示页
│   ├── trace.html                # trace 详情页
│   ├── app.js
│   └── style.css
└── requirements.txt
```

---

## 6. API 设计

### POST /api/plan-trip

请求：
```json
{
  "start_date": "2026-12-10",
  "end_date": "2026-12-20",
  "travelers": 2,
  "budget_per_person": 2000,
  "currency": "USD"
}
```

响应（同步等待，跑完才返回；MVP 不做异步轮询）：
```json
{
  "run_id": "run_abc123",
  "recommendation": {
    "recommended_region": "Asia",
    "destination": "...",
    "reasoning": "...",
    "itinerary": [...],
    "estimated_total_cost_per_person": 1850,
    "all_four_summaries": [
      {"region": "North America", "verdict": "..."},
      {"region": "Europe", "verdict": "..."},
      {"region": "Asia", "verdict": "..."},
      {"region": "Oceania", "verdict": "..."}
    ]
  }
}
```

### GET /api/trace/{run_id}

响应：
```json
{
  "run_id": "run_abc123",
  "trace": [
    {"type": "step", "agent": "North America Travel Researcher", "thought": "...", "timestamp": "..."},
    {"type": "task_complete", "agent": "North America Travel Researcher", "output": "...", "timestamp": "..."}
  ]
}
```

---

## 7. 前端页面

**index.html（输入 + 结果）**
- 表单：start_date, end_date（日期选择器）, travelers（数字输入）, budget_per_person（数字输入）, currency（下拉，默认 USD/SGD）
- 提交后显示 loading（跑完可能要 1-2 分钟，因为 5 个 agent 都要调用 LLM + 搜索，明确告诉用户"AI 正在调研四大洲，预计需要1-2分钟"）
- 结果区：推荐的 region + destination + 理由 + day-by-day 行程 + 一个"查看完整 AI 决策过程"按钮，跳到 trace.html?run_id=xxx

**trace.html（agent 轨迹）**
- 按 agent 分组（4 个 researcher + supervisor，5 个 section）
- 每个 agent 下面按时间顺序列出它的 thought/action，最后展示它的最终 output（JSON 折叠展示，可展开）
- 顶部提示一句类似课件的话："This is the trace — who decided what, in what order."（可以中文替换，帮助用户理解 multi-agent 系统怎么协作）

---

## 8. 关键边界情况

- **搜索无结果/API 报错**：某个 researcher 的 search tool 调用失败，该 agent 应该用已有知识给出保守估计，并在 output 里注明"数据来源受限，为估算值"，不能让整个 crew 因为一个 region 搜索失败就崩掉
- **budget 明显不现实**（比如人均 $50 要去 Europe 10天）：researcher 应如实报告"当前预算下只能找到经济型方案"，不要瞎编凑数
- **日期跨年/跨季**：agent 要按实际日期判断季节（比如 12月的 Southeast Asia 是旱季，12月的 New Zealand 是夏季），不能只看月份不看半球

---

## 9. 环境变量（.env）

```
OPENAI_API_KEY=...       # 或换成 Anthropic/其他 LLM provider
SERPER_API_KEY=...       # serper.dev 注册免费拿，前 2500 次查询免费
```

`crewai[tools]` 里的 `SerperDevTool` 直接读 `SERPER_API_KEY` 环境变量，不用手动传参。

---

## 10. MVP 范围 vs 可以往后加的

**MVP 必须有**：
- 4 region 并行 researcher + supervisor synthesis，跑通端到端
- 输入表单 → 调用 crew → 展示推荐结果
- Trace 页面（跑完后展示，非实时）

**先不做（有余力再加）**：
- 实时 WebSocket 推送 trace（课件里也提到这是能砍的复杂度，先用"跑完后完整展示"）
- 用户账号/历史行程保存（用内存存 run_id 即可，不用数据库和登录）
- 让用户自定义要比较哪几个 region（目前写死 4 个，这是保持 Pattern 3 simplicity 的关键假设，改成可变数量就要考虑要不要换成 routing 模式）
- 多语言支持

---

## 11. 建议的实现顺序（给 Claude Code）

1. 先写 `crew.py`，用假的 trip 数据在命令行跑通整个 5-agent crew（不接 FastAPI，先确认 CrewAI 逻辑本身没问题，尤其是 `async_execution` + `context` 的 fan-in 是否真的并行、真的等齐）
2. 加 `step_callback`/`task_callback`，确认 trace_log 结构符合预期
3. 包一层 FastAPI（`main.py` + `models.py` + `trace_store.py`），跑通 `POST /api/plan-trip` 和 `GET /api/trace/{run_id}`
4. 写最简单的 `index.html`（表单 + fetch API + 展示结果），确认端到端能跑
5. 写 `trace.html`，展示第2步验证过的 trace 结构
6. 补边界情况处理（第8节）

每一步都能跑起来再进下一步，不要一次性把所有代码写完再测——这也是课件里反复强调的"small beats grand"。
