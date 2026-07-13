
# iwork（车间工效看板）应用数据结构汇总

代码仓库: `D:\DM\iwork`
主应用目录: `D:\DM\iwork\iwork\`
技术栈: Django 5.2 + Celery + Redis + MySQL + Uvicorn ASGI

## 一、目录结构（关键文件清单）

```
D:\DM\iwork\iwork\
├── models.py              # 远程数据库模型 (只读)
├── local_models.py        # 本地数据库模型 (可读写)
├── views.py               # 页面视图 (看板主页面、生产详情、产量看板)
├── api_views.py           # REST API 视图 (实时数据、SSE推送、目标设置、产量看板API)
├── api_views_local.py     # 历史数据 API 视图 (本地/远程查询、同步)
├── api_urls.py            # 备用 URL 路由 (未在主 urls.py 中使用)
├── history_urls.py        # 历史数据 API URL 路由
├── urls.py                # 主 URL 路由
├── queries.py             # 远程数据库查询函数
├── local_queries.py       # 本地数据库查询函数
├── statistics.py          # 统计引擎 (并行查询、Redis缓存、批处理)
├── sync.py                # 数据同步模块 (远程→本地)
├── tasks.py               # Celery 定时任务
├── database_router.py     # 多数据库路由器
├── middleware.py          # IP 校验中间件 (TrustedProxyMiddleware)
├── apps.py                # Django AppConfig
├── settings.py            # 项目配置
├── celery.py              # Celery 配置
└── migrations/            # 数据库迁移
    ├── 0001_target_production.py
    ├── 0002_add_workorder_to_targetproduction.py
    └── 0003_productionorder.py
```

> 注意：iwork 应用无 `admin.py`（无 Django Admin 注册）、无 `serializers.py`（使用 @api_view 装饰器直接返回 dict，不经过 DRF Serializer）。

## 二、数据库架构（三库分离）

应用使用3个独立数据库，通过 DatabaseRouter 自动路由：

| 数据库别名  | 用途                                                                               |
| ----------- | ---------------------------------------------------------------------------------- |
| default     | Django 系统表（auth, sessions 等）                                                 |
| iwork       | 远程生产数据库 (iwork_system) — 表 pytckreg3                                      |
| iwork_local | 本地业务数据库 (iwork_local) — 表 pytckreg3, target_production, production_orders |

### 路由器规则（database_router.py）

1. Pytckreg3 → 读 iwork，禁止写入（只读）
2. LocalPytckreg3 / TargetProduction / ProductionOrder → 读写 iwork_local
3. 其他模型 → 读写 default

## 三、模型定义

### 3.1 Pytckreg3 — 远程生产打卡记录（只读）

- 文件: `D:\DM\iwork\iwork\models.py`
- 数据库: `iwork_system.pytckreg3`（远程，managed=False）
- 用途：映射 payroll 系统的生产流水线打卡记录

| 字段名      | 类型          | 约束                  |
| ----------- | ------------- | --------------------- |
| TicketNo    | CharField(13) | PK                    |
| SeqNo       | IntegerField  | default=0             |
| WrkOrder    | CharField(14) | blank, default=''     |
| BundleNo    | IntegerField  | default=0             |
| StepNo      | IntegerField  | default=0             |
| Qty         | IntegerField  | default=0             |
| RegPerSysID | IntegerField  | default=0             |
| RegDate     | DateTimeField | null=True, blank=True |
| RegTime     | DateTimeField | null=True, blank=True |
| RFID        | CharField(10) | blank, default=''     |
| Flow        | CharField(40) | blank, default=''     |
| PO          | CharField(40) | blank, default=''     |
| TimeCost    | IntegerField  | default=0             |
| SysSource   | CharField(3)  | default=''            |
| AccBundleNo | IntegerField  | default=0             |
| MtrType     | CharField(14) | blank, default=''     |
| Color       | CharField(35) | blank, default=''     |
| Sizx        | CharField(16) | blank, default=''     |
| SerialNum   | CharField(10) | blank, default=''     |
| StationID   | CharField(3)  | blank, default=''     |

属性方法：`full_datetime` — 将 RegDate + RegTime 合并为完整 datetime。

### 3.2 LocalPytckreg3 — 本地打卡记录（可读写）

- 文件: `D:\DM\iwork\iwork\local_models.py`
- 数据库: `iwork_local.pytckreg3`（本地，managed=False）
- 用途：从远程同步过来的数据副本，字段与 Pytckreg3 完全一致
- 字段：18个字段和远程表完全相同，仅归属数据库不同

### 3.3 TargetProduction — 目标产量（可读写）

- 文件: `D:\DM\iwork\iwork\local_models.py`
- 数据库: `iwork_local.target_production`（managed=True）
- 用途：存储员工每日目标产量，支持员工级总目标 + 工单级分目标

| 字段名      | 类型           | 约束              |
| ----------- | -------------- | ----------------- |
| id          | BigAutoField   | PK (自增)         |
| target_date | DateField      | —                |
| employee_id | CharField(50)  | —                |
| workorder   | CharField(100) | blank, default='' |
| target_qty  | IntegerField   | default=0         |
| created_at  | DateTimeField  | auto_now_add=True |
| updated_at  | DateTimeField  | auto_now=True     |

唯一约束：`(target_date, employee_id, workorder)` — 每个员工每天每个工单仅一条目标记录。

设计逻辑：

- `workorder=''` 代表员工总目标（兼容旧格式，由工单目标自动聚合）
- `workorder='WO-001'` 代表该工单的分目标

### 3.4 ProductionOrder — 生产工单信息（可读写）

- 文件: `D:\DM\iwork\iwork\local_models.py`
- 数据库: `iwork_local.production_orders`（managed=True）
- 用途：工单编号与产品款号映射表，数据源来自 `iwork/sqlite/production_orders.db`

| 字段名       | 类型           | 约束              |
| ------------ | -------------- | ----------------- |
| id           | BigAutoField   | PK (自增)         |
| order_no     | CharField(50)  | —                |
| order_dept   | CharField(50)  | blank, default='' |
| style_no     | CharField(50)  | blank, default='' |
| product_name | CharField(200) | blank, default='' |
| style_desc   | CharField(200) | blank, default='' |
| created_at   | DateTimeField  | auto_now_add=True |
| updated_at   | DateTimeField  | auto_now=True     |

索引：

- idx_po_order_no (order_no)
- idx_po_style_no (style_no)
- idx_po_order_dept (order_dept)

唯一约束 `idx_po_unique_record`: `(order_no, order_dept, style_no, product_name, style_desc)`

关联关系：通过 `Pytckreg3.WrkOrder[:6]` 前6位匹配 ProductionOrder.style_no，关联出 product_name 和 order_no。

## 四、模型关系简图

```
┌────────────────────────────┐      sync_date_data()       ┌────────────────────────────┐
│   Pytckreg3 (远程只读)     │ ───────────────────────> │  LocalPytckreg3 (本地)    │
│   iwork_system.pytckreg3   │   逐条对比+写入           │  iwork_local.pytckreg3    │
│   managed=False            │                           │  managed=False            │
└─────────────┬──────────────┘                           └────────────────────────────┘
              │ WrkOrder[:6]
              ▼
┌────────────────────────────┐     ┌────────────────────────────┐
│   ProductionOrder (本地)   │     │  TargetProduction (本地)  │
│   iwork_local.production_orders │  iwork_local.target_production │
│   managed=True            │     │  managed=True             │
│                           │     │                          │
│   style_no ←→ [:6]匹配    │     │  目标日期 + 员工ID + 工单 │
│   产品名称 + 款号信息     │     │  唯一约束                │
└────────────────────────────┘     └────────────────────────────┘
```

## 五、URL 路由与 API 汇总

### 5.1 页面路由 (urls.py — 前缀 /iwork/)

| URL                                               | 视图                           |
| ------------------------------------------------- | ------------------------------ |
| /                                                 | views.dashboard                |
| /history/                                         | views.history_dashboard        |
| /production/detail-data/                          | views.production_detail        |
| /production/detail-data/flow/<flow_name>/         | views.production_detail_flow   |
| /production/detail-data/stepno/<stepno></stepno>/ | views.production_detail_stepno |
| /kanban/                                          | views.kanban_page              |

### 5.2 实时数据 API (api_views)

| URL                                             | 请求方法 | 用途           |
| ----------------------------------------------- | -------- | -------------- |
| /api/dashboard/realtime/                        | GET      | 实时统计数据   |
| /api/dashboard/processes/                       | GET      | 可用工序列表   |
| /api/dashboard/hourly/                          | GET      | 每小时产量统计 |
| /api/dashboard/flow/<flow_name>/                | GET      | Flow 组详情    |
| /api/dashboard/workorders/                      | GET      | 工单列表(分页) |
| /api/dashboard/workorders/<wrk_order>/          | GET      | 工单详情       |
| /api/dashboard/monthly-trend/                   | GET      | 当月日产量趋势 |
| /api/dashboard/process-compare/                 | GET      | 工序×Flow对比 |
| /api/dashboard/heatmap/                         | GET      | 热力图矩阵     |
| /api/dashboard/station-ranking/                 | GET      | 工位产量排行   |
| /api/dashboard/stream/                          | GET      | SSE 实时推送流 |
| /api/dashboard/set-targets/                     | POST     | 设置目标产量   |
| /api/dashboard/detail/stepno-overview/          | GET      | 工序概览汇总   |
| /api/dashboard/detail/flows/                    | GET      | Flow 概览      |
| /api/dashboard/detail/flow/<flow_name>/         | GET      | Flow 员工明细  |
| /api/dashboard/detail/stepno/<stepno></stepno>/ | GET      | 工序员工明细   |
| /api/dashboard/detail/product-overview/         | GET      | 产品分组概览   |

### 5.3 产量看板 API (api_views)

| URL                         | 请求方法 | 用途         | 关键参数                                        |
| --------------------------- | -------- | ------------ | ----------------------------------------------- |
| /api/kanban/stats/          | GET      | 看板统计汇总 | ?date=&stepno=&wrk_order=&flow=&reg_per_sys_id= |
| /api/kanban/ranking/        | GET      | 看板排行榜   | ?date=&stepno=&...&page=&page_size=             |
| /api/kanban/filter-options/ | GET      | 级联筛选选项 | ?date=&stepno=&wrk_order=&flow=&reg_per_sys_id= |

### 5.4 历史数据 API (api_views_local，通过 history_urls.py include)

| URL                              | 请求方法 |
| -------------------------------- | -------- |
| /api/history/date/<target_date>/ | GET      |
| /api/history/dates/              | GET      |
| /api/history/sync/<target_date>/ | POST     |

## 六、查询层架构

iwork 未使用 DRF Serializer，分层查询直接将数据库结果转为 dict 返回：

| 层级       | 文件                        | 功能                               |
| ---------- | --------------------------- | ---------------------------------- |
| 模型层     | models.py / local_models.py | ORM 模型定义                       |
| 远程查询层 | queries.py (1121行)         | 远程库查询（单日/批量/看板）       |
| 本地查询层 | local_queries.py (954行)    | 本地库查询（镜像远程库的函数签名） |
| 统计引擎   | statistics.py (529行)       | 线程池并行查询、Redis 缓存、批处理 |
| 同步模块   | sync.py (146行)             | 远程→本地数据同步                 |
| 定时任务   | tasks.py (49行)             | Celery Beat 每60秒执行             |

### 查询函数分类

#### 单日查询 (queries.py / local_queries.py)

- get_basic_stats() — 工单数、总产量
- get_hourly_stats() — 按小时统计
- get_process_stats() — Top工序统计
- get_all_stepnos() — 全部工序号
- get_flow_stats() / get_flow_detail() — Flow 统计
- get_station_stats() — 工位统计
- get_workorders_list() / get_workorder_detail() — 工单列表/详情
- get_monthly_total_trend() — 月度趋势
- get_heatmap_data() — 热力图
- get_station_ranking() — 工位排行

#### 批量查询（batch 函数，单次SQL覆盖全部工序）

- get_batch_basic_stats() — 每个工序KPI
- get_batch_hourly_stats() — 每个工序小时趋势
- get_batch_process_by_flow() — 工序×Flow对比
- get_batch_flow_overview() — Flow概览
- get_batch_flow_employees() — Flow下员工明细
- get_batch_stepno_employees() — 工序下员工明细
- get_batch_product_overview() — 产品四层结构

#### 产量看板查询 (queries.py / local_queries.py)

- get_kanban_stats() — 工人数/总产量/人均/最高
- get_kanban_ranking() — 排行榜（分页）
- get_kanban_filter_options() — 级联筛选

## 七、关键业务配置（settings.py）

| 配置项               | 值                           |
| -------------------- | ---------------------------- |
| ALLOWED_FLOWS_STEPNO | 70                           |
| ALLOWED_FLOWS        | ['A', 'B', ...]              |
| HIDDEN_FLOWS         | [...]                        |
| VISIBLE_FLOWS        | ALLOWED_FLOWS - HIDDEN_FLOWS |
| QUERY_TIMEOUT        | 45s                          |
| MONTHLY_CACHE_TTL    | 30天                         |
| CELERY_BROKER_URL    | redis://iwork-redis:6379/1   |
| MIDDLEWARE[0]        | TrustedProxyMiddleware       |

## 八、数据流总览

```
┌─────────────┐    每秒打卡    ┌────────────────────┐      sync任务      ┌────────────────────┐
│  payroll系统 │ ───────────> │  Pytckreg3(远程只读)│ ──sync_date──> │ LocalPytck(本地副本)│
└─────────────┘                └──────────┬─────────┘                    └──────────┬─────────┘
                                          │                                   │
                                          ▼                                   ▼
                          ┌────────────────────┐                    ┌────────────────────┐
                          │  queries.py        │                    │ local_q.py         │
                          │  (并行查询)        │                    │  (镜像接口)        │
                          └──────────┬─────────┘                    └──────────┬─────────┘
                                     │                                   │
                                     ▼                                   ▼
                          ┌────────────────────┐                    ┌────────────────────┐
                          │statistics.py      │                    │ history模式        │
                          │ (Redis缓存)       │                    │ 实时查询           │
                          └──────────┬─────────┘                    └──────────┬─────────┘
                                     │                                   │
                    ┌────────────────┴───────────────────────────────────┘
                    │
                    ▼
        ┌─────────────────────────────────────────────────────────────────────┐
        │                        Redis 缓存（每60s更新）                     │
        └───────────┬──────────────────────┬─────────────────────┬───────────┘
                    │                      │                     │
                    ▼                      ▼                     ▼
        ┌───────────────┐      ┌───────────────┐      ┌────────────────────┐
        │ SSE推送(async)│      │ api_views(REST)│      │ api_views_local(历史)│
        └───────────────┘      └───────────────┘      └────────────────────┘
```

### 核心设计要点

1. **三层缓存策略**：Celery任务每60秒执行SQL → 写入Redis → 所有API从Redis读取（纯读，毫秒级响应）
2. **双数据库架构**：远程库只读（规避事故），本地库可读写（存储同步副本+业务自定义数据）
3. **并行查询**：使用 ThreadPoolExecutor(6线程) 单次SQL并行执行多查询维度
4. **SSE 实时推送**：异步协程，每15秒心跳保活，每60秒推送最新Redis数据
5. **历史数据隔离**：mode=local 参数切换本地库查询，支持历史回溯
