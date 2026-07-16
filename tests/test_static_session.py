import asyncio

import pytest
from fastapi import HTTPException

from domains.machine.services import MachineService
from domains.users.schemas import SessionPickupRequest
from domains.users.services import SessionService


class FakeSessionRepository:
    """Réplica em memória da SessionRepository (mesma semântica atômica)."""

    def __init__(self):
        self.docs = {}

    async def create(self, doc):
        self.docs[doc["_id"]] = dict(doc)

    async def find(self, session_id):
        doc = self.docs.get(session_id)
        return dict(doc) if doc else None

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
