"""floored entry point: python floored.py serve --workspace DIR [--port N]

When the private environment ~/.floored/venv exists (the doctor makes it), every command runs inside it: this launcher
hands over to its Python. FLOORED_NO_VENV=1 turns that off."""
import os
import sys

# redirected output uses the ANSI code page on Windows: keep non-ASCII paths from crashing the server
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, 'reconfigure'):
        _stream.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == '__main__':
    from ft import doctor  # noqa: E402  (standard library only)
    _code = doctor.run_in_venv(sys.argv[1:], os.path.abspath(__file__))
    if _code is not None:
        sys.exit(_code)
    from ft.cli import main  # noqa: E402
    sys.exit(main(sys.argv[1:]))
