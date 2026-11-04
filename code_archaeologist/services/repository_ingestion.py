"""Controlled repository acquisition. Repository code is never executed."""
import os
import shutil
import stat
import sys
import uuid
import zipfile
from io import BytesIO
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from flask import current_app
from git import GitCommandError, InvalidGitRepositoryError, Repo
from werkzeug.datastructures import FileStorage


class IngestionError(ValueError):
    """A safe, user-facing ingestion failure."""


def validate_github_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or parsed.hostname not in {"github.com", "www.github.com"}:
        raise IngestionError("Enter a public HTTPS GitHub repository URL.")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2 or not all(parts):
        raise IngestionError("Use a repository URL such as https://github.com/owner/repository.")
    return f"https://github.com/{parts[0]}/{parts[1].removesuffix('.git')}.git"


def _new_destination() -> Path:
    root = Path(current_app.config["REPOSITORY_STORAGE"])
    root.mkdir(parents=True, exist_ok=True)
    return root / uuid.uuid4().hex


def clone_public_repository(url: str) -> tuple[Path, str, bool]:
    clone_url = validate_github_url(url)
    destination = _new_destination()
    try:
        Repo.clone_from(
            clone_url, destination, depth=current_app.config["GIT_CLONE_DEPTH"], no_single_branch=True,
            env={"GIT_TERMINAL_PROMPT": "0"},
        )
    except (GitCommandError, OSError) as error:
        remove_tree(destination)
        raise IngestionError("The repository could not be cloned. Confirm that it is public and accessible.") from error
    _enforce_file_limit(destination)
    return destination, Path(urlparse(clone_url).path).stem, True


def extract_uploaded_archive(upload: FileStorage) -> tuple[Path, str, bool]:
    if not upload or not upload.filename or not upload.filename.lower().endswith(".zip"):
        raise IngestionError("Upload a ZIP file containing source code.")
    destination = _new_destination()
    destination.mkdir(parents=True, exist_ok=False)
    max_bytes = current_app.config["MAX_EXTRACTED_MB"] * 1024 * 1024
    max_files = current_app.config["MAX_REPOSITORY_FILES"]
    try:
        # Read into memory (already capped by MAX_CONTENT_LENGTH) so zipfile gets a seekable stream.
        with zipfile.ZipFile(BytesIO(upload.read())) as archive:
            members = [member for member in archive.infolist() if not member.is_dir()]
            if len(members) > max_files:
                raise IngestionError(f"The archive contains more than {max_files} files.")
            if sum(member.file_size for member in members) > max_bytes:
                raise IngestionError("The extracted archive would exceed the configured size limit.")
            for member in members:
                relative = PurePosixPath(member.filename)
                if relative.is_absolute() or ".." in relative.parts or not relative.parts:
                    raise IngestionError("The ZIP archive contains an unsafe file path.")
                # Unix symlinks are encoded in the upper file-mode bits; do not extract them.
                if (member.external_attr >> 16) & 0o170000 == 0o120000:
                    raise IngestionError("ZIP archives containing symbolic links are not supported.")
                target = destination.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
    except IngestionError:
        remove_tree(destination)
        raise
    except (zipfile.BadZipFile, OSError) as error:
        remove_tree(destination)
        if isinstance(error, IngestionError):
            raise
        raise IngestionError("The uploaded file is not a valid ZIP archive.") from error
    source_root = _unwrap_single_directory(destination)
    git_available = _has_usable_git_history(source_root)
    return source_root, Path(upload.filename).stem, git_available


def _unwrap_single_directory(root: Path) -> Path:
    children = [entry for entry in root.iterdir() if entry.name != "__MACOSX"]
    return children[0] if len(children) == 1 and children[0].is_dir() else root


def _has_usable_git_history(path: Path) -> bool:
    try:
        return not Repo(path, search_parent_directories=False).bare
    except InvalidGitRepositoryError:
        return False


def _enforce_file_limit(root: Path) -> None:
    file_count = sum(1 for path in root.rglob("*") if path.is_file() and ".git" not in path.parts)
    if file_count > current_app.config["MAX_REPOSITORY_FILES"]:
        remove_tree(root)
        raise IngestionError("The repository exceeds the configured file limit.")


def discard_repository(path: Path) -> None:
    """Remove a temporary checked-out/extracted repository after storing derived results."""
    storage = Path(current_app.config["REPOSITORY_STORAGE"]).resolve()
    try:
        relative = path.resolve().relative_to(storage)
    except ValueError:
        return
    if relative.parts:
        remove_tree(storage / relative.parts[0])


def remove_tree(path: Path) -> None:
    """Delete a temporary folder, including Git's read-only object files on Windows."""
    def make_writable_and_retry(function, target, _error):
        try:
            os.chmod(target, stat.S_IWRITE)
            function(target)
        except OSError:
            pass  # cleanup is best-effort; it must never break an analysis

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=make_writable_and_retry)
    else:
        shutil.rmtree(path, onerror=make_writable_and_retry)
