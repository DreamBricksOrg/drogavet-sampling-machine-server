import pytest

import domains.machine.services as machine_services
from domains.machine.services import MachineService


class FakeSerial:
    """Serial fake: devolve respostas roteirizadas, grava tudo que foi enviado."""

    def __init__(self, responses=None, fail_on_send=None):
        self.responses = list(responses or [])
        self.sent = []
        self.fail_on_send = fail_on_send  # mensagem que dispara exceção ao enviar

    def send(self, msg):
        if self.fail_on_send == msg:
            raise RuntimeError("serial quebrada")
        self.sent.append(msg)

    def receive(self):
        return self.responses.pop(0) if self.responses else None


class FakeInventory:
    def __init__(self):
        self.drops = 0

    async def update_on_drop(self):
        self.drops += 1
        return True


class FakeLogSender:
    def log(self, *args, **kwargs):
        pass


@pytest.fixture
def fake_serial(monkeypatch):
    fake = FakeSerial()
    monkeypatch.setattr(machine_services, "_serial_comm", fake)
    monkeypatch.setattr(machine_services, "LogSender", FakeLogSender)
    return fake


def make_service():
    inventory = FakeInventory()
    return MachineService(inventory_service=inventory), inventory


async def test_pickup_settings_default():
    from infrastructure.config import settings
    assert settings.PICKUP_TIMEOUT_SECONDS == 60


async def test_pickup_completed_decrementa_inventario(fake_serial):
    fake_serial.responses = ["on", "1"]
    service, inventory = make_service()
    status = await service.pickup_cycle(timeout_seconds=2)
    assert status == "completed"
    assert inventory.drops == 1
    assert fake_serial.sent == ["on", "off"]


async def test_pickup_timeout_envia_off(fake_serial):
    fake_serial.responses = ["on"]  # nunca chega "1"
    service, inventory = make_service()
    status = await service.pickup_cycle(timeout_seconds=0.3)
    assert status == "failed"
    assert inventory.drops == 0
    assert fake_serial.sent == ["on", "off"]


async def test_pickup_ignora_mensagens_diferentes_de_1(fake_serial):
    fake_serial.responses = ["on", "dropped", "lixo", "1"]
    service, inventory = make_service()
    status = await service.pickup_cycle(timeout_seconds=2)
    assert status == "completed"
    assert inventory.drops == 1


async def test_pickup_sem_confirmacao_on_continua(fake_serial):
    # Arduino não responde "on", mas envia "1" depois — ciclo completa mesmo assim
    fake_serial.responses = [None, None, "1"]
    service, inventory = make_service()
    status = await service.pickup_cycle(timeout_seconds=2, on_timeout_seconds=0.3)
    assert status == "completed"
    assert inventory.drops == 1


async def test_pickup_excecao_retorna_failed_e_tenta_off(fake_serial):
    fake_serial.fail_on_send = "on"
    service, inventory = make_service()
    status = await service.pickup_cycle(timeout_seconds=0.3)
    assert status == "failed"
    assert inventory.drops == 0
