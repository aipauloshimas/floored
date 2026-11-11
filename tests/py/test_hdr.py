"""ft.media.HDR_TO_SDR: an HDR clip keeps its brightness when tone-mapped to SDR (finding F-08: HDR clips came out darker).
The HDR clip is made from SDR frames of the shipped sample, with SDR white at 203 nits (BT.2408), so the SDR frames are
the reference: the converted clip's mean luma must be within 5 % of theirs. HLG is what an iPhone films by default;
PQ is what HDR10 and HDR10+ phones film."""
import subprocess

import numpy as np
import pytest

from conftest import APP, _ffmpeg
from ft import media

SAMPLE = APP / 'sample' / 'source.mp4'
TO_HDR = ('setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv,zscale=t=linear:npl=100,'
          'format=gbrpf32le,zscale=p=bt2020,zscale=t=%s:npl=203,zscale=m=bt2020nc:r=tv,format=yuv420p10le')


def mean_luma(path, vf):
    r = subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-i', str(path), '-vf', vf + ',format=yuv420p,extractplanes=y',
                        '-f', 'rawvideo', '-'], capture_output=True, check=True)
    return float(np.frombuffer(r.stdout, dtype=np.uint8).mean())


@pytest.mark.parametrize('transfer', ['arib-std-b67', 'smpte2084'], ids=['hlg', 'pq'])
def test_hdr_clip_keeps_its_brightness_in_sdr(tmp_path, transfer):
    sdr = tmp_path / 'sdr.mkv'
    hdr = tmp_path / 'hdr.mkv'
    _ffmpeg('-ss', 1, '-i', SAMPLE, '-frames:v', 5, '-an', '-vf', 'scale=480:-2,format=yuv420p', '-c:v', 'ffv1', sdr)
    _ffmpeg('-i', sdr, '-vf', TO_HDR % transfer, '-c:v', 'ffv1', '-pix_fmt', 'yuv420p10le', '-color_primaries', 'bt2020',
            '-color_trc', transfer, '-colorspace', 'bt2020nc', '-color_range', 'tv', hdr)
    assert media.is_hdr(transfer, 10)                               # the pipeline takes this clip down the HDR road
    ref = mean_luma(sdr, 'null')
    got = mean_luma(hdr, media.HDR_TO_SDR)
    assert abs(got - ref) / ref < 0.05, 'mean luma %.1f against %.1f (%+.1f %%)' % (got, ref, 100 * (got - ref) / ref)
