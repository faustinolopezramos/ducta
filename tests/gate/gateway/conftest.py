import pytest


@pytest.fixture(autouse=True)
def _block_real_driver_downloads(monkeypatch, request):
    """Fail fast if a test accidentally hits Maven Central for a JDBC driver.

    ConnectionManager/JDBCConnector download real JARs over the network when not
    mocked. Mark a test with @pytest.mark.network to opt out and allow real I/O.
    """
    if "network" in request.keywords:
        yield
        return

    def _blocked(*args, **kwargs):
        raise AssertionError(
            "Test attempted a real JDBC driver download. Mock JDBCConnector.download_driver "
            "or ConnectionManager._create_connector, or mark the test @pytest.mark.network."
        )

    monkeypatch.setattr(
        "ducta.gate.gateway.connector.urllib.request.urlretrieve", _blocked, raising=True
    )
    yield
