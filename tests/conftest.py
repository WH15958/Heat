"""Keep software test artifacts out of real experiment and sample history."""
import pytest

from runtime_isolation import isolated_runtime


@pytest.fixture(autouse=True)
def isolated_test_runtime():
    with isolated_runtime() as directory:
        yield directory
