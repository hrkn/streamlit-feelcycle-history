import logging
import pathlib
import tempfile

import cryptography.fernet

import streamlit_feelcycle.encrypted_logger as encrypted_logger  # noqa: PLR0402


def test_get_default_log_path() -> None:
    path = encrypted_logger.get_default_log_path()
    assert isinstance(path, pathlib.Path)
    assert path.name == encrypted_logger.DEFAULT_LOG_FILENAME
    assert str(path.parent) == tempfile.gettempdir()


def test_get_encryption_key_from_env(monkeypatch) -> None:
    test_key = cryptography.fernet.Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("LOG_ENCRYPTION_KEY", test_key)
    monkeypatch.setattr(encrypted_logger.streamlit, "secrets", {}, raising=False)

    key = encrypted_logger.get_encryption_key()
    assert key == test_key


def test_get_encryption_key_none(monkeypatch) -> None:
    monkeypatch.delenv("LOG_ENCRYPTION_KEY", raising=False)
    monkeypatch.setattr(encrypted_logger.streamlit, "secrets", {}, raising=False)

    key = encrypted_logger.get_encryption_key()
    assert key is None


def test_encrypted_file_handler_and_decrypt(tmp_path: pathlib.Path) -> None:
    raw_key = cryptography.fernet.Fernet.generate_key()
    key_str = raw_key.decode("utf-8")
    log_file = tmp_path / "test.log"

    handler = encrypted_logger.EncryptedFileHandler(
        filename=log_file,
        key=key_str,
    )
    formatter = logging.Formatter("%(levelname)s: %(message)s")
    handler.setFormatter(formatter)

    test_logger = logging.getLogger("test_encrypted_handler")
    test_logger.setLevel(logging.INFO)
    test_logger.addHandler(handler)

    test_message = "This is a secret test log message."
    test_logger.info(test_message)
    handler.close()
    test_logger.removeHandler(handler)

    # 暗号化されていることを検証 (平文メッセージが含まれていない)
    raw_content = log_file.read_text(encoding="utf-8")
    assert test_message not in raw_content
    assert len(raw_content.strip()) > 0

    # 復号ユーティリティで検証
    decrypted_lines = encrypted_logger.decrypt_log_file(log_file, key_str)
    assert len(decrypted_lines) == 1
    assert decrypted_lines[0] == f"INFO: {test_message}"


def test_encrypted_file_handler_error_handling(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    raw_key = cryptography.fernet.Fernet.generate_key()
    log_file = tmp_path / "test_error.log"

    handler = encrypted_logger.EncryptedFileHandler(filename=log_file, key=raw_key)

    # emit中にエラーが発生した場合のハンドリング
    def mock_encrypt(data):
        raise RuntimeError("Encryption failed intentionally")

    monkeypatch.setattr(handler.fernet, "encrypt", mock_encrypt)

    error_called = False

    def mock_handle_error(record):
        nonlocal error_called
        error_called = True

    monkeypatch.setattr(handler, "handleError", mock_handle_error)

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="test",
        args=(),
        exc_info=None,
    )
    handler.emit(record)
    assert error_called is True
    handler.close()


def test_setup_encrypted_file_logging_success(tmp_path: pathlib.Path) -> None:
    raw_key = cryptography.fernet.Fernet.generate_key().decode("utf-8")
    log_file = tmp_path / "setup_test.log"

    test_logger = logging.getLogger("test_setup_logger")
    test_logger.setLevel(logging.INFO)
    test_logger.handlers.clear()

    formatter = logging.Formatter("%(message)s")
    handler = encrypted_logger.setup_encrypted_file_logging(
        logger=test_logger,
        log_path=log_file,
        key=raw_key,
        formatter=formatter,
    )
    assert handler is not None
    assert handler in test_logger.handlers

    # 重複追加の防止確認
    second_handler = encrypted_logger.setup_encrypted_file_logging(
        logger=test_logger,
        log_path=log_file,
        key=raw_key,
    )
    assert second_handler is handler
    assert len(test_logger.handlers) == 1

    test_logger.info("Encrypted via setup test")
    handler.close()
    test_logger.handlers.clear()

    decrypted = encrypted_logger.decrypt_log_file(log_file, raw_key)
    assert decrypted == ["Encrypted via setup test"]


def test_setup_encrypted_file_logging_no_key(monkeypatch) -> None:
    monkeypatch.delenv("LOG_ENCRYPTION_KEY", raising=False)
    monkeypatch.setattr(encrypted_logger.streamlit, "secrets", {}, raising=False)

    test_logger = logging.getLogger("test_no_key_logger")
    test_logger.handlers.clear()

    handler = encrypted_logger.setup_encrypted_file_logging(
        logger=test_logger,
        key=None,
    )
    assert handler is None
    assert len(test_logger.handlers) == 0


def test_setup_encrypted_file_logging_invalid_key(tmp_path: pathlib.Path) -> None:
    test_logger = logging.getLogger("test_invalid_key_logger")
    test_logger.handlers.clear()

    handler = encrypted_logger.setup_encrypted_file_logging(
        logger=test_logger,
        log_path=tmp_path / "invalid.log",
        key="not-a-valid-fernet-key",
    )
    assert handler is None
    assert len(test_logger.handlers) == 0


def test_decrypt_log_file_non_existent(tmp_path: pathlib.Path) -> None:
    raw_key = cryptography.fernet.Fernet.generate_key()
    non_existent = tmp_path / "does_not_exist.log"
    assert encrypted_logger.decrypt_log_file(non_existent, raw_key) == []


def test_encrypted_logger_constants() -> None:
    assert encrypted_logger.DEFAULT_MAX_BYTES == 32 * 1024 * 1024
    assert encrypted_logger.DEFAULT_BACKUP_COUNT == 8


def test_encrypted_file_handler_rotation(tmp_path: pathlib.Path) -> None:
    raw_key = cryptography.fernet.Fernet.generate_key().decode("utf-8")
    log_file = tmp_path / "rotating.log"

    # 小さなサイズでローテーションをテスト (backup_count=2)
    handler = encrypted_logger.EncryptedFileHandler(
        filename=log_file,
        key=raw_key,
        max_bytes=200,
        backup_count=2,
    )
    formatter = logging.Formatter("%(message)s")
    handler.setFormatter(formatter)

    test_logger = logging.getLogger("test_rotation_logger")
    test_logger.setLevel(logging.INFO)
    test_logger.handlers.clear()
    test_logger.addHandler(handler)

    messages = [f"Log message {i}" for i in range(10)]
    for msg in messages:
        test_logger.info(msg)

    handler.close()
    test_logger.handlers.clear()

    # ローテーションされたファイルが存在することを確認
    assert log_file.exists()
    assert (tmp_path / "rotating.log.1").exists()
    assert (tmp_path / "rotating.log.2").exists()
    assert not (tmp_path / "rotating.log.3").exists()

    all_decrypted = encrypted_logger.decrypt_all_log_files(log_file, raw_key)
    assert len(all_decrypted) > 0
    assert messages[-1] in all_decrypted


def test_decrypt_all_log_files_non_existent(tmp_path: pathlib.Path) -> None:
    raw_key = cryptography.fernet.Fernet.generate_key()
    non_existent = tmp_path / "non_existent_dir" / "does_not_exist.log"
    assert encrypted_logger.decrypt_all_log_files(non_existent, raw_key) == []
