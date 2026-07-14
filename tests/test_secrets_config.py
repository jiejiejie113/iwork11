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


def test_deploy_script_loads_profile_and_central_secrets():
    content = (ROOT / 'deploy.ps1').read_text(encoding='utf-8')
    assert "'--env-file', $Profile" in content
    assert "'--env-file', $SecretsFile" in content
    assert 'down -v' not in content.lower()
