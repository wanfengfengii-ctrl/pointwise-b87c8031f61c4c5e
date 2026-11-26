# 社区版画工坊印务服务

编版员从纸规和印区定稿。印务员为定稿开连续编号批，并指定一台印机。机长按张完成正面、背面和实际吐纸。质检员按实物出纸号录入套印偏差，合格后前台按原批号领取编号册。

## 运行

需要 Python 3.11 标准库。在项目目录执行 `python3 -B check_project.py` 运行完整回归。`python3 -B -m samples.demo` 在临时目录启动印务台和两台本地仿真印机，通过 HTTP 完成 041 至 043 的印刷、质检和签出，打印实际领取清单。演示使用环回地址和临时端口。

分别启动服务时，可在当前目录执行以下命令。第一个命令的两个库文件应使用不同路径。每台印机使用自己的运行库和设备库。

```sh
python3 -B -m press.http --id A --db press-a.sqlite --device device-a.sqlite --port 8101
python3 -B -m desk.http --db desk.sqlite --template samples/festival.json --press A http://127.0.0.1:8101 --port 8100
```

## 印务台 HTTP

请求和响应使用 JSON 对象。可在 `samples/festival.json` 取用 `draft` 及号段。`template` 是当前本地模板，包含编号区、标记区和允许的套印偏差。启动不写配置文件。提交定稿时读取当前模板，旧定稿和原批一直用创建时的快照。

| 方法与路径 | 输入与结果 |
| --- | --- |
| `POST /editions` | `draft_id`、`paper`、`flip`、`front_art`、`back_art`。成功 201，含 `revision_id`、`fingerprint`、`proof` 及投影后的 `back_print`。 |
| `GET /editions/{id}` | 读取定稿及校样。 |
| `POST /batches` | `revision_id`、`start`、`count`。成功 201，返回 `batch_id` 与完整 `plan`。 |
| `GET /batches/{id}` | 开批快照、指定印机和已知的原运行号。 |
| `POST /batches/{id}/dispatch` | `press_id`、`request_id`。成功 200，返回 `batch_id`、`press_id`、`run_id`。派发请求号在印务台内使用。 |
| `GET /batches/{id}/progress` | 固定批、原印机和运行号，以及 `actual` 实吐列表和 `missing` 印号列表。未派发批的印机与运行号为空。已绑定待确认时只有印机号。 |
| `POST /batches/{id}/inspection` | `measurements` 数组，每项为 `ejection_id` 和 `deviation_mm`。成功 200，返回固定交付清单。以相同证据重复验收得到原清单。 |
| `GET /batches/{id}/delivery` | 按原批号领取第一次验收的清单，包含 `delivery_id`、`revision_id` 及原编号升序的纸张明细。 |

矩形字段为 `x,y,w,h`。纸规字段为 `width,height,margins`，边距按左、上、右、下排列。纸宽、高、矩形宽、高为正整数，坐标与边距为非负整数。翻边为 `long` 或 `short`。长边取长边所在方向为轴，正方形用纵轴作为长边。纵轴用 `width-x-w`，横轴用 `height-y-h`。完整矩形的四边都须在许可纸面内，允许贴边。印号可取 1 至 999999，单批 1 至 500 张，末号不得越界。所有数字均使用 JSON 整数。印号文本三位起补零。印机号和请求号最长 80 字符，使用字母、数字、点、下划线和连字符。

## 印机 HTTP

`POST /runs/{id}/advance` 输入 `request_id`。返回 `action_id`、`number`、`stage`、本次 `ejection_id` 及 `actual` 实吐快照。同一印机内请求号绑定到原运行。每次新推进选择可用印号中最靠前的一张，按 `front`、`back`、`ejected` 逐步执行。同张还有未确认动作时可推进别张。失答可按同一个请求号重投。`GET /runs/{id}` 回读这个运行的实吐事实。

印务台通过 `POST /queue` 传送 `batch_id`、目标 `press_id` 与 `plan`。这是本地服务之间的入队接口。原批及相同快照在同一台印机重投时返回原运行号。运行库和设备库是各自提交的 SQLite 库。设备在吐纸动作上记账，印机服务再保存本次推进结果。读进度、查原运行和领取都不调用设备执行入口。

## 错误与恢复

错误响应为 `{"error":"错误标识"}`。未知对象为 404。无效几何、号段和超差为 422。改机、请求身份冲突、无法推进和证据覆盖不齐为 409。领取的 `incomplete` 表示缺纸，`not_inspected` 表示实吐齐备等待质检。实际出纸号需要与测量一一对应，等量的外来出纸号不能替代原批实物。正负偏差的绝对值与原定稿公差比较，等额可以签出。传输失答或设备暂未完成可以返回 503，待恢复后使用原请求号继续。已签出时可直接领取，无需原机在线。
