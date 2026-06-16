-- ==========================================
-- iwork 项目 — 数据库初始化脚本
-- 由 MySQL 容器首次启动时自动执行
-- ==========================================

-- Django 系统库（认证、会话、迁移记录等）
CREATE DATABASE IF NOT EXISTS iwork_system
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 本地业务数据同步库（远程 payroll 数据的本地镜像）
CREATE DATABASE IF NOT EXISTS iwork_local
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 创建应用用户
CREATE USER IF NOT EXISTS 'iwork_admin'@'%'
  IDENTIFIED BY 'iwork_db_pwd_2026';

-- 授权
GRANT ALL PRIVILEGES ON iwork_system.* TO 'iwork_admin'@'%';
GRANT ALL PRIVILEGES ON iwork_local.* TO 'iwork_admin'@'%';
FLUSH PRIVILEGES;
