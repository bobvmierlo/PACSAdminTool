"""
Tests for hardening of the built-in receivers (Storage SCP, C-GET, HL7):

  - received UIDs can never steer where files are written
  - the receive directory cannot overlap the app's own data
  - only *.dcm files are served / deleted / cleaned up
  - optional sender allowlists (calling AE title, IP / CIDR)
"""

import json
import os
import socket
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.network import address_allowed, parse_host_allowlist, validate_host_entry
from dicom.operations import _uid_path_component


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# UID → path component
# ---------------------------------------------------------------------------

class TestUidPathComponent:
    @pytest.mark.parametrize("uid", ["1.2.840.10008.1", "2.25.123456789", "1"])
    def test_valid_uid_kept(self, uid):
        assert _uid_path_component(uid, "fb") == uid

    def test_padding_stripped(self):
        assert _uid_path_component("1.2.3\x00", "fb") == "1.2.3"
        assert _uid_path_component(" 1.2.3 ", "fb") == "1.2.3"

    @pytest.mark.parametrize("uid", [
        "../../etc", "..", ".", "/data", "1.2/../../x", "1..2", ".1.2", "1.2.",
        "1.2.3<img src=x onerror=alert(1)>", "C:\\evil", "", None, "9" * 129,
    ])
    def test_malformed_uid_replaced(self, uid):
        assert _uid_path_component(uid, "fallback") == "fallback"


# ---------------------------------------------------------------------------
# Host allowlist helpers
# ---------------------------------------------------------------------------

class TestHostAllowlist:
    def test_empty_allows_everyone(self):
        assert address_allowed("192.0.2.1", [])

    def test_ip_and_cidr(self):
        nets = parse_host_allowlist(["10.1.2.3", "192.168.0.0/16"])
        assert address_allowed("10.1.2.3", nets)
        assert address_allowed("192.168.44.5", nets)
        assert not address_allowed("10.1.2.4", nets)

    def test_ipv4_mapped_ipv6(self):
        nets = parse_host_allowlist(["127.0.0.1"])
        assert address_allowed("::ffff:127.0.0.1", nets)

    def test_garbage_address_rejected(self):
        assert not address_allowed("not-an-ip", parse_host_allowlist(["10.0.0.0/8"]))

    def test_validate_entry(self):
        assert validate_host_entry("10.0.0.0/8") is None
        assert validate_host_entry("fe80::1") is None
        assert validate_host_entry("pacs.example.org") is not None
        assert validate_host_entry("") is not None


# ---------------------------------------------------------------------------
# Storage SCP (real association over localhost)
# ---------------------------------------------------------------------------

def _make_dataset(study_uid, series_uid, sop_uid):
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage

    ds = Dataset()
    ds.SOPClassUID = SecondaryCaptureImageStorage
    ds.SOPInstanceUID = sop_uid
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.PatientName = "Test^Patient"
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    return ds


def _send(port, ds, calling_ae="SENDER"):
    from pynetdicom import AE
    from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage

    ae = AE(ae_title=calling_ae)
    ae.acse_timeout = ae.network_timeout = 5
    ae.add_requested_context(SecondaryCaptureImageStorage, ExplicitVRLittleEndian)
    assoc = ae.associate("127.0.0.1", port, ae_title="PACSADMIN")
    if not assoc.is_established:
        return None
    status = assoc.send_c_store(ds)
    assoc.release()
    return status


@pytest.fixture()
def scp_factory(tmp_path):
    pytest.importorskip("pynetdicom")
    from dicom.operations import SCPListener

    listeners = []

    def make(**kwargs):
        port = _free_port()
        scp = SCPListener(ae_title="PACSADMIN", port=port,
                          storage_dir=str(tmp_path / "store"), **kwargs)
        scp.start()
        listeners.append(scp)
        return scp, port

    yield make
    for scp in listeners:
        scp.stop()


class TestStorageSCP:
    def test_normal_store(self, scp_factory, tmp_path):
        scp, port = scp_factory()
        status = _send(port, _make_dataset("1.2.3", "1.2.3.4", "1.2.3.4.5"))
        assert status is not None and status.Status == 0x0000
        assert (tmp_path / "store" / "1.2.3" / "1.2.3.4" / "1.2.3.4.5.dcm").is_file()

    def test_traversal_uids_stay_inside_storage_dir(self, scp_factory, tmp_path):
        scp, port = scp_factory()
        ds = _make_dataset("../../escaped", "/tmp/abs", "../../../pwned")
        status = _send(port, ds)
        assert status is not None and status.Status == 0x0000
        written = [os.path.join(dp, f) for dp, _, fs in os.walk(tmp_path) for f in fs]
        assert written, "file should have been stored"
        store = os.path.realpath(tmp_path / "store")
        for path in written:
            assert os.path.realpath(path).startswith(store + os.sep), path
        assert (tmp_path / "store" / "unknown_study" / "unknown_series").is_dir()

    def test_calling_ae_allowlist(self, scp_factory):
        scp, port = scp_factory(allowed_calling_aes=["MODALITY1"])
        ds = _make_dataset("1.2.3", "1.2.3.4", "1.2.3.4.6")
        assert _send(port, ds, calling_ae="INTRUDER") is None
        assert _send(port, ds, calling_ae="MODALITY1").Status == 0x0000

    def test_host_allowlist_rejects(self, scp_factory):
        messages = []
        scp, port = scp_factory(allowed_hosts=["10.0.0.0/8"],
                                log_callback=messages.append)
        assert _send(port, _make_dataset("1.2", "1.2.3", "1.2.3.4")) is None
        assert any("Rejected connection from 127.0.0.1" in m for m in messages)

    def test_host_allowlist_accepts(self, scp_factory):
        scp, port = scp_factory(allowed_hosts=["127.0.0.0/8"])
        assert _send(port, _make_dataset("1.2", "1.2.3", "1.2.3.5")).Status == 0x0000

    def test_stop_and_restart_same_port(self, scp_factory, tmp_path):
        from dicom.operations import SCPListener
        scp, port = scp_factory()
        scp.stop()
        again = SCPListener(ae_title="PACSADMIN", port=port,
                            storage_dir=str(tmp_path / "store"))
        again.start()
        try:
            assert _send(port, _make_dataset("1.9", "1.9.1", "1.9.1.1")).Status == 0x0000
        finally:
            again.stop()


# ---------------------------------------------------------------------------
# HL7 listener allowlist
# ---------------------------------------------------------------------------

def _hl7_listener(allowed_hosts):
    from hl7_module.messaging import HL7Listener
    received, rejected = [], []
    port = _free_port()
    listener = HL7Listener(port=port, callback=lambda m, a: received.append(m),
                           allowed_hosts=allowed_hosts,
                           reject_callback=rejected.append)
    listener.start()
    for _ in range(50):
        if listener.running:
            break
        time.sleep(0.05)
    return listener, port, received, rejected


class TestHL7ListenerAllowlist:
    MSG = "MSH|^~\\&|A|B|C|D|20240101||ADT^A01|1|P|2.5\rPID|1||123\r"

    def test_rejected_sender_gets_no_ack(self):
        from hl7_module.messaging import send_mllp
        listener, port, received, rejected = _hl7_listener(["10.0.0.0/8"])
        try:
            ok, _ = send_mllp("127.0.0.1", port, self.MSG)
            assert not ok
            assert received == []
            assert rejected == ["127.0.0.1"]
        finally:
            listener.stop()

    def test_allowed_sender(self):
        from hl7_module.messaging import send_mllp
        listener, port, received, rejected = _hl7_listener(["127.0.0.1"])
        try:
            ok, _ = send_mllp("127.0.0.1", port, self.MSG)
            assert ok
            assert len(received) == 1 and rejected == []
        finally:
            listener.stop()


# ---------------------------------------------------------------------------
# Web API: receive directory, file endpoints, config validation
# ---------------------------------------------------------------------------

@pytest.fixture()
def app(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("PACS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setenv("USERPROFILE", str(home_dir))

    import importlib
    import config.manager as config_mod
    import web.auth as auth_mod
    import web.server as server_mod
    importlib.reload(config_mod)
    importlib.reload(auth_mod)
    importlib.reload(server_mod)
    app = server_mod.app
    app.config["TESTING"] = True
    yield app

    import web.context as ctx
    with ctx._listener_lock:
        if ctx._scp_listener:
            ctx._scp_listener.stop()
            ctx._scp_listener = None
    ctx._last_scp_storage_dir = None


@pytest.fixture()
def admin(app):
    c = app.test_client()
    r = c.post("/setup", json={"username": "admin", "password": "testpass1"})
    assert r.status_code == 200
    return c


@pytest.fixture()
def regular(app, admin):
    admin.post("/api/users", json={"username": "user1", "password": "userpass1",
                                   "role": "user"})
    c = app.test_client()
    assert c.post("/login", json={"username": "user1",
                                  "password": "userpass1"}).status_code == 200
    return c


class TestReceiveDirectory:
    def test_resolve_rules(self, app, tmp_path):
        from config.manager import APP_DIR, LOG_DIR
        from web.helpers import resolve_receive_dir

        default, err = resolve_receive_dir(None, is_admin=False)
        assert err is None
        assert default == os.path.normpath(os.path.expanduser("~/DICOM_Received"))

        sub, err = resolve_receive_dir("~/DICOM_Received/test", is_admin=False)
        assert err is None and sub.endswith("test")

        for bad in ("/", APP_DIR, os.path.dirname(APP_DIR), LOG_DIR,
                    os.path.join(LOG_DIR, "x"), "~", "relative/dir"):
            path, err = resolve_receive_dir(bad, is_admin=True)
            assert path is None and err, bad

        # Inside the data dir (e.g. a Docker volume) is fine for admins
        ok_path, err = resolve_receive_dir(os.path.join(APP_DIR, "received"), is_admin=True)
        assert err is None and ok_path

        elsewhere = str(tmp_path / "elsewhere")
        assert resolve_receive_dir(elsewhere, is_admin=True)[1] is None
        assert resolve_receive_dir(elsewhere, is_admin=False)[0] is None

    def test_scp_start_rejects_data_dir(self, admin):
        from config.manager import APP_DIR
        r = admin.post("/api/scp/start", json={"port": _free_port(), "save_dir": APP_DIR})
        assert r.status_code == 400
        assert not r.get_json()["ok"]

    def test_non_admin_limited_to_default_dir(self, regular, tmp_path):
        r = regular.post("/api/scp/start", json={"port": _free_port(),
                                                 "save_dir": str(tmp_path / "other")})
        assert r.status_code == 400

    def test_cget_rejects_data_dir(self, admin):
        from config.manager import APP_DIR
        r = admin.post("/api/dicom/get", json={"host": "127.0.0.1", "port": 104,
                                               "ae_title": "X", "study_uid": "1.2",
                                               "save_dir": APP_DIR})
        assert r.status_code == 400


class TestStorageFileEndpoints:
    def _prepare(self, admin, tmp_path):
        store = tmp_path / "home" / "DICOM_Received"
        (store / "1.2" / "1.2.3").mkdir(parents=True)
        (store / "1.2" / "1.2.3" / "note.txt").write_text("not dicom")
        (store / "1.2" / "1.2.3" / "a.dcm").write_bytes(b"x")
        r = admin.post("/api/scp/start", json={"port": _free_port()})
        assert r.get_json()["ok"], r.get_json()
        return store

    def test_non_dcm_not_served_or_deleted(self, admin, tmp_path):
        store = self._prepare(admin, tmp_path)
        assert admin.get("/api/scp/files/raw?path=1.2/1.2.3/note.txt").status_code == 404
        r = admin.post("/api/scp/files/delete", json={"name": "1.2/1.2.3/note.txt"})
        assert r.status_code == 404
        assert (store / "1.2" / "1.2.3" / "note.txt").exists()
        assert admin.get("/api/scp/files/raw?path=1.2/1.2.3/a.dcm").status_code == 200

    def test_cleanup_only_removes_old_dcm(self, admin, tmp_path):
        from web.helpers import _cleanup_scp_storage
        store = self._prepare(admin, tmp_path)
        old = time.time() - 48 * 3600
        for name in ("note.txt", "a.dcm"):
            os.utime(store / "1.2" / "1.2.3" / name, (old, old))
        deleted, _ = _cleanup_scp_storage()
        assert deleted == 1
        assert (store / "1.2" / "1.2.3" / "note.txt").exists()
        assert not (store / "1.2" / "1.2.3" / "a.dcm").exists()


class TestAllowlistConfig:
    def test_valid_allowlists_saved(self, admin):
        r = admin.post("/api/config", json={
            "local_ae": {"ae_title": "PACSADMIN", "port": 11112,
                         "allowed_calling_aes": ["MOD1", "PACS MAIN"],
                         "allowed_hosts": ["10.0.0.1", "10.20.0.0/16"]},
            "hl7": {"listen_port": 2575, "allowed_hosts": ["192.168.1.0/24"]},
        })
        assert r.status_code == 200, r.get_json()
        cfg = admin.get("/api/config").get_json()
        assert cfg["local_ae"]["allowed_hosts"] == ["10.0.0.1", "10.20.0.0/16"]
        assert cfg["hl7"]["allowed_hosts"] == ["192.168.1.0/24"]

    @pytest.mark.parametrize("payload", [
        {"local_ae": {"allowed_hosts": ["pacs.example.org"]}},
        {"local_ae": {"allowed_hosts": "10.0.0.1"}},
        {"local_ae": {"allowed_calling_aes": ["THIS_AE_TITLE_IS_TOO_LONG"]}},
        {"local_ae": {"allowed_calling_aes": [""]}},
        {"hl7": {"allowed_hosts": ["300.1.1.1"]}},
    ])
    def test_invalid_allowlists_rejected(self, admin, payload):
        assert admin.post("/api/config", json=payload).status_code == 400


class TestUploadPath:
    @pytest.mark.parametrize("name,expected", [
        ("IM0001", "IM0001"),
        ("../../etc/cron.d/x", "x"),
        ("series1/IM0001.dcm", "IM0001.dcm"),
        ("..\\..\\evil.dcm", "evil.dcm"),
        ("..", "default.dcm"),
        ("", "default.dcm"),
        (None, "default.dcm"),
    ])
    def test_stays_inside_tmp_dir(self, tmp_path, name, expected):
        from web.helpers import _upload_path
        path = _upload_path(str(tmp_path), name, 3, "default.dcm")
        assert os.path.basename(path) == expected
        assert os.path.realpath(path).startswith(os.path.realpath(tmp_path) + os.sep)

    def test_same_name_different_index(self, tmp_path):
        from web.helpers import _upload_path
        a = _upload_path(str(tmp_path), "a/IM1", 0, "x")
        b = _upload_path(str(tmp_path), "b/IM1", 1, "x")
        assert a != b
