# 校园课程智能助手 · AI Agent + RAG + MCP 全栈项目

一个把「大模型 Agent 接管教务业务」这件事**做完整、做到能上生产讨论**的示例项目。

不是 demo 级拼装：身份带外透传防越权、写操作人工审批、AI 操作全量审计、
检索质量有量化评测、安全项有自动化自检。

```
FastAPI + LangChain create_agent + FastMCP + Chroma + Vue3
```

---

## 一、30 秒跑起来

双击 `scripts/run.bat`，菜单选 `1`。三个服务会各自开一个窗口起起来，
就绪后自动打开浏览器。

| 服务 | 地址 | 说明 |
|---|---|---|
| 前端 | http://127.0.0.1:5173 | 界面 |
| 业务后端 | http://127.0.0.1:18000 | REST + Agent 编排 + RAG |
| 接口文档 | http://127.0.0.1:18000/docs | Swagger |
| MCP 工具服务 | http://127.0.0.1:18001/mcp | 模型可调用的工具 |

演示账号（密码都是 `123456`）：

| 账号 | 角色 | 说明 |
|---|---|---|
| `20230101` | 学生 | 张思远，有 6 门历史成绩，适合演示查成绩 |
| `20230102` | 学生 | 李佳琪，空课表，适合演示选课 |
| `admin` | 管理员 | 可看全部人的审计日志 |

**不需要任何 API Key**。项目自带一个脚本假模型（见第五节），
链路是真的，只有"推理"是规则模拟的。

### 菜单其他选项

- `3` 查看状态 —— 三个端口 + 模型 + 向量库 + MCP 连通性
- `4` 重建知识库索引
- `5` 运行链路自检 —— **32 项检查**，这是本项目的**验收凭证**

### 手工启动（不用脚本）

```bash
# 1. MCP 工具服务
cd campus-agent && python -m mcp_server.server

# 2. 业务后端
cd campus-agent/backend && python -m app.main

# 3. 前端
cd campus-agent/frontend && npm install && npm run dev
```

---

## 二、三个进程，各管什么

```
                    ┌──────────────────────────┐
   浏览器  ────SSE──►│  FastAPI  :18000         │
   :5173            │  · 业务 REST             │
                    │  · JWT 鉴权              │
                    │  · Agent 编排            │
                    │  · RAG 检索              │
                    │  · SSE 网关              │
                    └────────┬─────────────────┘
                             │ 短票据放 HTTP 头
                             ▼
                    ┌──────────────────────────┐
                    │  FastMCP  :18001         │
                    │  · 7 个工具（5读2写）     │
                    │  · 纯薄适配层             │
                    └────────┬─────────────────┘
                             │ 原样转发票据
                             ▼
                    回调 /api/* 业务接口 → 业务规则在此裁决
```

### 为什么 MCP 服务走 HTTP 回调业务接口，而不是直连数据库

| 维度 | 直连数据库 | **走 HTTP（本项目做法）** |
|---|---|---|
| 权限校验 | 要在 MCP 侧重写一套，规则必然漂移 | 复用业务鉴权，**单一真相源** |
| 身份传递 | 只能塞进工具参数，**模型可伪造** | 走 HTTP 头，模型看不到也改不了 |
| 业务规则 | 状态机/校验要重写一遍 | 直接复用 |
| MCP 定位 | 变成"第二套后端" | 干净的薄适配层 |

---

## 三、功能清单

### 业务侧
- JWT 登录鉴权（正式票据 12 小时 / MCP 短票据 5 分钟）
- 课程列表、搜索、类别筛选、余量显示
- **选课**：容量、时间冲突、先修课、学分上限、重复选课五重校验
- **原子占座**：`courses.enrolled_count` 用条件 UPDATE 维护，并发抢最后一个座位不会超卖
- **退课**：已出成绩的课不可退
- 课表、成绩、加权均分与 GPA 计算
- 审计日志：区分 WEB / AI 来源，记录成功 / 拒绝 / 失败
- 审批台账：**被拒绝的操作也留痕**，并记录最终执行结果
  （SUCCESS / FAILED / REJECTED / NOT_EXECUTED）

### Agent 侧
- LangChain `create_agent` + ReAct 循环
- **7 个 MCP 工具**：课程查询、课程详情、我的课表、我的成绩、知识库检索、选课、退课
- **SSE 流式**：思考 → 调工具 → 工具返回 → 逐字回答，全过程前端可见
- **写操作人工审批**：选课/退课必须用户点"批准"才执行；多个操作可逐项批准/拒绝
- **身份带外透传**：工具参数里没有任何身份字段，Agent 无法越权
- **会话按用户隔离**：`thread_id` 统一加 `u<user_id>:` 命名空间，
  换号或伪造他人 thread_id 既不能续写会话，也不能替他人审批

### RAG 侧
- 6 份校园规章制度文档，切出 59 个 chunk
- **Chroma 向量召回 + BM25 关键词召回，RRF 融合**
- 检索质量有量化评测：**Hit@1 83.3%、Hit@3 100%**（18 条标注查询）
- 无 Key 时用本地哈希向量兜底，开箱可用

---

## 四、界面预览

`docs/screenshots/` 下的截图**不是手工摆拍的**，由 `scripts/browser_verify.py`
用无头 Chrome + CDP 自动跑出来：注入登录态 → 逐页切换 → 点击快捷提问
→ 真实触发审批 → 点「拒绝」→ 全程截图。所以截图本身就等于一次端到端验收。

> 注：P0 加固后审批卡片改为逐项批准/拒绝、审批台账新增「执行结果」列，
> 现有 `04` / `08` 截图需要重跑 `browser_verify.py` 更新（见 `待测试.md`）。

| 截图 | 证明什么 |
|---|---|
| `01-登录页.png` | Vue 挂载 + 演示账号从后端拉取渲染 |
| `02-智能助手.png` | 快捷提问、假模型状态明示（不让人误以为接了真模型） |
| `03-对话-ReAct与流式.png` | 步骤时间线、工具调用卡片、逐字流式回答、带【依据】溯源 |
| `04-写操作审批卡片.png` | 写操作被拦下，显示工具名与参数，给出批准/拒绝按钮 |
| `05-拒绝后回复.png` | 拒绝后模型解释「因为你拒绝了，所以没有执行」 |
| `06-课程列表.png` | 搜索、类别筛选、余量红绿标识 |
| `07-我的课表与成绩.png` | 周一至周日 × 节次的课表网格 + 绩点卡片 |
| `08-审计与安全.png` | WEB/AI 操作对比、**安全自检 4 项全绿**、审批台账 |

审计页那个「安全自检」区块是这套系统的核心论证，它直接调 `/api/agent/tools`
把四个上线必查项算成结论：MCP 连接、工具描述完整性、
**身份字段没有泄漏到工具参数里**、**所有写工具都已纳入审批**。

---

## 五、四个值得单独说的设计

### 1. 身份带外透传 —— Agent 越权的根治办法

**问题**：如果工具签名是 `enroll_course(student_no, course_code)`，
那么 `student_no` 就成了模型可见、可改的参数。
一句「我是 20230102，帮我选课」就能让 Agent 代别人操作。

**做法**：身份不进工具参数，只走 HTTP 头。

```
前端 POST /api/agent/chat（头带正式票据）
  → 后端解析出 user_id，签一张「仅本会话有效」的 5 分钟短票据
  → 为【本次请求】新建 MultiServerMCPClient，短票据放进 headers
  → Agent 调工具，请求带短票据到 MCP Server
  → MCP 从 ctx.request_context.request.headers 取出短票据
  → 工具用 httpx 调业务接口，票据原样放进 Authorization
  → 业务接口照常鉴权 → 越权在这里被拒
```

`MultiServerMCPClient` 的 `headers` 是**构造时静态的**，
所以**必须每个请求新建一个实例**，否则用户身份会串号。
代价是每请求多一轮本地 MCP 握手（毫秒级），换的是身份绝不串号。

**会话 id 也必须隔离**：`thread_id` 由客户端传入，如果直接当 checkpointer key，
拿到别人 thread_id 的人就能续写对方会话。现在统一加 `u<user_id>:` 前缀
（`agent/session.py`），且对服务端返回的完整 id 保持幂等；`/api/agent/resume`
还会校验会话存在且确实有待审批中断，否则直接 409。

### 2. 人工审批 —— 只拦写工具

```python
HumanInTheLoopMiddleware(interrupt_on={"campus_enroll_course": True,
                                       "campus_drop_course": True})
```

- **读工具不登记** → 不会出现"查个课表还要审批"这种骚扰，误拦率为 0
- 拒绝后框架自动生成一条带拒绝理由的 `ToolMessage` 回灌给模型，
  模型据此向用户解释 —— 这条消息本身就是审计记录
- **拒绝即无副作用**：自检脚本会核对业务表条数，证明拒绝真的生效
- **逐项审批**：一个中断里可能有多个写操作，前端逐项选择批准/拒绝，
  后端 `decisions` 与待审批台账按顺序一一对应；数量不匹配直接 400
- **批准 ≠ 成功**：台账先记 `pending → approved/rejected`，
  再根据 `tool_result` 回填最终结果（SUCCESS / FAILED / NOT_EXECUTED），
  不会出现"已批准但根本没执行"却看不出来的情况

清单放在 `backend/app/agent/policy.py`，并有一个覆盖性审计：
MCP 暴露了名字带写动词、但不在审批清单里的工具时会告警。
避免「新加了写工具但忘了登记审批」这种致命疏漏。

### 3. 混合检索 —— 为什么最后选了 RRF

单个知识库 59 个 chunk，向量和 BM25 谁都不够用：

- **单用向量**：本地哈希 embedding 只有词面能力，高频词（「学分」）权重过高，
  问「一学期最多能选多少学分」会把「创新学分」排第一
- **单用 BM25**：抓不到同义改写（「我不想上了」vs「退课」）

融合方式试过三种，最后用 RRF：

| 融合方式 | Hit@1 | 问题 |
|---|---|---|
| 加权求和 + min-max 归一化 | 差 | 把只命中一个通用词的噪声文档顶到 BM25 满分 |
| 加权求和 + 按最大值归一化 | 好转 | 量纲仍不可比，部分查询错排 |
| **RRF（倒数排名融合）** | **83.3%** | 只用排名不用分数，彻底绕开量纲问题 |

RRF 公式：`score = Σ 1/(60 + rank_i)`，60 是文献默认值。

另外两个细节：
- **分块时把标题路径拼回正文**——「退课」那节里的「不收取任何费用」
  脱离标题就没有意义
- **标题在 BM25 里重复 3 次做加权**——标题里的「退课规则」这类词
  对检索贡献极大，只在正文出现一次会被长正文稀释

`scripts/eval_rag.py` 是评测脚本，改分块参数后直接重跑看数字。

### 4. 假模型 —— 把"链路"和"推理"解耦

没有 API Key 时，如果只能等有 Key 才能测试，那么 MCP 连没连上、
工具绑定成功没有、ReAct 能不能跑、SSE 对不对、审批中断能不能恢复
—— 全都无法验证。

`ScriptedChatModel` 按规则产出 `tool_calls`，把上面每一项都变成可复现的实证。

**它不能验证什么**（这点必须说清楚）：
- 模型会不会**选错工具**（规则驱动，不是理解）
- 越界任务下会不会**幻觉**（拒绝话术是写死的）

所以接上真实模型后，**必须重跑 `scripts/check_chain.py`**。

---

## 六、接入真实模型

改 `backend/.env` 即可，代码一行不用动：

```ini
# DeepSeek
LLM_PROVIDER=deepseek
LLM_API_KEY=sk-xxxxx

# 智谱 GLM
LLM_PROVIDER=zhipu
LLM_API_KEY=xxxxx.xxxxx

# 任意 OpenAI 兼容端点（Ollama、通义、vLLM…）
LLM_PROVIDER=openai_compatible
LLM_API_KEY=xxx
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_MODEL=qwen2.5:7b
```

RAG 的向量化也可以换：

```ini
EMBEDDING_BACKEND=openai_compatible
EMBEDDING_MODEL=embedding-3
```

改完记得重建索引：菜单选 `4`。

---

## 七、验证结果（这是本项目的验收凭证）

### 链路自检：32 项全部通过

```
菜单选 5，或 python scripts/check_chain.py
```

| 分组 | 检查项 |
|---|---|
| 业务 REST 与 JWT | 登录、无票据 401、错误密码 401、课程检索、课表成绩、RAG 检索 |
| MCP 与工具 | 连接与工具发现、审批策略覆盖、**工具描述均非空**、**参数无身份字段** |
| 身份防越权 | 两个用户各自身份独立、Agent 会话不串号 |
| ReAct 与 SSE | 事件序列、工具自主调用、155 个分片流式推送、回答有据可依 |
| 审批·拒绝 | 触发中断、**拒绝后业务表条数不变**、模型有解释 |
| 审批·批准 | 触发中断、**批准后业务表 +1**、测试数据已还原 |
| 越界任务 | 改成绩/重置密码/缓修/代考 —— **均不幻觉、不硬凑工具** |
| 文本质量 | 消息内容未被 Python repr 污染（防止内容块列表直接喂给界面） |
| 审计 | AI 操作进审计、台账含被拒绝记录 |

### P0 加固回归测试

```
cd backend
python -m unittest discover -s tests -v
```

12 项不依赖 LangChain / MCP 的本地测试：

| 测试 | 证明什么 |
|---|---|
| `thread_key` 命名空间 | 不同用户拿到同一个原始 id 也不会撞 key，回传完整 id 保持幂等 |
| 并发选课 | 8 个用户抢 1 个座位，只成功 1 人，`enrolled_count` 与记录数一致 |
| 同人并发 | 同一用户并发选同一门课，只落 1 条记录、只占 1 个座位 |
| 同人并发不同课程 | 时间相同、各 20 学分的两门课只能成功一门，不会同时绕过时间冲突和学分上限 |
| 计数校准 | 人为把 `enrolled_count` 改错，`sync_enrollment_counts` 能修复 |
| 启动 seed 不覆盖 | 已退课保持 dropped、已出成绩保持 completed/分数，不会被改回在读 |
| 审批状态识别 | 用 `StateSnapshot` 能识别待审批中断，且不会把 checkpoint 字典误判为会话 |
| 台账成功/失败 | 工具返回成功/业务拒绝分别落 SUCCESS / FAILED，并记录错误 |
| 同名工具混合决定 | 拒绝产生的 ToolMessage 不会吃掉同名批准行的结果 |
| 台账未执行 | 已批准但流结束前没收到工具结果，落 NOT_EXECUTED |

### RAG 检索质量

```
python scripts/eval_rag.py

Hit@1 : 15/18 = 83.3%
Hit@3 : 18/18 = 100.0%
Hit@4 : 18/18 = 100.0%
```

3 条未在 Top1 的查询，正确答案都在 Top3 内，而 RAG 是把 Top4 一起给模型，
所以对最终回答无影响。

---

## 八、项目结构

```
campus-agent/
├── scripts/
│   ├── run.ps1              # 一键启停菜单（UTF-8 with BOM）
│   ├── run.bat              # ASCII 入口（绕过 ExecutionPolicy）
│   ├── probe_apis.py        # API 探测脚本，动手前先跑这个
│   ├── build_index.py       # 构建知识库索引
│   ├── eval_rag.py          # 检索质量评测
│   ├── check_chain.py       # 端到端链路自检（32 项）
│   └── browser_verify.py    # 无头浏览器端到端验证 + 自动截图
│
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI 入口
│   │   ├── config.py        # 配置（MCP 服务复用同一份）
│   │   ├── models.py        # SQLAlchemy 模型
│   │   ├── services.py      # 业务规则（唯一真相源）
│   │   ├── security.py      # JWT 正式票据 + MCP 短票据
│   │   ├── seed.py          # 种子数据（32 门课 / 6 个用户）
│   │   ├── routers/         # auth / courses / enrollments / knowledge / audit / agent
│   │   ├── rag/             # loader / embeddings / bm25 / store
│   │   └── agent/
│   │       ├── llm.py              # 模型工厂（假模型 / 真实模型切换）
│   │       ├── scripted_model.py   # 脚本假模型
│   │       ├── policy.py           # 审批策略 + 覆盖性审计
│   │       ├── session.py          # thread_id 用户命名空间
│   │       ├── ledger.py           # 审批台账：中断入账 + 执行结果回填
│   │       └── runtime.py          # MCP 客户端 + create_agent + SSE
│   ├── kb/                  # 6 份规章制度文档
│   ├── tests/               # P0 加固回归测试（stdlib unittest）
│   └── data/                # SQLite + Chroma（运行时生成）
│
├── mcp_server/
│   ├── server.py            # FastMCP 入口
│   ├── tools.py             # 7 个工具（docstring 是模型选工具的唯一依据）
│   ├── business_client.py   # 票据透传 + 回调业务接口
│   └── _config.py           # 复用 backend 的 Settings，避免端口漂移
│
└── frontend/                # Vue3 + Vite（深色主题）
```

---

## 九、环境依赖

- Python 3.13（本项目在 3.13.14 上验证）
- Node.js 22
- Windows / PowerShell 5.1（启停脚本针对 Windows 写的）

### 安装依赖

```bash
python -m venv .venv
.venv/Scripts/pip install -r backend/requirements.txt
cd frontend && npm install
```

> **国内网络提示**：如果 pip 装不上包，多半是镜像源问题。
> 实测在代理环境下清华镜像不通而官方源正常，也可以换腾讯云镜像（实测 20 MB/s）：
> ```bash
> pip install -i https://mirrors.cloud.tencent.com/pypi/simple -r backend/requirements.txt
> ```

---

## 十、已知限制

诚实列出来，因为这些问题会在生产环境咬人：

| 限制 | 影响 | 生产做法 |
|---|---|---|
| `InMemorySaver` 做 checkpointer | 后端重启后，待审批的中断状态会丢 | 换 `langgraph-checkpoint-postgres` / SQLite 后端 |
| 手写 SQLite 轻量迁移（只加列） | 复杂 schema 变更仍需手工处理 | 引入 Alembic |
| 台账结果回填依赖 SSE `tool_result` | 客户端在工具执行后、结果返回前断开时，可能记成 `NOT_EXECUTED`（实际已执行） | 把结果落库放到工具端点或独立任务/消息队列 |
| `local` 哈希向量 | 只有词面检索能力，靠 BM25 补偿 | 接真实 embedding；届时把 RRF 权重调向向量侧 |
| 知识库 6 份文档 59 chunk | 规模小，检索评测集只有 18 条 | 扩到真实教务文档量级后重跑评测 |
| Agent 的 MCP 客户端每请求重建 | 每请求多一轮本地握手（毫秒级） | 若身份不需要隔离可用连接池；但那样会串号，不建议 |
| 假模型无法验证工具选择准确率 | 只能验证链路 | **接真模型后必须重跑 check_chain.py** |
| 前端未做移动端适配 | 窄屏体验一般 | 加响应式 |
| 无用户注册、无密码找回 | 只有内置演示账号 | 接统一身份认证 |
| 未做接口限流 | Agent 对话可被高频调用 | 加限流 + 单用户并发上限 |

---

## 十一、这套系统里"刻意没做"的能力

以下能力业务系统有或未来会有，但**有意不做成 MCP 工具**，因为让模型自动执行风险过高：

- 修改/录入成绩 —— 成绩是学籍凭证，改动必须走教务人工审核
- 重置密码、修改个人信息 —— 涉及账号安全
- 免修/缓修/缓考申请 —— 需上传证明材料，属于带附件的审批流
- 教师端排课、容量调整 —— 管理权限

这几个正好是评测 Agent 安全性的天然**越界用例**：
工具集里根本没有这个能力时，模型会不会硬凑一个不相干的工具、
会不会幻觉"已办理"。自检脚本第 7 组就是专门测这个的。

---

## 十二、开发记录：踩过的坑

写给后面改这个项目的人，省得重踩：

| # | 坑 | 正确做法 |
|---|---|---|
| 1 | `Context.get_http_headers()` 不存在（那是 mcp 2.x 才有的） | 用 `ctx.request_context.request.headers` |
| 2 | `create_react_agent` 已从 `langchain.agents` 移除 | 用 `create_agent`（注意 `tools` 是第 2 个位置参数） |
| 3 | `create_agent` 返回的是编译后的图，**没有 `.tools` 属性** | 想拿工具清单要从 MCP 客户端取，不是从 agent |
| 4 | 服务端 `transport="streamable-http"`（连字符）<br>客户端 `"transport": "streamable_http"`（下划线） | 写反了不报参数错误，只是连不上 |
| 5 | Chroma 1.5.9 自定义向量函数**必须实现 `embed_query`** | 纯自定义类不会继承 Protocol 的默认实现，会 AttributeError |
| 6 | Chroma 的 `embed_query` 收到的是**列表**不是单个字符串 | 按单字符串写会在 query 时崩 |
| 7 | Chroma 集合名不能以下划线开头 | 必须 3-512 字符且以字母数字开头结尾 |
| 8 | `MultiServerMCPClient(tool_name_prefix=True)` 会把工具名变成 `campus_xxx` | 判定写工具/匹配工具名前要先剥前缀 |
| 9 | **checkpointer 会带回整轮历史**，假模型因此误判"已有工具结果"而不再调工具 | 只看最后一条用户消息之后的 ToolMessage |
| 10 | 原生 `EventSource` 无法带 `Authorization` 头 | SSE 必须用 `fetch` + `ReadableStream` 手工解析帧 |
| 11 | `passlib 1.7.4` + `bcrypt 4.1+` 版本探测冲突 | 直接用 `bcrypt`，少一层脆弱封装 |
| 12 | BM25 用 min-max 归一化会把噪声文档顶到满分 | 按最大值归一化；更彻底的做法是直接用 RRF |
| 13 | `.ps1` 含中文但没 BOM → PS 5.1 按 GBK 解析，菜单全乱码 | 存为 UTF-8 with BOM |
| 14 | `.bat` 里写中文 → OEM 代码页乱码 | `.bat` 保持纯 ASCII，中文全放 `.ps1` |
| 15 | `??` 空合并运算符是 PS 7+ 语法，5.1 会报错 | 用 `if/else` 显式判断 |
| 16 | 停止服务只杀父进程会留残留占着端口<br>（uvicorn 有 reloader+worker，npm 会派生子进程） | 按**端口**找进程，`taskkill /PID $pid /T /F` |
| 17 | `taskkill` 关不掉 `cmd /k` 的**窗口壳**，每次停止留一排空窗口 | 记录 cmd PID 一并关，再按窗口标题前缀兜底 |
| 18 | 测试复用同一 `thread_id` 会被上轮历史污染 | 每次运行用唯一 thread 前缀 |
| 19 | 测试挑的课程可能因业务规则（先修课未过）被拒，看起来像 bug | 先预检出一门"这次一定选得上"的课；<br>**FAIL 先怀疑标注，再怀疑被测对象** |
| 20 | **工具节点返回的 `ToolMessage.content` 不是字符串，而是内容块列表**<br>`[{'type': 'text', 'text': '...', 'id': 'lc_...'}]` | 直接 `str()` 会把 Python repr 显示给用户。必须归一化后再用。<br>⚠️ **这个 bug 在 HTTP 层自检里查不出来** —— repr 里同样含有关键词，<br>"回答里有没有学分"这类断言照样通过。只有把界面渲染出来看才会发现。<br>而且**直接构造消息看类型也测不出来**（构造时是 str，流经图之后才变列表） |
| 21 | `HumanInTheLoopMiddleware` 的审批说明默认是英文 | 传 `description_prefix="此操作需要修改你的数据，需要你确认"` 覆盖 |
| 22 | 滚动容器没有自己的层叠上下文 | 对话区滚动时最早的内容会盖到顶部状态条上，出现叠字。<br>状态条加 `position: relative; z-index: 2`，滚动区 `z-index: 1` |

---

## 十三、动手前先跑探测脚本

`scripts/probe_apis.py` 会把 MCP / LangChain / Chroma 的**真实**签名打出来。

这不是可选项。MCP 和 LangChain 生态迭代极快，教程里的 import 路径、
参数名、transport 取值经常已经失效。上面 19 个坑里有 6 个是靠它提前发现的，
省掉的是照着过时教程写完再调试的时间。
