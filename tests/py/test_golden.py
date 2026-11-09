"""Visual regression: each ready look at its default settings on the sample take must still render like its golden.
One HyperFrames snapshot run per look (all three instants), cached for the session. Slow:
`pytest -m slow tests/py/test_golden.py`. Refresh the goldens on purpose with
`python dev/bench/make.py --golden tests/golden`."""
import sys
from pathlib import Path

import pytest

import imgcmp

REPO = Path(__file__).resolve().parents[2]
GOLDEN = REPO / 'tests' / 'golden'
sys.path.insert(0, str(REPO / 'dev' / 'bench'))
import make  # noqa: E402

MIN_SSIM = 0.985
_rendered = {}


@pytest.fixture(scope='session')
def work(tmp_path_factory):
    return tmp_path_factory.mktemp('ftg')


def render_look(look, work):
    if look not in _rendered:
        _rendered[look] = make.render_goldens(work, looks=[look])    # {golden file name: png}, all instants of this look
    return _rendered[look]


@pytest.mark.slow
@pytest.mark.parametrize('t', make.GOLDEN_TIMES, ids=lambda t: '%.1f' % t)
@pytest.mark.parametrize('look', make.LOOKS)
def test_golden_matches(look, t, work):
    name = make.golden_name(look, t)
    golden = GOLDEN / name
    assert golden.exists(), '%s is missing (python dev/bench/make.py --golden tests/golden)' % golden
    new = render_look(look, work)[name]
    assert imgcmp.ssim(new, golden) >= MIN_SSIM
