# Langflow 与 MyFlow 后端源码学习笔记

记录日期：2026-10-30。

学习范围是 Python 后端，重点理解节点定义、图校验、异步调度、事件流、持久化和模型适配。以 MyFlow 为较小的阅读入口，再对照 Langflow 的组件和执行框架。

## 主要区别

MyFlow 的现有范围以 [SPEC.md](../SPEC.md) 为准。Langflow 的定位见[项目介绍](https://github.com/langflow-ai/langflow)，技术栈和模块划分见[源码说明](https://github.com/langflow-ai/langflow/blob/main/AGENTS.md)。

| 方面 | 当前 MyFlow | Langflow |
| --- | --- | --- |
| 主要用途 | 串联文本、图片、语音、音乐、视频和识别能力 | 搭建 Agent、知识库问答、工具调用等通用 AI 应用 |
| 后端结构 | FastAPI、asyncio、SQLAlchemy，使用 SQLite 和本地文件；主要分为 API、engine、nodes、providers | FastAPI 应用层、服务层、LFX 执行基础能力和独立供应商组件包 |
| 节点传值 | 连线表示节点依赖，通过 `{{节点ID.output}}`、`{{节点ID.url}}` 等变量取值 | 连线接到具体的、有类型的输入和输出端口 |
| 扩展节点 | 节点类型、配置元数据和执行器分别在代码中注册 | 通过 `Component` 子类声明输入、输出和执行方法，由组件框架加载 |
| 流程控制 | 运行图必须无环；每次运行最多并发 4 个节点；节点失败会取消同次运行的其他任务 | 提供条件路由、循环、子流程等组件，组合方式受各组件规则约束 |
| 对外使用 | 单机单用户，通过 POST JSON 业务 API 管理工作流和运行，通过 SSE 返回运行事件 | 支持认证、工作流 API，以及把流程作为 MCP 工具供其他应用调用 |

Langflow 的端口和组件扩展机制见[自定义组件文档](https://docs.langflow.org/components-custom-components)；流程控制见 [Loop 文档](https://docs.langflow.org/loop)，其中也说明了 Loop 与 If-Else 的组合限制；对外工具调用见 [MCP 服务文档](https://docs.langflow.org/mcp-server)。

## 重点理解节点抽象

MyFlow 将节点配置元数据保存在 [registry.py](../backend/app/nodes/registry.py)，节点类型定义在 [schemas.py](../backend/app/schemas.py)，执行逻辑通过 [runners.py](../backend/app/nodes/runners.py) 中的 `RUNNERS` 映射查找。新增节点通常要同时调整这些位置及相关校验和测试。

Langflow 将输入字段、端口类型、输出方法和组件加载组织成统一体系。阅读时重点比较：增加一个简单节点需要改哪些地方，节点配置如何转成运行参数，连接类型如何校验，运行时如何找到对应方法。

例如，MyFlow 中先连接上游文本节点，再在下游模板填写 `{{text_1.output}}`；Langflow 则可以把上游输出端口接到兼容的下游输入端口。两者都传递数据，但表达依赖和字段绑定的方式不同。

对应 MyFlow 契约：GRAPH-001、REF-001、INPUT-001、OUTPUT-001。

## 重点理解执行与分层

MyFlow 的运行链路较集中，适合跟踪一次完整执行：

1. [schemas.py](../backend/app/schemas.py) 定义请求、节点、连线和图的数据结构。
2. [main.py](../backend/app/main.py) 的运行接口接收请求，调用 [graph.py](../backend/app/engine/graph.py) 校验图与输入，再保存运行记录及快照。
3. [executor.py](../backend/app/engine/executor.py) 调度就绪节点，通过 `RUNNERS` 调用节点逻辑，并处理失败、取消和终态。
4. [models.py](../backend/app/models.py) 保存工作流、运行和事件，`emit` 将运行事件写入数据库。
5. [main.py](../backend/app/main.py) 的事件接口按游标返回 SSE，供调用方消费和断线重连。

Langflow 将应用 API 与服务、执行基础能力、供应商组件拆成不同包。先读[架构说明](https://github.com/langflow-ai/langflow/blob/main/docs/agents/ARCHITECTURE.md)，再沿调用链追踪；重点观察执行层如何通过接口使用应用服务，以及供应商组件如何加载。

对应 MyFlow 契约：API-001、SAVE-001、RUN-001 至 RUN-003、HISTORY-001、SSE-001 至 SSE-002。

## 后端源码阅读顺序

| 顺序 | MyFlow 源码入口 | 要回答的问题 |
| --- | --- | --- |
| 1 | [schemas.py](../backend/app/schemas.py)、[graph.py](../backend/app/engine/graph.py) | 图如何表示？怎样拒绝环、悬空连接和非法变量？ |
| 2 | [registry.py](../backend/app/nodes/registry.py)、[runners.py](../backend/app/nodes/runners.py) | 节点配置和执行逻辑如何对应？节点怎样读取上游、返回结果？ |
| 3 | [executor.py](../backend/app/engine/executor.py) | 节点什么时候就绪？如何并发执行、限制并发、传播失败和取消任务？ |
| 4 | [models.py](../backend/app/models.py)、[main.py](../backend/app/main.py) | 如何保存运行快照与事件？SSE 如何按游标重连？服务重启后如何处理运行状态？ |
| 5 | [client.py](../backend/app/providers/client.py)、[minimax.py](../backend/app/providers/minimax.py)、[media.py](../backend/app/nodes/media.py) | 如何隔离供应商差异、汇总流式输出、查询视频任务并保留任务 ID？ |

先用纯文本和模板节点跟踪一次完整运行，再用假执行器观察两个独立分支的执行顺序。读到调度时，重点理解 `asyncio.create_task`、`asyncio.wait`、`Semaphore` 与任务取消的配合。

配套阅读 [test_text_workflows.py](../backend/tests/test_text_workflows.py)、[test_contracts.py](../backend/tests/test_contracts.py) 和 [test_workflows.py](../backend/tests/test_workflows.py)。先从成功结果、失败状态及副作用断言理解契约，再回到实现定位原因。

## 对照 Langflow 后端

按照[架构说明](https://github.com/langflow-ai/langflow/blob/main/docs/agents/ARCHITECTURE.md)定位以下目录，沿一个组件的输入、执行和输出追踪调用链：

- `src/lfx/src/lfx/`：组件基础类、执行基础能力及内置组件。
- `src/backend/base/langflow/api/`：FastAPI 接口与请求处理。
- `src/backend/base/langflow/services/`：数据库、认证、缓存等应用服务。
- `src/bundles/`：独立供应商组件和集成。

重点比较两种设计：MyFlow 的节点注册表和执行器映射，与 Langflow 的 `Component` 扩展机制；MyFlow 集中的运行链路，与 Langflow 执行层通过接口使用应用服务的分层方式。

阶段练习可以依次做“文本 → 模板拼接”、独立分支并发、节点失败取消其他任务、事件游标重连。掌握这些机制后，再研究 Langflow 的 Agent、流程控制和 MCP 服务。

练习仅使用演示模型、固定假输出和 mock 供应商，遵守 [AGENTS.md](../AGENTS.md) 的测试约束。以上是学习练习，不改变 MyFlow 当前的产品范围。

IDE 可继续使用 VS Code，配合 Python、Pylance 和 Python Debugger；相关配置见 [Python 官方使用说明](https://code.visualstudio.com/docs/languages/python/)。选择项目的 Python 解释器，在测试中打断点，观察节点输入、上下文、任务状态和数据库记录。
