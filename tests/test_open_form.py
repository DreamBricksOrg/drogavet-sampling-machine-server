import pytest
from fastapi import HTTPException

import domains.users.services as users_services
from domains.users.services import SessionService

from .test_static_session import FakeLogSender, FakeSessionRepository


class FakeUDP:
    def __init__(self):
        self.messages = []

    def send(self, msg):
        self.messages.append(msg)


@pytest.fixture
def repo():
    return FakeSessionRepository()


@pytest.fixture
def udp(monkeypatch):
    fake = FakeUDP()
    monkeypatch.setattr(users_services, "_udp_sender", fake)
    return fake


@pytest.fixture
def service(repo, udp, monkeypatch):
    monkeypatch.setattr(users_services, "LogSender", FakeLogSender)
    return SessionService(session_repository=repo)


async def make_pending(service):
    return await service.init_static_session()


async def test_primeira_abertura_marca_e_envia_udp(service, repo, udp):
    doc = await make_pending(service)
    template = await service.open_form(doc["_id"])
    assert template == "form.html"
    assert repo.docs[doc["_id"]]["status"] == "form_shown"
    assert udp.messages == ["next"]


async def test_refresh_do_form_continua_no_form(service, repo, udp):
    doc = await make_pending(service)
    await service.open_form(doc["_id"])
    template = await service.open_form(doc["_id"])  # refresh
    assert template == "form.html"
    assert udp.messages == ["next"]  # UDP não é reenviado


async def test_form_apos_fluxo_encerrado_404(service, repo):
    doc = await make_pending(service)
    repo.docs[doc["_id"]]["status"] = "completed"
    with pytest.raises(HTTPException) as exc:
        await service.open_form(doc["_id"])
    assert exc.value.status_code == 404


async def test_form_sid_invalido_vai_para_error(service):
    template = await service.open_form("nao-existe")
    assert template == "error.html"
