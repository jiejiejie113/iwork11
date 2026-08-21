from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_iwork_compose_maps_only_required_central_secrets():
    content = (ROOT / 'docker-compose.yml').read_text(encoding='utf-8')
    assert 'DJANGO_SECRET_KEY: ${IWORK_DJANGO_SECRET_KEY:?' in content
    assert 'ACCESS_DB_PASSWORD: ${IWORK_APP_DB_PASSWORD:?' in content
    assert 'LOCAL_DB_PASSWORD: ${IWORK_APP_DB_PASSWORD:?' in content
    assert 'IWORK_DB_PASSWORD: ${IWORK_DB_PASSWORD:?' in content
    assert '8000:8000' not in content


def test_iwork_docker_build_context_excludes_dotenv_files():
    lines = (ROOT / '.dockerignore').read_text(encoding='utf-8').splitlines()
    assert '.env' in lines
    assert '*.env' in lines


def test_non_secret_profiles_are_present_and_contain_no_passwords():
    for name in ('local.env', 'production.env'):
        content = (ROOT / 'env' / name).read_text(encoding='utf-8')
        assert 'DKT_ENVIRONMENT=' in content
        assert 'PASSWORD=' not in content
        assert 'SECRET_KEY=' not in content


def test_production_profile_accepts_ditu_and_legacy_portal_hosts():
    """生产环境在迁移观察期必须同时接受DITU正式入口和DKT旧入口。"""
    content = (ROOT / 'env' / 'production.env').read_text(encoding='utf-8')
    allowed_hosts_line = next(
        line for line in content.splitlines() if line.startswith('DJANGO_ALLOWED_HOSTS=')
    )
    allowed_hosts = set(allowed_hosts_line.split('=', 1)[1].split(','))

    assert {
        'dituportal.dongming.local',
        'auth.dituportal.dongming.local',
        'dktportal.dongming.local',
        'auth.dktportal.dongming.local',
    } <= allowed_hosts


def test_deploy_script_loads_profile_and_central_secrets():
    content = (ROOT / 'deploy.ps1').read_text(encoding='utf-8')
    assert "'--env-file', $Profile" in content
    assert "'--env-file', $SecretsFile" in content
    assert 'down -v' not in content.lower()


def test_iwork_healthcheck_uses_an_allowed_host_header():
    """容器健康检查必须携带生产环境允许的Host，避免正常服务被误判为400。"""
    content = (ROOT / 'docker-compose.yml').read_text(encoding='utf-8')

    assert "'Host':'iwork'" in content
