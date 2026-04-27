import json
import logging

from mobius.logging import configure_logging, get_logger


def test_configure_logging_writes_records_to_stderr_only(
    capsys,
) -> None:
    configure_logging(level="INFO", force=True)
    logger = get_logger("mobius.tests.logging")

    logger.info("MOBIUS_LOG_MARKER_UNIT")

    captured = capsys.readouterr()
    assert "MOBIUS_LOG_MARKER_UNIT" not in captured.out
    assert "MOBIUS_LOG_MARKER_UNIT" in captured.err
    assert "INFO" in captured.err


def test_get_logger_returns_standard_library_logger() -> None:
    logger = get_logger("mobius.tests.type")

    assert isinstance(logger, logging.Logger)


def test_get_logger_preserves_configured_json_formatter(capsys) -> None:
    configure_logging(level="INFO", json_output=True, force=True)

    first_logger = get_logger("child")
    second_logger = get_logger("child")

    assert first_logger is second_logger
    second_logger.info("MOBIUS_JSON_FORMATTER_MARKER")

    captured = capsys.readouterr()
    assert captured.out == ""
    payload = json.loads(captured.err)
    assert payload["logger"] == "child"
    assert payload["message"] == "MOBIUS_JSON_FORMATTER_MARKER"
