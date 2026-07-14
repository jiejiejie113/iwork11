"""
pytest 配置文件：初始化 Django 环境。

Django 模型需要在测试收集前完成应用注册。
"""
import os
import django


def pytest_configure():
    """pytest 启动时初始化 Django"""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'iwork.test_settings')
    django.setup()
