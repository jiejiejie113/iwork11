# iwork Portal 集成 API 文档

## 概述

本文档为 Portal 系统和 AI Agent 提供 iwork API 接入指南。

## 基础信息

- **基础 URL**: `https://dktportal.dongming.local/iwork/`
- **认证方式**: Keycloak OIDC（所有 API 需要有效 Portal 登录会话）
- **数据格式**: JSON
- **字符编码**: UTF-8

## 认证说明

所有 API 请求需要有效的 Portal 登录会话（Keycloak OIDC）。认证流程：

```
用户登录 Portal → Keycloak 签发 OIDC session cookie
  → Nginx 通过 auth_request 验证 cookie
  → oauth2-proxy 注入 Remote-User header
  → iwork TrustedProxyMiddleware 校验来源 IP
  → API 返回数据
```

> 注意：API 不直接暴露在公网，仅通过 Portal Nginx 反向代理访问。所有 API 需要有效 Portal 登录会话（Keycloak OIDC）。

## API 端点列表

### 实时数据 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/dashboard/realtime/` | GET | 实时统计数据 |
| `/api/dashboard/processes/` | GET | 工序列表 |
| `/api/dashboard/hourly/` | GET | 每小时产量统计 |
| `/api/dashboard/flow/<flow_name>/` | GET | 指定 Flow 统计数据 |
| `/api/dashboard/workorders/` | GET | 工单列表 |
| `/api/dashboard/workorders/<wrk_order>/` | GET | 工单详情 |

### 生产详情 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/dashboard/detail/stepno-overview/` | GET | 工序概览 |
| `/api/dashboard/detail/flows/` | GET | Flow 概览 |
| `/api/dashboard/detail/flow/<flow_name>/` | GET | Flow 详情 |
| `/api/dashboard/detail/stepno/<stepno>/` | GET | 工序详情 |

### 历史数据 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/history/date/<date>/` | GET | 指定日期统计（支持 mode=local/remote） |
| `/api/history/dates/` | GET | 有数据的可用日期列表 |
| `/api/history/sync/<date>/` | POST | 同步远程数据到本地 |

### 图表与排行 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/dashboard/monthly-trend/` | GET | 当月每日总产量趋势 |
| `/api/dashboard/process-compare/` | GET | 工序 x 生产线产量对比 |
| `/api/dashboard/heatmap/` | GET | 工时 x 生产线热力图 |
| `/api/dashboard/station-ranking/` | GET | 工站产量排行 |

### 目标产量 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/dashboard/set-targets/` | POST | 设定员工日目标产量 |

### SSE 实时推送

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/dashboard/stream/` | GET | SSE 实时数据流 |

## 使用示例

### 获取实时统计

```bash
curl -X GET https://dktportal.dongming.local/iwork/api/dashboard/realtime/ \
  -H "Content-Type: application/json" \
  -H "Cookie: _oauth2_proxy=..."
```

**响应示例**:
```json
{
  "total_qty": 12345,
  "workorder_count": 67,
  "employee_count": 89,
  "hourly_stats": [...],
  "process_stats": [...]
}
```

### 获取工单列表

```bash
curl -X GET https://dktportal.dongming.local/iwork/api/dashboard/workorders/ \
  -H "Content-Type: application/json" \
  -H "Cookie: _oauth2_proxy=..."
```

**响应示例**:
```json
{
  "workorders": [
    {
      "wrk_order": "WO240101001",
      "total_qty": 500,
      "step_count": 5,
      "worker_count": 10
    }
  ],
  "pagination": {
    "page": 1,
    "total_pages": 5,
    "total_count": 50
  }
}
```

### 获取历史数据

```bash
curl -X GET "https://dktportal.dongming.local/iwork/api/history/date/2026-06-08/?mode=local" \
  -H "Content-Type: application/json" \
  -H "Cookie: _oauth2_proxy=..."
```

### SSE 实时推送连接

```javascript
const eventSource = new EventSource('/iwork/api/dashboard/stream/');
eventSource.onmessage = function(event) {
    const data = JSON.parse(event.data);
    console.log('实时数据:', data);
};
```

## 数据结构

### 实时统计数据

```json
{
  "total_qty": "总产量",
  "workorder_count": "工单数量",
  "employee_count": "员工数量",
  "hourly_stats": [
    {
      "hour": "小时",
      "qty": "产量"
    }
  ],
  "process_stats": [
    {
      "stepno": "工序号",
      "qty": "产量",
      "worker_count": "人数"
    }
  ]
}
```

### 工单数据

```json
{
  "wrk_order": "工单号",
  "total_qty": "总产量",
  "step_count": "工序数",
  "worker_count": "工人数",
  "steps": [
    {
      "stepno": "工序号",
      "qty": "产量"
    }
  ]
}
```

## AI Agent 接入

### Python 示例

```python
import requests
import json

class IworkClient:
    def __init__(self, base_url="https://dktportal.dongming.local/iwork"):
        self.base_url = base_url
        self.session = requests.Session()
    
    def login(self, username, password):
        """Portal OIDC 登录（获取 session cookie）"""
        # 实际场景中需要通过 oauth2-proxy 的 OIDC 流程获取 cookie
        pass
    
    def get_realtime_stats(self):
        """获取实时统计"""
        response = self.session.get(f"{self.base_url}/api/dashboard/realtime/")
        return response.json()
    
    def get_workorders(self, page=1):
        """获取工单列表"""
        response = self.session.get(
            f"{self.base_url}/api/dashboard/workorders/",
            params={"page": page}
        )
        return response.json()
    
    def get_history_stats(self, date):
        """获取历史统计"""
        response = self.session.get(f"{self.base_url}/api/history/date/{date}/")
        return response.json()

# 使用示例（需要先通过 OIDC 认证获取有效 session）
client = IworkClient()
# client.login("username", "password")  # OIDC 认证
stats = client.get_realtime_stats()
print(f"当前总产量: {stats['total_qty']}")
```

### JavaScript 示例

```javascript
class IworkClient {
    constructor(baseUrl = 'https://dktportal.dongming.local/iwork') {
        this.baseUrl = baseUrl;
    }
    
    async getRealtimeStats() {
        const response = await fetch(`${this.baseUrl}/api/dashboard/realtime/`, {
            credentials: 'include'  // 携带 OIDC session cookie
        });
        return response.json();
    }
    
    async getWorkorders(page = 1) {
        const response = await fetch(
            `${this.baseUrl}/api/dashboard/workorders/?page=${page}`,
            { credentials: 'include' }
        );
        return response.json();
    }
}

// 使用示例（需要已登录 Portal）
const client = new IworkClient();
const stats = await client.getRealtimeStats();
console.log(`当前总产量: ${stats.total_qty}`);
```

## 错误处理

### HTTP 状态码

| 状态码 | 说明 |
|--------|------|
| 200 | 成功 |
| 400 | 请求参数错误 |
| 401 | 未认证（需要有效 Portal 登录会话） |
| 403 | 禁止访问（IP 不在信任列表或权限不足） |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |

### 错误响应格式

```json
{
  "error": "错误描述",
  "detail": "详细错误信息"
}
```

## 注意事项

1. **认证必需**: 所有 API 需要有效 Portal 登录会话（Keycloak OIDC），直接访问会返回 403 Forbidden
2. **请求频率**: 建议不超过每秒 10 次请求
3. **数据缓存**: 实时数据每 60 秒更新一次
4. **超时设置**: 建议请求超时设置为 30 秒
5. **编码**: 所有请求和响应使用 UTF-8 编码

## 联系方式

如有技术问题，请联系开发团队。
