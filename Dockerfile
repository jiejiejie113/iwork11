# 基础镜像 - 使用DaoCloud镜像源
FROM python:3.11-slim

# 设置pip国内镜像源
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    default-libmysqlclient-dev \
    supervisor \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# 工作目录
WORKDIR /app

# 安装Python依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码
COPY . .

# 创建日志目录
RUN mkdir -p /app/logs

# 复制启动脚本
COPY start.sh /app/start.sh
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/start.sh /app/entrypoint.sh

# 以非 root 用户运行：消除 Celery superuser 警告，uvicorn 同步受益。
# 固定 uid 便于宿主机排查；实际降权在 entrypoint 中完成——必须先以 root
# 修正 bind mount 里历史 root 属主的日志文件，否则追加报 Permission denied。
RUN groupadd -r -g 10001 iwork && \
    useradd -r -u 10001 -g iwork -d /app -s /usr/sbin/nologin iwork && \
    chown -R iwork:iwork /app

# 暴露端口
EXPOSE 8000

# 启动入口：root 修正挂载权限后降权执行 start.sh
ENTRYPOINT ["bash", "/app/entrypoint.sh"]
