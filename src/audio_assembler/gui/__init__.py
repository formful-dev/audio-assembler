"""User interface (PySide6). Built on audio_assembler.core only."""


def main() -> int:
    from .app import run
    return run()
