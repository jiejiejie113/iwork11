# 门户系统接入指南

## 概述

本文档为门户系统和AI Agent提供iwork API接入指南。

## 基础信息

- **基础URL**: `http://your-domain.com` 或 `http://localhost:8000`
- **认证方式**: 无需认证（公开API）
- **数据格式**: JSON
- **字符编码**: UTF-8

## API端点列表

### 实时数据API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/dashboard/realtime/` | GET | 实时统计数据 |
| `/api/dashboard/processes/` | GET | 工序列表 |
| `/api/dashboard/hourly/` | GET | 每小时产量统计 |
| `/api/dashboard/flow/<flow_name>/` | GET | 指定Flow统计数据 |
| `/api/dashboard/workorders/` | GET | 工单列表 |
| `/api/dashboard/workorders/<wrk_order>/` | GET | 工单详情 |

### 生产详情API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/dashboard/detail/stepno-overview/` | GET | 工序概览 |
| `/api/dashboard/detail/flows/` | GET | Flow概览 |
| `/api/dashboard/detail/flow/<flow_name>/` | GET | Flow详情 |
| `/api/dashboard/detail/stepno/<stepno>/` | GET | 工序详情 |

### 历史数据API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/history/stats/<date>/` | GET | 指定日期统计 |
| `/api/history/monthly/<year>/<month>/` | GET | 月度统计 |
| `/api/history/sync/<date>/` | POST | 同步历史数据 |

### SSE实时推送

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/dashboard/stream/` | GET | SSE实时数据流 |

## 使用示例

### 获取实时统计

```bash
curl -X GET http://localhost:8000/api/dashboard/realtime/ \
  -H "Content-Type: application/json"
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
curl -X GET http://localhost:8000/api/dashboard/workorders/ \
  -H "Content-Type: application/json"
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
curl -X GET http://localhost:8000/api/history/stats/2026-06-08/ \
  -H "Content-Type: application/json"
```

### SSE实时推送连接

```javascript
const eventSource = new EventSource('/api/dashboard/stream/');
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

## AI Agent接入

### Python示例

```python
import requests
import json

class IworkClient:
    def __init__(self, base_url="http://localhost:8000"):
        self.base_url = base_url
    
    def get_realtime_stats(self):
        """获取实时统计"""
        response = requests.get(f"{self.base_url}/api/dashboard/realtime/")
        return response.json()
    
    def get_workorders(self, page=1):
        """获取工单列表"""
        response = requests.get(
            f"{self.base_url}/api/dashboard/workorders/",
            params={"page": page}
        )
        return response.json()
    
    def get_history_stats(self, date):
        """获取历史统计"""
        response = requests.get(f"{self.base_url}/api/history/stats/{date}/")
        return response.json()

# 使用示例
client = IworkClient()
stats = client.get_realtime_stats()
print(f"当前总产量: {stats['total_qty']}")
```

### JavaScript示例

```javascript
class IworkClient {
    constructor(baseUrl = 'http://localhost:8000') {
        this.baseUrl = baseUrl;
    }
    
    async getRealtimeStats() {
        const response = await fetch(`${this.baseUrl}/api/dashboard/realtime/`);
        return response.json();
    }
    
    async getWorkorders(page = 1) {
        const response = await fetch(
            `${this.baseUrl}/api/dashboard/workorders/?page=${page}`
        );
        return response.json();
    }
}

// 使用示例
const client = new IworkClient();
const stats = await client.getRealtimeStats();
console.log(`当前总产量: ${stats.total_qty}`);
```

## 错误处理

### HTTP状态码

| 状态码 | 说明 |
|--------|------|
| 200 | 成功 |
| 400 | 请求参数错误 |
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

1. **请求频率**: 建议不超过每秒10次请求
2. **数据缓存**: 实时数据每60秒更新一次
3. **超时设置**: 建议请求超时设置为30秒
4. **编码**: 所有请求和响应使用UTF-8编码

## 联系方式

如有技术问题，请联系开发团队。
