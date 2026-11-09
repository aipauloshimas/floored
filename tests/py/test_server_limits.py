"""ft.server limits, with the real Handler on a loopback port and a stub pipeline: the byte cap for chunked uploads,
the socket timeout for a stalled body, and a JSON body nested too deep."""
import http.client
import json
import os
import socket
import sys
import threading
import time

import pytest

from ft import server


class StubPipe:
    busy = False

    def __init__(self, folder):
        self.folder, self.aborted, self.finished = folder, [], []

    def begin_upload(self, filename):
        path = os.path.join(self.folder, 'source.mp4')
        return 't1', path

    def abort_upload(self, tid):
        self.aborted.append(tid)

    def finish_upload(self, tid):
        self.finished.append(tid)


class StubExporter:
    def submit(self, *a):
        return 'e1'


@pytest.fixture
def live(tmp_path):
    srv = server.Server(('127.0.0.1', 0), server.Handler)
    srv.pipe, srv.exporter, srv.activity = StubPipe(str(tmp_path)), StubExporter(), server.Activity()
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv, srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def chunks(total, size=1000):
    left = total
    while left > 0:
        yield b'x' * min(size, left)
        left -= size


def test_chunked_upload_cannot_pass_the_cap(live, monkeypatch):
    srv, port = live
    monkeypatch.setattr(server, 'MAX_UPLOAD', 5000)
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=20)
    try:
        conn.request('POST', '/api/takes', body=chunks(20000), headers={'X-Filename': 'a.mp4'}, encode_chunked=True)
    except (BrokenPipeError, ConnectionResetError):
        pass                    # macOS: the server answered 413 and closed while the client was still sending the rest
    try:
        r = conn.getresponse()
        assert r.status == 413 and 'too large' in json.loads(r.read())['error']
    except (BrokenPipeError, ConnectionResetError, http.client.RemoteDisconnected):
        assert sys.platform != 'win32'                              # Windows always reads the 413
    deadline = time.time() + 5
    while not srv.pipe.aborted and time.time() < deadline:
        time.sleep(0.05)
    assert srv.pipe.aborted == ['t1'] and srv.pipe.finished == []
    assert not os.path.exists(os.path.join(srv.pipe.folder, 'source.mp4')) or \
        os.path.getsize(os.path.join(srv.pipe.folder, 'source.mp4')) <= 5000 + 1000      # it stopped writing at the cap


def test_chunked_upload_under_the_cap_still_works(live, monkeypatch):
    srv, port = live
    monkeypatch.setattr(server, 'MAX_UPLOAD', 5000)
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=20)
    conn.request('POST', '/api/takes', body=chunks(3000), headers={'X-Filename': 'a.mp4'}, encode_chunked=True)
    r = conn.getresponse()
    assert r.status == 200 and json.loads(r.read()) == {'id': 't1'} and srv.pipe.finished == ['t1']


def test_handler_has_a_socket_timeout():
    assert server.Handler.timeout == 120


def test_a_stalled_body_aborts_the_request(live, monkeypatch):
    srv, port = live
    monkeypatch.setattr(server.Handler, 'timeout', 1)                 # the real value is 120 s
    s = socket.create_connection(('127.0.0.1', port), timeout=20)
    s.sendall(b'POST /api/takes HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nX-Filename: a.mp4\r\nContent-Length: 100000\r\n\r\n' % port + b'x' * 10)
    t0 = time.time()
    data = s.recv(4096)                                               # the server answers (400) instead of waiting forever
    assert time.time() - t0 < 10 and b' 400 ' in data.split(b'\r\n')[0]
    assert srv.pipe.aborted == ['t1']
    for _ in range(40):
        if srv.activity.inflight == 0:
            break
        time.sleep(0.1)
    assert srv.activity.inflight == 0                                 # so the idle exit is not held back
    s.close()


def test_deeply_nested_json_is_a_400_not_a_dead_thread(live):
    srv, port = live
    body = b'[' * 200000 + b']' * 200000
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=20)
    conn.request('POST', '/api/export', body=body, headers={'Content-Type': 'application/json'})
    r = conn.getresponse()
    assert r.status == 400 and 'not valid JSON' in json.loads(r.read())['error']
