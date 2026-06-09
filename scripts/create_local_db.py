#!/usr/bin/env python
"""
创建本地业务数据库和表结构
"""
import os
import sys
import pymysql
from dotenv import load_dotenv

# 加载环境变量
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'iwork', '.env'))

# 本地数据库配置
LOCAL_DB_HOST = os.getenv('LOCAL_DB_HOST', 'localhost')
LOCAL_DB_PORT = int(os.getenv('LOCAL_DB_PORT', '3306'))
LOCAL_DB_NAME = os.getenv('LOCAL_DB_NAME', 'iwork_local')
LOCAL_DB_USER = os.getenv('LOCAL_DB_USER', 'iwork_local')
LOCAL_DB_PASSWORD = os.getenv('LOCAL_DB_PASSWORD', 'Lpf12160')

# root 用户配置（用于创建数据库和用户）
ROOT_HOST = os.getenv('LOCAL_DB_HOST', 'localhost')
ROOT_PORT = int(os.getenv('LOCAL_DB_PORT', '3306'))
ROOT_USER = 'root'
ROOT_PASSWORD = 'lpf121666'  # MySQL root密码


def create_local_database():
    """使用 root 用户创建本地数据库和用户"""
    conn = pymysql.connect(
        host=ROOT_HOST,
        port=ROOT_PORT,
        user=ROOT_USER,
        password=ROOT_PASSWORD,
        charset='utf8mb4'
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{LOCAL_DB_NAME}` "
                f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            print(f"数据库 {LOCAL_DB_NAME} 创建成功")

            cursor.execute(
                f"CREATE USER IF NOT EXISTS '{LOCAL_DB_USER}'@'localhost' "
                f"IDENTIFIED BY '{LOCAL_DB_PASSWORD}'"
            )
            cursor.execute(
                f"GRANT ALL PRIVILEGES ON `{LOCAL_DB_NAME}`.* TO '{LOCAL_DB_USER}'@'localhost'"
            )
            cursor.execute("FLUSH PRIVILEGES")
            print(f"用户 {LOCAL_DB_USER} 创建并授权成功")
    finally:
        conn.close()


def create_local_table():
    """在本地数据库中创建 pytckreg3 表"""
    conn = pymysql.connect(
        host=LOCAL_DB_HOST,
        port=LOCAL_DB_PORT,
        user=LOCAL_DB_USER,
        password=LOCAL_DB_PASSWORD,
        database=LOCAL_DB_NAME,
        charset='utf8mb4'
    )
    try:
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS `pytckreg3` (
            `TicketNo` VARCHAR(13) NOT NULL,
            `SeqNo` INT DEFAULT 0,
            `WrkOrder` VARCHAR(14) DEFAULT '',
            `BundleNo` INT DEFAULT 0,
            `StepNo` INT DEFAULT 0,
            `Qty` INT DEFAULT 0,
            `RegPerSysID` INT DEFAULT 0,
            `RegDate` DATETIME,
            `RegTime` DATETIME,
            `RFID` VARCHAR(10) DEFAULT '',
            `Flow` VARCHAR(40) DEFAULT '',
            `PO` VARCHAR(40) DEFAULT '',
            `TimeCost` INT DEFAULT 0,
            `SysSource` VARCHAR(3) DEFAULT '',
            `AccBundleNo` INT DEFAULT 0,
            `MtrType` VARCHAR(14) DEFAULT '',
            `Color` VARCHAR(35) DEFAULT '',
            `Sizx` VARCHAR(16) DEFAULT '',
            `SerialNum` VARCHAR(10) DEFAULT '',
            `StationID` VARCHAR(3) DEFAULT '',
            PRIMARY KEY (`TicketNo`),
            INDEX `idx_regdate` (`RegDate`),
            INDEX `idx_wrkorder` (`WrkOrder`),
            INDEX `idx_flow` (`Flow`),
            INDEX `idx_station` (`StationID`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
        with conn.cursor() as cursor:
            cursor.execute(create_table_sql)
        conn.commit()
        print("表 pytckreg3 创建成功")
    finally:
        conn.close()


if __name__ == '__main__':
    try:
        create_local_database()
        create_local_table()
        print("本地数据库初始化完成")
    except Exception as e:
        print(f"错误: {e}")
        sys.exit(1)
