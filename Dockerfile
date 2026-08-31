# 基础镜像 - 使用DaoCloud镜像源
FROM python:3.11-slim@sha256:1042b61448fef4ba92d16a8c7eb4996d027568ce64792a7877fd88511e0af7c6

# 固定Debian软件源快照，避免基础镜像构建时解析到漂移的APT输入。
ARG DEBIAN_SNAPSHOT=20260824T000000Z

# 设置pip国内镜像源
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 基础镜像Digest必须确实对应Debian trixie；若上游Digest被误配到其它发行版，
# 在使用固定APT快照前立即失败，避免静默混用发行版仓库。
RUN set -eux; . /etc/os-release; test "$ID" = "debian"; test "$VERSION_CODENAME" = "trixie"

# 系统依赖：使用固定快照，并禁止安装推荐包和建议包。
RUN set -eux; \
    rm -f /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources; \
    printf '%s\n' \
        "deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT} trixie main" \
        "deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT} trixie-updates main" \
        "deb [check-valid-until=no] https://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT} trixie-security main" \
        > /etc/apt/sources.list.d/debian-snapshot.list; \
    apt-get -o Acquire::Check-Valid-Until=false update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends --no-install-suggests \
    gcc \
    default-libmysqlclient-dev \
    supervisor \
    pkg-config \
    ; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*

# 工作目录
WORKDIR /app

# 安装Python依赖
COPY requirements-prod.lock .
RUN pip install --no-cache-dir --require-hashes --no-build-isolation -r requirements-prod.lock

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
