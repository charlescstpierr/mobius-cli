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
