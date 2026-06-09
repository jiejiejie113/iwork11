# 生产看板日期查询与本地持久化设计文档

## 概述

本文档描述了生产看板系统的增强功能设计，包括：
1. 支持根据日期查询历史数据
2. 实时数据与历史数据视图切换
3. 业务数据本地持久化

## 需求分析

### 功能需求

1. **日期查询功能**
   - 支持选择任意日期查看历史数据
   - 保持现有实时数据功能（今日数据）

2. **视图切换功能**
   - 实时数据视图：显示今日实时数据，通过WebSocket更新
   - 历史数据视图：显示指定日期的历史数据，从本地数据库读取

3. **数据持久化功能**
   - 创建本地业务数据库（iwork_local）
   - 将远程业务数据同步到本地
   - 支持增量同步，只更新有变动的数据

### 非功能需求

1. **性能要求**
   - 实时数据响应时间 < 1秒
   - 历史数据查询响应时间 < 2秒
   - 同步操作不影响实时数据性能

2. **数据一致性**
   - 实时数据：WebSocket推送 → 写入Redis缓存 → 异步写入本地数据库
   - 历史数据：从本地数据库读取，保证数据一致性
   - 同步操作：用户手动触发，从远程数据库同步到本地，覆盖本地数据

3. **可扩展性**
   - 支持后续功能扩展
   - 模块化设计，便于维护

## 技术设计

### 数据库设计

#### 本地数据库（iwork_local）

**数据库配置：**
- 数据库名：iwork_local
- 用户：iwork_local（需创建）
- 权限：读写

**环境变量配置（.env文件）：**
```bash
# 本地业务数据库（读写）
LOCAL_DB_HOST=localhost
LOCAL_DB_PORT=3306
LOCAL_DB_NAME=iwork_local
LOCAL_DB_USER=iwork_local
LOCAL_DB_PASSWORD=your_password_here
```

**Django settings.py配置：**
```python
DATABASES = {
    # ... 现有配置
    'iwork_local': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': env('LOCAL_DB_NAME'),
        'USER': env('LOCAL_DB_USER'),
        'PASSWORD': env('LOCAL_DB_PASSWORD'),
        'HOST': env('LOCAL_DB_HOST'),
        'PORT': env.int('LOCAL_DB_PORT', default=3306),
        'OPTIONS': {
            'charset': 'utf8mb4',
        },
    },
}
```

**数据库路由配置：**
```python
class DatabaseRouter:
    """
    数据库路由器：
    - default: Django 系统权限库（读写）
    - iwork: 业务生产数据库（只读）
    - iwork_local: 本地业务数据库（读写）
    """
    
    iwork_app_labels = ['iwork']
    
    def db_for_read(self, model, **hints):
        """指定模型的读取数据库"""
        if model._meta.app_label in self.iwork_app_labels:
            if model._meta.model_name == 'localpytckreg3':
                return 'iwork_local'
            return 'iwork'
        return 'default'
    
    def db_for_write(self, model, **hints):
        """指定模型的写入数据库"""
        if model._meta.app_label in self.iwork_app_labels:
            if model._meta.model_name == 'localpytckreg3':
                return 'iwork_local'
            return None  # 远程数据库只读
        return 'default'
    
    def allow_relation(self, obj1, obj2, **hints):
        """判断两个对象是否允许关联"""
        db1 = obj1._state.db
        db2 = obj2._state.db
        if db1 and db2:
            return db1 == db2
        return None
    
    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """判断是否允许迁移"""
        if app_label in self.iwork_app_labels:
            if model_name == 'localpytckreg3':
                return db == 'iwork_local'
            return False
        return db == 'default'
```

**表结构：**
```sql
-- 与远程数据库payroll.pytckreg3相同的表结构
CREATE TABLE pytckreg3 (
    TicketNo VARCHAR(13) PRIMARY KEY,
    SeqNo INT DEFAULT 0,
    WrkOrder VARCHAR(14) DEFAULT '',
    BundleNo INT DEFAULT 0,
    StepNo INT DEFAULT 0,
    Qty INT DEFAULT 0,
    RegPerSysID INT DEFAULT 0,
    RegDate DATETIME,
    RegTime DATETIME,
    RFID VARCHAR(10) DEFAULT '',
    Flow VARCHAR(40) DEFAULT '',
    PO VARCHAR(40) DEFAULT '',
    TimeCost INT DEFAULT 0,
    SysSource VARCHAR(3) DEFAULT '',
    AccBundleNo INT DEFAULT 0,
    MtrType VARCHAR(14) DEFAULT '',
    Color VARCHAR(35) DEFAULT '',
    Sizx VARCHAR(16) DEFAULT '',
    SerialNum VARCHAR(10) DEFAULT '',
    StationID VARCHAR(3) DEFAULT ''
);
```

### 模型设计

#### 本地Pytckreg3模型

```python
class LocalPytckreg3(models.Model):
    """
    本地业务数据模型（可读写）
    映射到 iwork_local.pytckreg3 表
    """
    TicketNo = models.CharField('票号', max_length=13, primary_key=True)
    SeqNo = models.IntegerField('序号', default=0)
    WrkOrder = models.CharField('工单号', max_length=14, blank=True, default='')
    BundleNo = models.IntegerField('扎号', default=0)
    StepNo = models.IntegerField('工序号', default=0)
    Qty = models.IntegerField('数量', default=0)
    RegPerSysID = models.IntegerField('登记人系统ID', default=0)
    RegDate = models.DateTimeField('登记日期', null=True, blank=True)
    RegTime = models.DateTimeField('登记时间', null=True, blank=True)
    RFID = models.CharField('RFID', max_length=10, blank=True, default='')
    Flow = models.CharField('流程', max_length=40, blank=True, default='')
    PO = models.CharField('PO号', max_length=40, blank=True, default='')
    TimeCost = models.IntegerField('耗时', default=0)
    SysSource = models.CharField('系统来源', max_length=3, default='')
    AccBundleNo = models.IntegerField('累计扎号', default=0)
    MtrType = models.CharField('物料类型', max_length=14, blank=True, default='')
    Color = models.CharField('颜色', max_length=35, blank=True, default='')
    Sizx = models.CharField('尺码', max_length=16, blank=True, default='')
    SerialNum = models.CharField('序列号', max_length=10, blank=True, default='')
    StationID = models.CharField('工位ID', max_length=3, blank=True, default='')
    
    class Meta:
        app_label = 'iwork'
        db_table = 'pytckreg3'
        managed = False
        verbose_name = '本地打卡记录'
        verbose_name_plural = '本地打卡记录'
```

### API设计

#### 1. 日期查询API

**端点：** `GET /api/dashboard/date/<date>/`

**参数：**
- `date`：查询日期（格式：YYYY-MM-DD）
- `mode`：查询模式（可选，默认'local'）
  - `local`：从本地数据库查询
  - `remote`：从远程数据库查询

**响应：**
```json
{
    "date": "2026-04-24",
    "source": "local",  // "local" 或 "remote"
    "stats": {
        "workorder_count": 56,
        "total_qty": 1234,
        "avg_time_cost": 4.2
    },
    "hourly_stats": [...],
    "process_stats": [...],
    "flow_stats": [...],
    "station_stats": [...],
    "worker_ranking": [...],
    "workorders": [...]
}
```

#### 2. 获取可用日期API

**端点：** `GET /api/dashboard/dates/`

**参数：**
- `mode`：查询模式（可选，默认'local'）
  - `local`：只返回本地有数据的日期
  - `remote`：返回所有可用日期

**响应：**
```json
{
    "mode": "local",
    "dates": [
        "2026-04-24",
        "2026-04-23",
        "2026-04-22"
    ]
}
```

#### 3. 同步API

**端点：** `POST /api/sync/<date>/`

**参数：**
- `date`：同步日期（格式：YYYY-MM-DD）

**响应：**
```json
{
    "success": true,
    "message": "同步完成",
    "synced_count": 1234,
    "updated_count": 56,
    "skipped_count": 1178
}
```

#### 4. 实时数据API（现有）

**端点：** `GET /api/dashboard/realtime/`

**响应：** 保持现有格式

### 前端设计

#### UI修改

在现有页面顶部添加：

1. **视图切换按钮**
   - 实时数据按钮
   - 历史数据按钮

2. **数据模式切换（历史数据视图）**
   - 本地模式按钮：只显示本地有数据的日期
   - 远程模式按钮：可以查询任意日期

3. **日期选择器**
   - 本地模式：只允许选择有数据的日期
   - 远程模式：可以选择任意日期
   - 默认选择今天

4. **同步按钮**
   - 仅在历史数据视图显示
   - 点击同步当前选择日期的数据

5. **数据源指示器**
   - 显示当前数据来源（远程/本地）
   - 显示同步状态

#### 交互逻辑

1. **视图切换**
   - 点击"实时数据"：加载今日实时数据
   - 点击"历史数据"：加载指定日期的历史数据

2. **数据模式切换**
   - 点击"本地模式"：日期选择器只显示本地有数据的日期
   - 点击"远程模式"：日期选择器可以查询任意日期

3. **日期选择**
   - 选择今天：自动切换到实时数据视图
   - 选择其他日期：加载该日期的历史数据

4. **同步操作**
   - 点击同步按钮：将指定日期数据同步到本地
   - 显示同步进度和结果

### 数据流设计

#### 实时数据流

```
远程数据库 → Redis缓存 → WebSocket → 前端
                ↓
            异步写入本地数据库
```

#### 历史数据流（本地模式）

```
用户选择日期 → 本地数据库查询 → 返回数据
```

#### 历史数据流（远程模式）

```
用户选择日期 → 远程数据库查询 → 返回数据
                            → 可选：同步到本地数据库
```

#### 同步数据流

```
用户点击同步 → 调用同步API → 从远程查询数据 → 对比本地数据 → 更新有变动的数据
```
远程数据库 → Redis缓存 → WebSocket → 前端
                ↓
            异步写入本地数据库
```

#### 历史数据流

```
用户选择日期 → 检查本地数据库 → 有数据则返回
                            → 无数据则从远程查询并缓存到本地
```

**数据查询模式：**

1. **本地模式**
   - 只显示本地数据库中已有数据的日期
   - 日期选择器只允许选择有数据的日期
   - 查询速度快，无网络延迟
   - 适用于查看已同步的历史数据

2. **远程模式**
   - 可以选择任意日期
   - 从远程数据库查询数据
   - 查询速度受网络影响
   - 适用于查看未同步的最新数据

**模式切换逻辑：**
```python
def get_available_dates(mode='local'):
    """
    获取可用的日期列表
    
    Args:
        mode: 'local' 或 'remote'
        
    Returns:
        list: 可用日期列表
    """
    if mode == 'local':
        # 从本地数据库获取有数据的日期
        dates = LocalPytckreg3.objects.using('iwork_local').dates(
            'RegDate', 'day', order='DESC'
        )
        return [date.date() for date in dates]
    else:
        # 从远程数据库获取所有日期（可能需要分页）
        dates = Pytckreg3.objects.using('iwork').dates(
            'RegDate', 'day', order='DESC'
        )
        return [date.date() for date in dates]
```

#### 同步数据流

```
用户点击同步 → 调用同步API → 从远程查询数据 → 对比本地数据 → 更新有变动的数据
```

### 同步策略

#### 增量同步算法

```python
def sync_date_data(target_date):
    """
    同步指定日期的数据到本地数据库
    
    Args:
        target_date: 目标日期
        
    Returns:
        dict: 同步结果统计
    """
    from iwork.models import Pytckreg3
    from iwork.models import LocalPytckreg3
    from django.db import transaction
    
    # 1. 从远程数据库查询数据
    remote_records = Pytckreg3.objects.using('iwork').filter(
        RegDate__date=target_date
    )
    
    # 2. 从本地数据库查询现有数据
    local_records = {
        record.TicketNo: record 
        for record in LocalPytckreg3.objects.using('iwork_local').filter(
            RegDate__date=target_date
        )
    }
    
    # 3. 对比并更新
    stats = {
        'synced_count': 0,
        'updated_count': 0,
        'skipped_count': 0
    }
    
    with transaction.atomic():
        for record in remote_records:
            local_record = local_records.get(record.TicketNo)
            
            if local_record is None:
                # 新增记录
                LocalPytckreg3.objects.using('iwork_local').create(
                    TicketNo=record.TicketNo,
                    SeqNo=record.SeqNo,
                    WrkOrder=record.WrkOrder,
                    BundleNo=record.BundleNo,
                    StepNo=record.StepNo,
                    Qty=record.Qty,
                    RegPerSysID=record.RegPerSysID,
                    RegDate=record.RegDate,
                    RegTime=record.RegTime,
                    RFID=record.RFID,
                    Flow=record.Flow,
                    PO=record.PO,
                    TimeCost=record.TimeCost,
                    SysSource=record.SysSource,
                    AccBundleNo=record.AccBundleNo,
                    MtrType=record.MtrType,
                    Color=record.Color,
                    Sizx=record.Sizx,
                    SerialNum=record.SerialNum,
                    StationID=record.StationID,
                )
                stats['synced_count'] += 1
            elif has_changes(local_record, record):
                # 更新有变动的记录
                local_record.SeqNo = record.SeqNo
                local_record.WrkOrder = record.WrkOrder
                local_record.BundleNo = record.BundleNo
                local_record.StepNo = record.StepNo
                local_record.Qty = record.Qty
                local_record.RegPerSysID = record.RegPerSysID
                local_record.RegDate = record.RegDate
                local_record.RegTime = record.RegTime
                local_record.RFID = record.RFID
                local_record.Flow = record.Flow
                local_record.PO = record.PO
                local_record.TimeCost = record.TimeCost
                local_record.SysSource = record.SysSource
                local_record.AccBundleNo = record.AccBundleNo
                local_record.MtrType = record.MtrType
                local_record.Color = record.Color
                local_record.Sizx = record.Sizx
                local_record.SerialNum = record.SerialNum
                local_record.StationID = record.StationID
                local_record.save(using='iwork_local')
                stats['updated_count'] += 1
            else:
                # 跳过无变动的记录
                stats['skipped_count'] += 1
    
    return stats
```

#### 数据变更检测

```python
def has_changes(local_record, remote_record):
    """
    检测记录是否有变更
    
    Args:
        local_record: 本地记录
        remote_record: 远程记录
        
    Returns:
        bool: 是否有变更
    """
    # 比较关键字段
    compare_fields = [
        'SeqNo', 'WrkOrder', 'BundleNo', 'StepNo', 'Qty',
        'RegPerSysID', 'RegDate', 'RegTime', 'RFID', 'Flow',
        'PO', 'TimeCost', 'SysSource', 'AccBundleNo', 'MtrType',
        'Color', 'Sizx', 'SerialNum', 'StationID'
    ]
    
    for field in compare_fields:
        local_value = getattr(local_record, field)
        remote_value = getattr(remote_record, field)
        
        # 处理None值
        if local_value is None and remote_value is None:
            continue
        if local_value is None or remote_value is None:
            return True
        
        # 比较值
        if local_value != remote_value:
            return True
    
    return False
```

## 实现计划

### 阶段1：数据库和模型（1天）

1. 创建本地数据库iwork_local
2. 创建本地Pytckreg3模型
3. 配置数据库路由
4. 测试数据库连接

### 阶段2：后端API（2天）

1. 实现日期查询API（支持local/remote模式）
2. 实现获取可用日期API
3. 实现同步API
4. 实现增量同步逻辑
5. 添加错误处理和日志

### 阶段3：前端UI（1天）

1. 添加视图切换按钮
2. 添加数据模式切换按钮（本地/远程）
3. 添加日期选择器（根据模式动态调整）
4. 添加同步按钮
5. 添加数据源指示器

### 阶段4：集成测试（1天）

1. 测试实时数据功能
2. 测试历史数据查询
3. 测试数据同步
4. 性能测试

### 阶段5：优化和文档（1天）

1. 性能优化
2. 错误处理优化
3. 编写用户文档
4. 编写技术文档

## 风险评估

### 技术风险

1. **数据一致性风险**
   - 风险：实时数据与历史数据不一致
   - 缓解：使用事务保证数据一致性

2. **性能风险**
   - 风险：同步操作影响实时数据性能
   - 缓解：异步同步，优先保证实时性能

3. **存储风险**
   - 风险：本地数据库存储空间不足
   - 缓解：定期清理过期数据，监控存储使用

### 业务风险

1. **用户体验风险**
   - 风险：同步操作耗时较长
   - 缓解：显示同步进度，提供取消操作

2. **数据安全风险**
   - 风险：本地数据泄露
   - 缓解：数据加密，访问控制

## 测试策略

### 单元测试

1. 数据库连接测试
2. 模型CRUD测试
3. 同步逻辑测试
4. API端点测试

### 集成测试

1. 实时数据流程测试
2. 历史数据查询测试（本地模式）
3. 历史数据查询测试（远程模式）
4. 数据同步流程测试
5. 模式切换功能测试
6. 前端交互测试

### 性能测试

1. 实时数据响应时间测试
2. 历史数据查询性能测试
3. 同步操作性能测试
4. 并发用户测试

## 部署计划

### 开发环境

1. 创建本地数据库
2. 配置开发环境
3. 运行测试

### 测试环境

1. 部署到测试服务器
2. 执行集成测试
3. 性能测试

### 生产环境

1. 备份现有数据
2. 创建生产数据库
3. 部署应用
4. 监控运行状态

## 维护计划

### 日常维护

1. 监控数据库性能
2. 检查同步任务状态
3. 清理过期数据

### 故障处理

1. 数据同步失败处理
2. 数据库连接失败处理
3. 前端显示异常处理

### 版本升级

1. 数据库结构升级
2. API接口升级
3. 前端功能升级

## 总结

本设计文档详细描述了生产看板系统的增强功能设计，包括日期查询、视图切换和数据持久化。通过合理的数据库设计、API设计和前端设计，实现了用户需求，同时保证了系统的性能、可靠性和可扩展性。