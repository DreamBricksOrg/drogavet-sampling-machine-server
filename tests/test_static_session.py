import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from domains.machine.services import MachineService
from domains.users.schemas import SessionPickupRequest
from domains.users.services import (
    PICKUP_BLOCK_COOKIE_NAME,
    SessionService,
    build_pickup_block_cookie_value,
    is_pickup_blocked,
    is_within_business_hours,
)


class FakeSessionRepository:
    """Réplica em memória da SessionRepository (mesma semântica atômica)."""

    def __init__(self):
        self.docs = {}

    async def create(self, doc):
        self.docs[doc["_id"]] = dict(doc)

    async def find(self, session_id):
        doc = self.docs.get(session_id)
        return dict(doc) if doc else None

    async def try_mark_form_opened(self, session_id, now):
        doc = self.docs.get(session_id)
        if not doc or doc["status"] != "pending" or doc.get("retire_sent"):
            return None
        doc.update(retire_sent=True, status="form_shown", form_opened_at=now)
        return dict(doc)

    async def try_start_processing(self, session_id, slug, now):
        doc = self.docs.get(session_id)
        if not doc or doc["slug"] != slug or doc["status"] != "form_shown" or doc.get("processing"):
            return None
        doc.update(processing=True, status="processing", processing_started_at=now)
        return dict(doc)

    async def finalize(self, session_id, status, now):
        doc = self.docs.get(session_id)
        if doc:
            doc.update(status=status, processing=False, completed_at=now)


class FakeLogSender:
    def log(self, *args, **kwargs):
        pass


@pytest.fixture
def repo():
    return FakeSessionRepository()


@pytest.fixture
def service(repo, monkeypatch):
    import domains.users.services as users_services
    monkeypatch.setattr(users_services, "LogSender", FakeLogSender)
    return SessionService(session_repository=repo)


async def seed_form_shown(service, repo):
    doc = await service.init_static_session()
    repo.docs[doc["_id"]]["status"] = "form_shown"
    return doc


async def test_init_static_session_cria_doc(service, repo):
    doc = await service.init_static_session()
    saved = repo.docs[doc["_id"]]
    assert saved["mode"] == "qrcode_static"
    assert saved["status"] == "pending"
    assert saved["short_url"] is None
    assert len(saved["slug"]) >= 6


async def test_get_session_info_retorna_mode(service, repo):
    doc = await service.init_static_session()
    info = await service.get_session_info(doc["_id"])
    assert info.mode == "qrcode_static"


async def test_start_pickup_completa_sessao(service, repo, monkeypatch):
    async def fake_cycle(self, *args, **kwargs):
        return "completed"

    monkeypatch.setattr(MachineService, "pickup_cycle", fake_cycle)
    doc = await seed_form_shown(service, repo)

    resp = await service.start_pickup(SessionPickupRequest(session_id=doc["_id"], slug=doc["slug"]))
    assert resp.status == "processing"

    # aguarda a task background finalizar
    for _ in range(50):
        if repo.docs[doc["_id"]]["status"] == "completed":
            break
        await asyncio.sleep(0.05)
    assert repo.docs[doc["_id"]]["status"] == "completed"


async def test_start_pickup_falha_finaliza_failed(service, repo, monkeypatch):
    async def fake_cycle(self, *args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(MachineService, "pickup_cycle", fake_cycle)
    doc = await seed_form_shown(service, repo)

    await service.start_pickup(SessionPickupRequest(session_id=doc["_id"], slug=doc["slug"]))
    for _ in range(50):
        if repo.docs[doc["_id"]]["status"] == "failed":
            break
        await asyncio.sleep(0.05)
    assert repo.docs[doc["_id"]]["status"] == "failed"


async def test_start_pickup_one_shot(service, repo, monkeypatch):
    async def fake_cycle(self, *args, **kwargs):
        await asyncio.sleep(0.2)
        return "completed"

    monkeypatch.setattr(MachineService, "pickup_cycle", fake_cycle)
    doc = await seed_form_shown(service, repo)

    await service.start_pickup(SessionPickupRequest(session_id=doc["_id"], slug=doc["slug"]))
    with pytest.raises(HTTPException) as exc:
        await service.start_pickup(SessionPickupRequest(session_id=doc["_id"], slug=doc["slug"]))
    assert exc.value.status_code == 409


async def test_start_pickup_slug_errado(service, repo):
    doc = await seed_form_shown(service, repo)
    with pytest.raises(HTTPException) as exc:
        await service.start_pickup(SessionPickupRequest(session_id=doc["_id"], slug="errado"))
    assert exc.value.status_code == 400


async def test_start_pickup_sid_inexistente(service):
    with pytest.raises(HTTPException) as exc:
        await service.start_pickup(SessionPickupRequest(session_id="nao-existe", slug="x"))
    assert exc.value.status_code == 404


def test_build_pickup_block_cookie_value_formato():
    now = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    value = build_pickup_block_cookie_value("sid-123", now)
    assert value == f"sid-123:{int(now.timestamp())}"


def test_is_pickup_blocked_dentro_da_janela():
    now = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    cookie_value = build_pickup_block_cookie_value("sid-123", now)
    later = now + timedelta(hours=11, minutes=59)
    assert is_pickup_blocked(cookie_value, later, hours=12) is True


def test_is_pickup_blocked_apos_a_janela():
    now = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    cookie_value = build_pickup_block_cookie_value("sid-123", now)
    later = now + timedelta(hours=12, minutes=1)
    assert is_pickup_blocked(cookie_value, later, hours=12) is False


def test_is_pickup_blocked_cookie_ausente():
    now = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    assert is_pickup_blocked(None, now, hours=12) is False
    assert is_pickup_blocked("", now, hours=12) is False


def test_is_pickup_blocked_cookie_malformado():
    now = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    assert is_pickup_blocked("sem-dois-pontos", now, hours=12) is False
    assert is_pickup_blocked("sid-123:nao-e-numero", now, hours=12) is False
    assert is_pickup_blocked("sid-123:", now, hours=12) is False


def test_pickup_block_cookie_name():
    assert PICKUP_BLOCK_COOKIE_NAME == "sample_pickup_block"


def test_is_within_business_hours_dentro_da_janela():
    # 14h em America/Sao_Paulo (UTC-3) = 17h UTC
    now = datetime(2026, 8, 10, 17, 0, 0, tzinfo=timezone.utc)
    assert is_within_business_hours(now, "America/Sao_Paulo", 10, 20) is True


def test_is_within_business_hours_antes_de_abrir():
    # 8h em America/Sao_Paulo = 11h UTC
    now = datetime(2026, 8, 10, 11, 0, 0, tzinfo=timezone.utc)
    assert is_within_business_hours(now, "America/Sao_Paulo", 10, 20) is False


def test_is_within_business_hours_apos_fechar():
    # 20h em America/Sao_Paulo = 23h UTC (close_hour é exclusivo)
    now = datetime(2026, 8, 10, 23, 0, 0, tzinfo=timezone.utc)
    assert is_within_business_hours(now, "America/Sao_Paulo", 10, 20) is False


def test_is_within_business_hours_no_limite_de_abertura():
    # exatamente 10h em America/Sao_Paulo = 13h UTC (open_hour é inclusivo)
    now = datetime(2026, 8, 10, 13, 0, 0, tzinfo=timezone.utc)
    assert is_within_business_hours(now, "America/Sao_Paulo", 10, 20) is True
