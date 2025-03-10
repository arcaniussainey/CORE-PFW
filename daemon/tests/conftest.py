"""
Unit test fixture module.
"""

import threading
import time

import mock
import pytest

from core.api.grpc.client import InterfaceHelper
from core.api.grpc.server import CoreGrpcServer
from core.emulator.coreemu import CoreEmu
from core.emulator.data import IpPrefixes
from core.emulator.distributed import DistributedServer
from core.emulator.enumerations import EventTypes
from core.emulator.session import Session
from core.nodes.base import CoreNode

EMANE_SERVICES = "zebra|OSPFv3MDR|IPForward"


class PatchManager:
    def __init__(self):
        self.patches = []

    def patch_obj(self, _cls, attribute, return_value=None):
        p = mock.patch.object(_cls, attribute, return_value=return_value)
        p.start()
        self.patches.append(p)

    def patch(self, func):
        p = mock.patch(func)
        p.start()
        self.patches.append(p)

    def shutdown(self):
        for p in self.patches:
            p.stop()


class MockServer:
    def __init__(self, coreemu):
        self.config = {}
        self.coreemu = coreemu


@pytest.fixture(scope="session")
def patcher(request):
    patch_manager = PatchManager()
    patch_manager.patch_obj(DistributedServer, "remote_cmd", return_value="1")
    if request.config.getoption("mock"):
        patch_manager.patch("core.utils.cmd")
        patch_manager.patch("core.utils.which")
        patch_manager.patch("core.emulator.hooks._run_callback")
        patch_manager.patch("core.emulator.hooks._run_script")
        patch_manager.patch("core.nodes.netclient.get_net_client")
        patch_manager.patch_obj(CoreNode, "create_file")
    yield patch_manager
    patch_manager.shutdown()


@pytest.fixture(scope="session")
def global_coreemu(patcher):
    coreemu = CoreEmu(config={"emane_prefix": "/usr"})
    yield coreemu
    coreemu.shutdown()


@pytest.fixture(scope="session")
def global_session(request, patcher, global_coreemu):
    mkdir = not request.config.getoption("mock")
    session = Session(1000, {"emane_prefix": "/usr"}, mkdir)
    session.service_manager = global_coreemu.service_manager
    yield session
    session.shutdown()


@pytest.fixture(scope="session")
def ip_prefixes():
    return IpPrefixes(ip4_prefix="10.83.0.0/16")


@pytest.fixture(scope="session")
def iface_helper():
    return InterfaceHelper(ip4_prefix="10.83.0.0/16")


@pytest.fixture(scope="module")
def module_grpc(global_coreemu):
    grpc_server = CoreGrpcServer(global_coreemu)
    thread = threading.Thread(target=grpc_server.listen, args=("localhost:50051",))
    thread.daemon = True
    thread.start()
    time.sleep(0.1)
    yield grpc_server
    grpc_server.server.stop(None)


@pytest.fixture
def grpc_server(module_grpc):
    yield module_grpc
    for session in module_grpc.coreemu.sessions.values():
        session.set_state(EventTypes.CONFIGURATION_STATE)
    module_grpc.coreemu.shutdown()


@pytest.fixture
def session(global_session):
    global_session.set_state(EventTypes.CONFIGURATION_STATE)
    yield global_session
    global_session.data_collect()
    global_session.clear()


def pytest_addoption(parser):
    parser.addoption("--distributed", help="distributed server address")
    parser.addoption("--mock", action="store_true", help="run without mocking")


def pytest_generate_tests(metafunc):
    distributed_param = "distributed_address"
    if distributed_param in metafunc.fixturenames:
        distributed_address = metafunc.config.getoption("distributed")
        metafunc.parametrize(distributed_param, [distributed_address])
