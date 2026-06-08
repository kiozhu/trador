"""File system watcher — hot-reload strategy when files change"""
import time
from pathlib import Path
from typing import Callable

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent

from ..utils.logger import log


class StrategyFileHandler(FileSystemEventHandler):
    def __init__(self, strategies_dir: Path, on_change: Callable[[str], None]):
        super().__init__()
        self.strategies_dir = Path(strategies_dir)
        self.on_change = on_change
        self._last_reload: dict[str, float] = {}

    def on_modified(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix == ".json" and path.parent == self.strategies_dir:
            strategy_id = path.stem
            # Debounce: ignore if reloaded within2 seconds
            now = time.time()
            last = self._last_reload.get(strategy_id, 0)
            if now - last < 2:
                return
            self._last_reload[strategy_id] = now
            log.info("Strategy file changed: %s", strategy_id)
            self.on_change(strategy_id)


class StrategyWatcher:
    def __init__(self, strategies_dir: Path, on_change: Callable[[str], None]):
        self.strategies_dir = Path(strategies_dir)
        self.on_change = on_change
        self.observer = Observer()
        self.handler = StrategyFileHandler(strategies_dir, on_change)

    def start(self):
        self.observer.schedule(self.handler, str(self.strategies_dir), recursive=False)
        self.observer.start()
        log.info("Strategy watcher started on %s", self.strategies_dir)

    def stop(self):
        self.observer.stop()
        self.observer.join()
        log.info("Strategy watcher stopped")
