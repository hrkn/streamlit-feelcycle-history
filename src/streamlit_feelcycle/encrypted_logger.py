import logging
import logging.handlers
import os
import pathlib
import tempfile

import cryptography.fernet
import streamlit
import streamlit.errors

LOGGER = logging.getLogger(__name__)

DEFAULT_LOG_FILENAME = "feelcycle-history_encrypted.log"
DEFAULT_MAX_BYTES = 32 * 1024 * 1024  # 32MB
DEFAULT_BACKUP_COUNT = 8  # 最大8個


def get_default_log_path() -> pathlib.Path:
    """Return the default path to the encrypted log file in the OS temporary directory."""
    return pathlib.Path(tempfile.gettempdir()) / DEFAULT_LOG_FILENAME


def get_encryption_key() -> str | None:
    """Retrieve the encryption key from Streamlit Secrets or environment variables."""
    key = None
    try:
        if hasattr(streamlit, "secrets") and "LOG_ENCRYPTION_KEY" in streamlit.secrets:
            key = str(streamlit.secrets["LOG_ENCRYPTION_KEY"])
    except (
        streamlit.errors.StreamlitAPIException,
        KeyError,
        FileNotFoundError,
        AttributeError,
    ):
        key = None

    if not key:
        key = os.environ.get("LOG_ENCRYPTION_KEY")

    if key:
        key = key.strip()
    return key if key else None


class EncryptedFileHandler(logging.handlers.RotatingFileHandler):
    """A rotating logging handler that encrypts log records line-by-line using Fernet."""

    def __init__(
        self,
        filename: str | os.PathLike[str],
        key: bytes | str,
        max_bytes: int = DEFAULT_MAX_BYTES,
        backup_count: int = DEFAULT_BACKUP_COUNT,
        encoding: str = "utf-8",
        mode: str = "a",
    ) -> None:
        if isinstance(key, str):
            key = key.encode("utf-8")
        self.fernet = cryptography.fernet.Fernet(key)
        self.log_encoding = encoding
        super().__init__(
            filename=filename,
            mode=mode,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
            delay=False,
        )

    def should_rollover_with_line(self, line: str) -> bool:
        """Check if writing the line will exceed maxBytes."""
        if self.stream is None:
            self.stream = self._open()
        if self.maxBytes > 0:
            self.stream.seek(0, 2)
            if self.stream.tell() + len(line.encode("ascii")) >= self.maxBytes:
                return True
        return False

    def emit(self, record: logging.LogRecord) -> None:
        """Format, encrypt, and write a log record to the file with rotation."""
        try:
            msg = self.format(record)
            encrypted_token = self.fernet.encrypt(msg.encode(self.log_encoding))
            line = encrypted_token.decode("ascii") + "\n"

            if self.should_rollover_with_line(line):
                self.doRollover()

            self.stream.write(line)
            self.flush()
        except Exception:  # noqa: BLE001
            self.handleError(record)


EncryptedRotatingFileHandler = EncryptedFileHandler


def decrypt_log_file(
    file_path: str | os.PathLike[str],
    key: bytes | str,
    encoding: str = "utf-8",
) -> list[str]:
    """Decrypt an encrypted log file and return decrypted log lines."""
    if isinstance(key, str):
        key = key.encode("utf-8")
    fernet = cryptography.fernet.Fernet(key)
    path = pathlib.Path(file_path)
    if not path.exists():
        return []

    decrypted_lines: list[str] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            decrypted = fernet.decrypt(stripped.encode("ascii")).decode(encoding)
            decrypted_lines.append(decrypted)
    return decrypted_lines


def decrypt_all_log_files(
    base_path: str | os.PathLike[str],
    key: bytes | str,
    encoding: str = "utf-8",
) -> list[str]:
    """Decrypt all rotated log files in chronological order from oldest to newest."""
    path = pathlib.Path(base_path)
    parent = path.parent
    name = path.name

    candidate_files: list[tuple[int, pathlib.Path]] = []
    if path.exists():
        candidate_files.append((0, path))

    if parent.exists():
        for p in parent.glob(f"{name}.*"):
            suffix = p.name[len(name) + 1 :]
            if suffix.isdigit():
                candidate_files.append((int(suffix), p))

    # Older backups have higher numbers, current file is 0
    candidate_files.sort(key=lambda x: x[0], reverse=True)

    all_lines: list[str] = []
    for _, file_path in candidate_files:
        all_lines.extend(decrypt_log_file(file_path, key, encoding=encoding))
    return all_lines


def setup_encrypted_file_logging(
    logger: logging.Logger | None = None,
    log_path: pathlib.Path | None = None,
    key: str | None = None,
    formatter: logging.Formatter | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
) -> EncryptedFileHandler | None:
    """Configure encrypted file logging to OS temporary directory with rotation if key is valid."""
    target_logger = logger if logger is not None else logging.getLogger()

    # Prevent duplicate handlers on Streamlit script reruns
    for handler in target_logger.handlers:
        if isinstance(handler, EncryptedFileHandler):
            return handler

    target_key = key if key is not None else get_encryption_key()
    if not target_key:
        target_logger.warning(
            "LOG_ENCRYPTION_KEY is not set. Encrypted file logging to temporary directory is skipped."
        )
        return None

    try:
        target_path = log_path if log_path is not None else get_default_log_path()
        handler = EncryptedFileHandler(
            filename=target_path,
            key=target_key,
            max_bytes=max_bytes,
            backup_count=backup_count,
        )
        if formatter is not None:
            handler.setFormatter(formatter)
        target_logger.addHandler(handler)
        return handler
    except (ValueError, TypeError, OSError) as exc:
        target_logger.warning(
            f"Failed to initialize encrypted file logging: {exc}. Output to file is skipped."
        )
        return None
