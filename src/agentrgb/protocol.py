"""Строгий профиль входного контракта 04A, без содержимого диалогов."""
from dataclasses import dataclass
from datetime import datetime
import re

MAX_BODY = 4096
KINDS = {"run_started", "run_waiting", "run_resumed", "run_ended"}
FIELDS = {"schema_version", "source", "source_instance_id", "session_id",
          "run_id", "event_id", "kind", "timestamp", "metadata"}
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


@dataclass(frozen=True)
class Event:
    source: str
    source_instance_id: str
    session_id: str
    run_id: str
    event_id: str
    kind: str
    timestamp: str
    outcome: str = "unknown"

    @property
    def key(self):
        return (self.source, self.source_instance_id, self.session_id, self.run_id)


def validate(value):
    def require(condition):
        if not condition:
            raise ValueError("invalid_event")

    require(type(value) is dict and set(value) == FIELDS)
    require(type(value["schema_version"]) is int and value["schema_version"] == 1)
    require(value["source"] == "pi")
    for name in ("source_instance_id", "session_id", "run_id", "event_id"):
        require(type(value[name]) is str and IDENTIFIER.fullmatch(value[name]))
    require(type(value["kind"]) is str and value["kind"] in KINDS)
    stamp = value["timestamp"]
    require(type(stamp) is str and len(stamp) <= 40)
    try:
        require(datetime.fromisoformat(stamp).tzinfo is not None)
    except (ValueError, TypeError):
        raise ValueError("invalid_event") from None
    metadata = value["metadata"]
    require(type(metadata) is dict)
    if value["kind"] == "run_ended":
        require(set(metadata) <= {"outcome"})
        require(metadata.get("outcome", "unknown") in ("completed", "unknown"))
    else:
        require(not metadata)
    return Event(**{name: value[name] for name in
                   ("source", "source_instance_id", "session_id", "run_id", "event_id", "kind", "timestamp")},
                 outcome=metadata.get("outcome", "unknown"))
