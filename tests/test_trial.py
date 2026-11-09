import uuid

from licencias import trial


def test_machine_id_estable_si_la_mac_es_aleatoria(monkeypatch):
    valores = iter([0x010000000001, 0x01AABBCCDDEE])  # bit multicast: MAC inventada por Python
    monkeypatch.setattr(uuid, "getnode", lambda: next(valores))
    assert trial._machine_id() == trial._machine_id()


def test_machine_id_con_mac_real_no_cambia_formula(monkeypatch):
    import hashlib
    import socket
    monkeypatch.setattr(uuid, "getnode", lambda: 0x00AABBCCDDEE)
    esperado = hashlib.sha256(f"{0x00AABBCCDDEE}-{socket.gethostname()}".encode()).hexdigest()[:20]
    assert trial._machine_id() == esperado


def test_trial_sigue_vigente_al_reabrir(tmp_path, monkeypatch):
    monkeypatch.setattr(trial, "TRIAL_PATH", str(tmp_path / ".trial"))
    primero = trial.activar_o_verificar_trial()
    segundo = trial.activar_o_verificar_trial()
    assert primero["dias_restantes"] == segundo["dias_restantes"] == 7
