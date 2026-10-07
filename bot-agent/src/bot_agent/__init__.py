"""bot-agent — LiveKit Agents worker backing the webapp's bot conversations."""


def main() -> None:
    # Imported lazily: `livekit-agents` and the model runtimes are heavy, and
    # nothing else in this package should drag them in.
    from .agent import main as run_worker

    run_worker()
