from infrastructure.hardware.serial_fake import FakeSerialComm


def test_fake_confirma_on_automaticamente():
    fake = FakeSerialComm()
    fake.send("on")
    assert fake.receive() == "on"
    assert fake.receive() is None


def test_fake_inject_entrega_na_ordem():
    fake = FakeSerialComm()
    fake.inject("1")
    fake.inject("dropped")
    assert fake.receive() == "1"
    assert fake.receive() == "dropped"
    assert fake.receive() is None


def test_fake_registra_enviados():
    fake = FakeSerialComm()
    fake.send("on")
    fake.send("off")
    assert fake.sent == ["on", "off"]


def test_get_serial_comm_respeita_flag(monkeypatch):
    import domains.machine.services as machine_services

    monkeypatch.setattr(machine_services, "_serial_comm", None)
    monkeypatch.setattr(machine_services.settings, "SERIAL_FAKE", True)
    comm = machine_services.get_serial_comm()
    assert isinstance(comm, FakeSerialComm)
