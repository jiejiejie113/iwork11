from django.conf import settings


def test_pytest_uses_isolated_in_process_dependencies():
    """测试运行不得连接部署环境的 Redis 或 MySQL。"""
    assert settings.CACHES['default']['BACKEND'] == 'iwork.test_cache.PatternLocMemCache'
    assert {
        config['ENGINE'] for config in settings.DATABASES.values()
    } == {'django.db.backends.sqlite3'}
