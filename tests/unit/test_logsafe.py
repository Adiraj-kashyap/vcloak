"""M10 A4: the logging allow-list, and the log of a service run searched for what must never be in it.
(M11 finalises the allow-list and adds the session fields.)"""
from __future__ import annotations

import logging
import re
from typing import Any

import numpy as np
import pytest

from service_contract import post, read, send_across_windows, token, vcloak_harness
from vcloak.service import logsafe
from vcloak.service.models import conv_id_of, encode_payload
from vcloak.storage.repo import SqliteRepo


def test_allowed_fields_render_sorted() -> None:
    assert logsafe.render("window_closed", {"win": 3, "rows": 120}) == "event=window_closed rows=120 win=3"
    assert logsafe.render("started", {"mode": "vcloak", "ready": True}) == "event=started mode=vcloak ready=True"


@pytest.mark.parametrize("field", [*logsafe.FORBIDDEN_EXAMPLES, "user", "ip", "htu", "nonce", "tag", "anything_new"])
def test_fields_off_the_allow_list_are_refused(field: str) -> None:
    assert field not in logsafe.ALLOWED
    with pytest.raises(logsafe.ForbiddenLogField) as err:
        logsafe.render("x", {field: 1})
    assert field in str(err.value)


@pytest.mark.parametrize("value", [1.5, 1712000000.123, b"\x00" * 8, None, [1], {"a": 1}, "two words",
                                   "a" * 41, "dG9rZW4=", "9f8a7c", "x/y", ""])
def test_values_that_could_carry_a_secret_are_refused(value: object) -> None:
    with pytest.raises(logsafe.ForbiddenLogField) as err:
        logsafe.render("x", {"status": value})
    assert "status" in str(err.value)
    if isinstance(value, str) and len(value) > 3:
        assert value not in str(err.value)  # the error names the field, never the value


def test_text_is_allowed_only_in_text_fields() -> None:
    assert logsafe.TEXT_FIELDS <= logsafe.ALLOWED
    for field in sorted(logsafe.ALLOWED - logsafe.TEXT_FIELDS):
        with pytest.raises(logsafe.ForbiddenLogField):
            logsafe.render("x", {field: "text"})


@pytest.mark.parametrize("event", ["Window Closed", "", "x" * 41, "win=3", "9lives"])
def test_event_names_are_identifiers(event: str) -> None:
    with pytest.raises(logsafe.ForbiddenLogField):
        logsafe.render(event, {})


def test_failure_logs_the_exception_class_only(caplog: pytest.LogCaptureFixture) -> None:
    log = logsafe.get_logger("t")
    with caplog.at_level(logging.DEBUG, logger="vcloak"):
        log.failure("epoch_failed", ValueError("conv_token=abc payload=deadbeef"), queued=2)
    assert caplog.messages == ["event=epoch_failed error=ValueError queued=2"]


def test_timestamps_have_one_second_resolution() -> None:
    record = logging.LogRecord("vcloak.t", logging.INFO, __file__, 1, "event=x", None, None)
    line = logging.Formatter(logsafe.FORMAT, logsafe.DATEFMT).format(record)
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d INFO vcloak\.t event=x", line), line


def test_configure_is_idempotent() -> None:
    root = logging.getLogger(logsafe.ROOT_LOGGER)
    before, propagate, level = list(root.handlers), root.propagate, root.level
    try:
        logsafe.configure()
        logsafe.configure()
        assert len([h for h in root.handlers if getattr(h, "_vcloak", False)]) == 1
    finally:
        root.handlers[:] = before
        root.propagate, root.level = propagate, level


def test_a4_the_log_of_a_service_run_holds_no_forbidden_value(caplog: pytest.LogCaptureFixture) -> None:
    """Traffic over three windows, an overflowing read, a failed epoch and an invalid request: then the
    captured log is searched for conversation tokens and ids, buckets, payload bytes and epoch numbers."""
    h = vcloak_harness(SqliteRepo(), cand_k=8)
    seen: dict[str, Any] = {}

    async def scenario(client: Any) -> None:
        sent = await send_across_windows(h, client, n=60)
        seen["sent"] = sent
        conv = max(sent, key=lambda c: len(sent[c]))
        r = await client.post("/v1/read", json={"conv_token": conv, "win": 0})
        assert r.status_code == 503  # more than cand_k = 8 rows in the bucket-window
        assert (await post(client, token("x"), b"too short")).status_code == 422
        engine = h.backend.engine
        write, state = engine.write_epoch, {"fail": True}

        def flaky(epoch: int, batch: list[Any]) -> list[Any]:
            if state.pop("fail", False):
                raise RuntimeError(f"epoch {epoch} conv {batch[0].conv_id}")
            return write(epoch, batch)

        engine.write_epoch = flaky
        assert (await post(client, conv, sent[conv][0])).status_code == 202
        await h.step(2)
        assert h.backend.scheduler.errors == 1
        seen["extra"] = await read(client, token("nobody"), 9)
        assert np.all(engine.bucket_of(np.array([conv_id_of(c) for c in sent], dtype=np.uint64)) < 4)

    with caplog.at_level(logging.DEBUG):
        h.serve(scenario)
    text = "\n".join(f"{r.name} {r.getMessage()}" for r in caplog.records if r.name.startswith("vcloak"))
    events = re.findall(r"event=(\w+)", text)
    assert {"started", "window_closed", "candidate_overflow", "epoch_failed", "stopped"} <= set(events)

    for conv, payloads in seen["sent"].items():
        assert conv not in text and str(conv_id_of(conv)) not in text and hex(conv_id_of(conv))[2:] not in text
        for p in payloads:
            assert encode_payload(p)[:24] not in text and p[:8].hex() not in text
    keys = set(re.findall(r"(\w+)=", text))
    assert keys <= logsafe.ALLOWED | {"event"}, keys - logsafe.ALLOWED
    assert not keys & {"bucket", "conv_id", "conv_token", "seq", "row_id", "epoch", "payload"}
    # no row ids, and no long digit runs (epoch numbers, millisecond timestamps, conversation ids)
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-", text) and not re.search(r"\d{10,}", text)
