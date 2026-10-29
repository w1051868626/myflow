# MyFlow 行为规范与验收契约

状态：当前项目基线，2026-10-29。约束后续代码生成、修复和重构。

本规范中的“必须”是验收要求。新增需求应先写明可观察行为、失败分支和范围；在获得实现和测试授权后，再补充会失败的测试并实现。不得仅因当前实现如此就把缺陷写成标准。需求改变时，说明变更理由并同步修改规范、测试和实现。撰写或修改本规范本身不构成修改业务代码、编写测试或执行测试的授权。

## 产品范围

单机、单用户的可视化 AI 工作流平台：编辑并保存节点图，连接文本、图片、语音、音乐、视频及识别能力，执行后查看流式输出和历史记录。另提供 MiniMax 模型试验台。支持九类节点：start、llm、image、speech、music、video、asr、template、end。

当前不承诺：多用户鉴权、分布式调度、多个 Uvicorn worker、条件分支、版本回滚、失败续跑、供应商模型始终可用或临时媒体链接永久有效。增加这些能力需要单独需求，不能隐含在本次改动中。

## 可执行契约

表中测试函数位于 `backend/tests/`，前端条目例外注明。测试文件中的参数化用例属于同一契约的多个场景。验收以行为和可观察结果为准，不检查实现文本或私有函数名称。

| 编号 | 必须满足的行为 | 自动化证据 |
| --- | --- | --- |
| API-001 | `/api/` 业务路由只使用 POST，ID 在 JSON 请求体中，路由不含 ID 占位符；文档和资源仍可 GET。健康检查返回 `{"status":"ok"}`。 | `test_workflows.py::test_post_api_contract_and_get_documentation` |
| API-002 | 创建返回 201；读取及列表包含工作流；删除返回 204 和空响应体，随后读取返回 404。 | `test_workflows.py::test_workflow_list_and_delete_payload`；前端 `events.test.mjs` 的共享客户端用例 |
| SAVE-001 | 保存成功版本递增；携带旧版本保存返回 409，已保存的名称、节点和位置不能被覆盖。 | `test_contracts.py::test_save_001_stale_write_cannot_overwrite_saved_graph` |
| GRAPH-001 | 允许保存不完整草稿；运行时必须拒绝无效图且不创建运行记录。有效图恰有一个开始与输出节点，所有节点均在开始至输出的路径上；禁止重复节点、重复连线、自环、环、悬空引用及方向错误。 | `test_contracts.py::test_graph_001_incomplete_draft_is_saved_but_cannot_run`；`test_workflows.py::test_rejects_invalid_graphs`；下方图校验补充用例 |
| GRAPH-002 | 单图最多 100 个节点、500 条边；超过限制返回 422。 | `test_contracts.py::test_graph_002_graph_size_limits` |
| INPUT-001 | 开始节点字段唯一且合法；运行输入必须精确匹配字段，值不能空白；非法请求返回 422 且不产生运行记录。 | `test_contracts.py::test_input_001_rejected_inputs_create_no_run`；`test_workflows.py::test_rejects_invalid_graphs` |
| REF-001 | 变量只能引用已连接的上游；开始节点可引用声明字段及 output，文本/识别/模板用 output，媒体用 url；未知字段及不完整变量语法失败，禁止默默替换为空。 | `test_workflows.py::test_rejects_invalid_graphs`、`test_template_missing_variable_is_error`；`test_media_nodes.py::test_invalid_media_types_and_references_are_rejected` |
| RUN-001 | 依赖完成即允许调度，不等待无关分支；单次运行节点并发上限为 4，独立分支能够并行；成功运行只有一个终结事件。 | `test_contracts.py::test_run_001_independent_nodes_run_concurrently_with_limit_four`；`test_workflows.py::test_ready_queue_does_not_wait_for_unrelated_branch` |
| RUN-002 | 节点失败导致运行 failed，取消同次运行中的其他任务；下游输出不得继续执行，并记录跳过节点。未知模型不可伪装成功。 | `test_workflows.py::test_failure_cancels_sibling_and_skips_end`、`test_failing_model_ends_run` |
| RUN-003 | 取消运行最终为 cancelled；重启后原 running 记录为 interrupted，并追加对应终结事件。 | `test_workflows.py::test_cancel_running_task`、`test_restart_marks_unfinished_run_interrupted` |
| HISTORY-001 | 历史保存运行时图、版本、输入、输出及事件；后续编辑不得改变历史详情或重放。 | `test_contracts.py::test_history_001_graph_version_inputs_and_outputs_survive_later_edits` |
| HISTORY-002 | 运行列表仅返回指定工作流最近 50 条，按创建时间从新到旧。 | `test_contracts.py::test_history_002_only_latest_fifty_runs_are_returned` |
| SSE-001 | POST 事件流按事件 ID 递增，after 仅返回更大的 ID；终结事件结束流。非法游标 422，不存在运行 404。 | `test_workflows.py::test_demo_end_to_end_history_and_reconnect`、`test_event_payload_validation`、`test_event_run_not_found`；下方游标补充用例 |
| SSE-002 | 前端正确解码跨字节 UTF-8、CRLF、多行 data、心跳；断线携带最后 after 重连；run_finished / stream_closed 停止重连；关闭订阅中止在途请求。 | `frontend/src/api/events.test.mjs` |
| CANVAS-001 | 拖动及流式结果更新保留节点尺寸与拖动位置；保存仅持久化图配置和坐标；历史图切换正确同步节点增删与位置。 | `frontend/src/canvas/state.test.mjs` |
| PROVIDER-001 | DeepSeek、MiniMax 连接独立存储，密钥加密落盘，读取和保存响应不返回密钥；空密钥保留已有值；未知供应商及非 HTTP(S) Base URL 拒绝。 | `test_workflows.py::test_provider_connections_are_independent_and_keys_stay_private`、`test_required_inputs_and_provider_key` |
| PROVIDER-002 | 新预置和节点默认文本为 deepseek-flash、图片为 image-01；演示工作流无需真实密钥即可完成，产生文本及可读本地 SVG。 | `test_workflows.py::test_new_workflows_and_node_defaults_use_requested_models`、`test_demo_end_to_end_history_and_reconnect` |
| PROVIDER-003 | DeepSeek 请求为流式并汇总 token 用量；MiniMax 图片尺寸正确、Base64 保存为本地资源；业务错误码及空图片结果导致失败。 | `test_workflows.py::test_deepseek_stream_adapter`、`test_minimax_adapter_persists_generated_image`、`test_minimax_business_errors_do_not_look_like_success` |
| LAB-001 | 试验目录每个模型路由到对应 API；单次试验只提交一次生成；非法模型/参数不调用上游；上游错误隐藏当前密钥；文本专用连接未配置时可复用 MiniMax 连接。 | `test_minimax.py::test_every_catalog_model_is_routed_to_its_api`、`test_invalid_trials_do_not_call_upstream`、`test_upstream_business_error_redacts_secret`、`test_minimax_text_can_fall_back_to_multimodal_key` |
| MEDIA-001 | 上传仅接受支持的音频/图片扩展名及合法 Base64，解码后大小为 1 字节至 20 MiB；返回资源可读取；非法上传不得产生文件。这里验收扩展名和字节数，不宣称验证媒体编码内容。 | `test_contracts.py::test_media_001_invalid_upload_creates_no_artifact`、`test_media_001_upload_limit_is_on_decoded_bytes`；`test_media_nodes.py::test_uploaded_audio_is_persistent_input_to_asr` |
| MEDIA-002 | ASR 只读取本地音频；拒绝外部地址、越界路径、子目录、反斜杠路径和缺失文件。上传音频及上游音频均能作为 ASR 输入。 | `test_contracts.py::test_media_002_asr_local_resource_boundary`；`test_media_nodes.py::test_speech_to_asr_to_template_runs_in_order` |
| MEDIA-003 | 语音→识别→模板、音乐→翻唱→识别可执行；图片→视频将本地图片转换为 Data URL，媒体连接遵守类型约束。 | `test_media_nodes.py::test_speech_to_asr_to_template_runs_in_order`、`test_music_can_feed_asr_and_cover_uses_local_audio`、`test_image_to_h3_video_waits_and_passes_image_as_data_url`、`test_invalid_media_types_and_references_are_rejected` |
| VIDEO-001 | 视频只提交一次生成任务，后续轮询已有任务；进度保留 task_id / api_version。连续查询错误、等待超时及取消终止本地轮询；失败提示保留任务 ID，禁止自动重新生成。 | `test_media_nodes.py::test_video_poll_failure_preserves_task_id_without_resubmitting`、`test_video_timeout_bounds_a_hanging_query_and_cancellation_stops_polling`、`test_image_to_h3_video_waits_and_passes_image_as_data_url`；`test_minimax.py` 的 v1/v2 查询用例 |

## 验收入口

本节记录可用的验收方式；是否编写或执行测试以用户授权为准。仅要求输出或修改规范时，不执行这些命令。

图校验补充用例为 `test_contracts.py::test_graph_001_invalid_draft_never_creates_a_run`，验证重复连线、自环、悬空端点、开始/输出方向、开始/输出数量、孤立节点及重复字段；游标补充用例为 `test_contracts.py::test_sse_001_cursor_is_exclusive_and_terminal_cursor_closes_stream`。

试验台单次生成补充用例为 `test_contracts.py::test_lab_001_one_trial_never_retries_generation`，同时验证成功和供应商业务失败时均不重试生成。`test_acceptance_default_http_transport_is_blocked` 验证同步和异步 HTTPX 默认传输都被测试夹具阻断。

安装 README 中的 Python 和前端依赖后，从项目根目录执行：

```powershell
python scripts/verify.py
# 当前终端无 Python 时，用已有项目解释器启动：
.\backend\.venv\Scripts\python.exe scripts/verify.py
# 也可以显式指定用于后端验收的解释器：
python scripts/verify.py --python C:/path/to/python.exe
```

脚本依次运行完整 pytest、前端测试、TypeScript 检查和生产构建；任一步失败返回非零，不能把局部通过写成验收通过。脚本自动优先使用项目 `.conda`，其次 `backend/.venv`，最后使用启动脚本的 Python。前端通过 Node 24 的 `--run` 执行已有 package scripts，依赖安装仍按 pnpm 锁文件进行。

后端测试使用独立临时数据库、文件目录和测试密钥；HTTPX 默认真实传输被测试夹具阻止，供应商测试使用 MockTransport。统一验收不执行 `check_minimax_models.py` 或 `check_media_workflow.py`。付费实测需要用户明确要求，测试通过不能证明供应商账户权限、余额或当前模型开放情况。

## 人工验收与覆盖边界

以下是人工验收要求，目前未接入浏览器自动化，不能凭单元测试或构建通过宣称已完成：

1. 打开首页，添加并拖动节点、连线、编辑配置、删除节点与边；保存刷新后名称、参数和位置正确。
2. 运行演示工作流，查看节点状态、流式文本、资源预览；打开历史后看到对应图和结果，再返回编辑。
3. 设置页分别保存两家连接；空密钥保存保留原配置，页面不显示已存密钥。
4. 在 `/models` 选择不同能力，示例 payload 随模型更新；上传与媒体预览可用，错误可见。此项无需点击真实生成按钮。
5. 视频节点切换模型后默认时长和分辨率跟随模型调整；已有任务可转到试验台继续查询。

当前自动化不覆盖视觉布局、拖拽手势、浏览器端完整操作链、容器启动及供应商在线可用性。新增关键浏览器交互时应补充相应浏览器验收；未执行的项目必须明确标注。

## 代码格式与函数设计规范

以下要求约束后续新增代码及本次实际修改的逻辑，不要求为满足指标批量重构历史代码。阈值为项目约定；本次仅记录规范，不安装检查工具、不编写或运行测试，也不宣称现有代码已满足这些要求。

### CODE-001：格式与命名

- 优先遵循仓库现有格式配置；无配置时沿用所在文件的缩进、引号和分号习惯。Python 使用四空格缩进。
- Python 函数和变量使用 `snake_case`；TypeScript 函数和变量使用 `camelCase`；类、组件和类型使用 `PascalCase`；常量按语言惯例命名。
- 无既有行宽配置时，代码行默认不超过 120 字符；无法合理拆分的 URL、字符串及生成内容除外。
- 仅整理本次修改涉及的代码，避免无关文件格式化和整文件重排。
- 不遗留无用导入、无用变量、注释掉的旧代码和临时调试输出。注释说明原因、限制和特殊处理。
- 不擅自引入或更换 formatter、linter，不通过禁用规则掩盖问题。

### CODE-002：函数入参

- 新增或修改的函数必须有明确的参数类型。Python 使用类型注解；TypeScript 的函数边界使用明确类型，不以 `any` 代替业务模型。
- 每个参数应有清晰含义；涉及单位、有效范围、空值、默认值或格式时，通过类型、命名或文档说明。例如区分 `timeoutSeconds` 与 `elapsedMs`。
- 必选参数、可选参数和默认值应明确区分；禁止使用可变对象作为 Python 默认参数。
- 默认最多五个显式参数，不计 `self`、`cls`。超过时优先审查职责，或将语义相关参数组成有类型的配置对象；不得仅为减少参数数量塞入无约束字典。
- 多个含义不直观的布尔参数应改为有名称的选项或枚举；Python 优先使用关键字参数，TypeScript 优先使用命名字段。
- 不默认修改调用者传入的对象、数组或集合。确需原地修改时，在函数契约中明确说明。
- 在 API、文件、配置和供应商响应等外部输入边界校验数据；可信内部调用避免无意义地重复校验。

### CODE-003：函数出参与错误

- 新增或修改的函数必须有明确返回类型；无返回值使用 Python `-> None` 或 TypeScript `void`，异步函数明确最终结果类型。
- 同一操作的成功结果应保持稳定结构；多种合法结果使用明确的联合类型，必要时提供状态判别字段，禁止调用者猜测返回形状。
- 返回多个业务字段时优先使用命名结构，如 dataclass、Pydantic 模型、TypedDict 或 TypeScript 类型；默认不返回超过三个元素的位置元组。
- 明确空结果、未找到和失败的区别。不得用空字符串、空集合或 `None` 掩盖异常；合法的缺失值必须在返回类型和契约中说明。
- 错误处理遵循现有调用边界约定，使用明确异常或有类型的错误结果，不混用无法判别的成功/失败值。
- 不吞掉异常、不将失败包装为成功；错误信息不得泄露密钥。资源分配、文件写入、网络调用及其他副作用应说明。

### CODE-004：复杂度与规模

| 指标 | 默认约束 | 超出时的处理 |
| --- | --- | --- |
| 显式参数数量 | 每个函数不超过 5 个，不计 `self`、`cls` | 审查职责并组织相关参数；框架固定签名单独说明 |
| 圈复杂度 | 每个函数不超过 10 | 简化分支或按业务职责拆分，不通过禁用规则绕过 |
| 控制流嵌套深度 | 每个函数最多 3 层 | 使用提前返回、卫语句或职责清晰的辅助函数 |
| 函数体有效行数 | 每个函数不超过 80 行，排除空行、纯注释和 docstring | 按职责拆分，避免机械切成无意义的小函数 |

圈复杂度衡量函数独立执行路径数量，以确定采用的分析工具及其规则为准；没有实际测量时，不宣称指标已通过。嵌套深度只计函数体内的条件、循环、异常处理及上下文管理等控制结构，不计模块、类和函数定义；相邻的 `elif`、`else`、`except` 按同一结构层级计算。

- 函数应承担一个清晰职责；避免同时混合参数解析、业务决策、供应商调用和响应展示。
- 优先减少嵌套和重复条件；不为了降低单个函数的指标，把复杂度转移到难以理解的表达式、递归或大量零散函数中。
- UI 组件中的业务计算和副作用应与展示结构合理分离；JSX 标签层级不计入控制流嵌套深度。
- 生成文件、声明文件及纯静态数据不适用函数规模限制；框架固定接口、兼容接口及其他必要例外应逐项记录原因、影响和适用范围，不设笼统豁免。

### CODE-005：可维护性与验收说明

- 不随意使用 `any`、非空断言、`@ts-ignore`、`noqa` 或宽泛异常捕获；必要用法必须能说明具体原因。
- 命名常量替代难以理解的业务数值；不要为一次简单使用引入无必要的抽象或依赖。
- 修改已有函数时，不使原已超标的参数数量、圈复杂度、嵌套深度或函数行数进一步恶化。无法在任务范围内处理的历史问题如实记录，不借机扩大改动。
- 交付说明涉及的函数契约、格式或结构变化，以及必要例外。只有实际执行了相应检查，才能报告格式、类型或复杂度检查通过。
- 本节是代码交付规范，当前未配置对应的自动化静态检查；如需接入工具或 CI，另按用户授权实施。

## 对后续产出的限制

- 每次改动说明对应的契约编号或新增需求，不擅自增加产品功能、收费调用、依赖升级或无关重构。
- 新行为先补规范；在用户授权实现和测试后，再补充能够揭示问题的测试并实现，回归修复先证明新增测试在修复前失败。
- 不删除、跳过测试，不放宽断言或降低阈值来掩盖失败；需求确有变化时说明旧行为、新行为和理由。
- 不以快照更新、实现字符串比对、仅检查 mock 被调用代替结果断言；失败分支应验证状态和副作用。
- 保留已有工作区改动；交付说明实际修改、执行的检查、结果和未覆盖范围。没有运行证据不得宣称通过。
