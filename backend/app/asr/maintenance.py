"""One-shot admin commands, never an HTTP endpoint or resident worker."""
import argparse
import json
from pathlib import Path

from ..ai_config import setting
from .service import ASRService
from .temporary import sweep


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["usage", "cleanup"])
    args = parser.parse_args()
    default = Path(__file__).resolve().parents[2] / "data" / "learning.sqlite3"
    service = ASRService(Path(setting("VIDEO_LEARNING_DB", str(default))).parent)
    if args.command == "usage":
        print(json.dumps(service.store.usage_report(), ensure_ascii=False, indent=2))
    else:
        sweep(service.config.temp_root)
        service.cleanup_objects()
        remaining = len(service.store.artifacts())
        print(json.dumps({"remaining_object_cleanup_records": remaining}))


if __name__ == "__main__":
    main()
