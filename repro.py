#!/usr/bin/env python3
import logging
import re
import sys
import tempfile
from pathlib import Path
import subprocess
from typing import TYPE_CHECKING, Mapping
import json
from enum import IntEnum

import yaml
from git import Repo, exc

if TYPE_CHECKING:
    from os import PathLike
    from typing import Any, Sequence, TextIO, TypeVar, Union

    _KT = TypeVar("_KT")  # Key type.
    _VT = TypeVar("_VT")  # Value type.


DOCKERFILE_TEMPLATE = """
{basefile}

WORKDIR /app

COPY . .
RUN {postcreatecommand}

CMD {command}
"""


class FormatMsgType(IntEnum):
    OK = 0
    WARN = 1
    ERROR = 2


_fmt = FormatMsgType


def fmt_message(message: str, level: _fmt) -> str:
    """
    Prints a formatted log message with a symbol indicating the status.

    Parameters:
    - message (str): The log message to display.
    - level (_fmt): The level of the message; can be _fmt.OK, _fmt.WARN, _fmt.ERROR.
    """
    symbols = {
        _fmt.OK: "\033[92m\u2713\033[0m",  # Green check mark
        _fmt.WARN: "\033[93m" + b"\xe2\x9a\xa0".decode("utf-8") + "\033[0m",  # Yellow warning
        _fmt.ERROR: "\033[91m" + b"\xe2\x9c\x96".decode("utf-8") + "\033[0m",  # Red cross
    }

    symbol = symbols[level]
    return f"{symbol} {message}"


def log_message(message: str, level: _fmt):
    """
    Prints a formatted log message with a symbol indicating the status.

    Parameters:
    - message (str): The log message to display.
    - level (_fmt): The level of the message; can be _fmt.OK, _fmt.WARN, _fmt.ERROR.
    """
    print(fmt_message(message, level))

def __get_nested(
    d: "Mapping[_KT, Union[dict, _VT]]", keys: "Sequence[_KT]"
) -> "Union[Mapping[_KT, Union[dict, _VT]], _VT]":
    """Recursively retrieves a value from a nested mapping using a list of keys.

    Args:
        d (Mapping[_KT, Union[dict, _VT]]): The dictionary to traverse.
        keys (list[_KT]): A list of keys representing the path to the desired value.

    Raises:
        TypeError: If an intermediate value in the path is not a mapping.
        KeyError: If any key in the path is not found in the corresponding mapping.

    Returns:
        The value located at the nested key path.
    """
    out: "Union[Mapping[_KT, Union[dict, _VT]], _VT]" = d
    for i, key in enumerate(keys):
        if not isinstance(out, Mapping):
            raise LookupError(
                f"The value at {'>'.join(map(str, keys[:i]))} is not a mapping")
        if key not in out:
            raise KeyError(
                f"The key {'>'.join(map(str, keys[:i+1]))} could not be found")
        out = out[key]
    return out


def __load_metadata(metadata: "TextIO") -> "dict[str, Any]":
    try:
        data = yaml.safe_load(metadata)
        log_message("Input is a correctly formatted YAML file", FormatMsgType.OK)
        return data
    except yaml.YAMLError as e:
        log_message(f"Failed to parse the input file: {e}", FormatMsgType.OK)
        logging.critical(
            "The input file is not formatted correctly", exc_info=e)
        sys.exit(1)


def __download_code(metadata: "dict[str, Any]", dest: "PathLike") -> Repo:
    # Find out where I can get the code from
    try:
        repository = __get_nested(
            metadata, ("implementation", "source", "repository"))
        commit = __get_nested(metadata, ("implementation", "source", "commit"))
        assert isinstance(repository, str)
        assert isinstance(commit, str)
        log_message(f"Repository is at {repository}#{commit}", FormatMsgType.OK)
    except LookupError as e:
        log_message(f"Failed to locate the code from the metadata: {e}", FormatMsgType.ERROR)
        logging.critical(
            "Vital information is not present in the metadata", exc_info=e)
        sys.exit(2)

    # Download the code
    candidates = [repository]
    if (match := re.match(r"([^@]*)@([A-Za-z0-9.-]+):(.*)", repository)) is not None:
        candidates.append(f"https://{match[2]}/{match[3]}")
        log_message(
            f"Repository URL seems to use ssh. I will additionally try cloning via https: {candidates[-1]}",
            FormatMsgType.WARN,
        )

    for url in candidates:
        try:
            repo = Repo.clone_from(url, to_path=dest)
            log_message(f"Cloned into the repository from {url}", FormatMsgType.OK)
            repo.git.checkout(commit)
            log_message(f"Checked out commit {commit}", FormatMsgType.OK)
            break
        except exc.GitError:
            log_message(f"Failed to clone from {url}", FormatMsgType.WARN)
    else:
        log_message("Failed to clone repository", FormatMsgType.ERROR)
        logging.critical(f"Failed to clone repository from {repository} and checkout {commit}")
        sys.exit(3)
    return repo


def __configure_docker_container(metadata: "dict[str, Any]", dest: Path) -> None:
    # Search for an existing Docker configuration
    # TODO: implement
    log_message(
        "No docker configuration found; I will create one from the metadata...", FormatMsgType.WARN)
    # Construct a Docker Container
    try:
        # TODO: load image
        image = "mcr.microsoft.com/devcontainers/python:2-3.14-trixie"
        basefile = """FROM --platform=linux/amd64 mcr.microsoft.com/devcontainers/python:2-3.14-trixie

# Need for docker-in-docker
RUN <<EOF
# The one inside the image seems to be deprecated
curl -fsSL https://dl.yarnpkg.com/debian/pubkey.gpg | gpg --dearmor | sudo tee /usr/share/keyrings/yarn-archive-keyring.gpg > /dev/null
EOF

RUN apt-get update && apt-get install -y openjdk-21-jdk"""
        # TODO: load post-create command
        postcreatecommand = "pip3 install --user -r requirements.txt"
        cmd = __get_nested(metadata, ("implementation", "executable", "cmd"))
        # packages = __get_nested(metadata, ("implementation", "python", "packages"))
        dockerfile = DOCKERFILE_TEMPLATE.format_map({
            # "dependencies": "\n".join(packages)
            "basefile": basefile or f"FROM {image}",
            "postcreatecommand": postcreatecommand,
            "command": json.dumps(cmd),
        })
        (dest / "Dockerfile").write_text(dockerfile)
        log_message("Created a docker file", FormatMsgType.OK)
    except LookupError as e:
        log_message(
            f"Failed to construct a dockerfile from the metadata: {e}", FormatMsgType.ERROR)
        logging.critical(
            "Vital information is not present in the metadata", exc_info=e)
        sys.exit(4)


def __run_experiment(metadata: "dict[str, Any]", directory: "Path") -> None:
    # Find out what script to run
    try:
        cmd = __get_nested(metadata, ("implementation", "executable", "cmd"))
        assert isinstance(cmd, list) and all(isinstance(e, str) for e in cmd)
        log_message(f"Running {cmd}", FormatMsgType.OK)
    except KeyError as e:
        log_message(
            f"Failed to find the command that ran the experiments: {e}", FormatMsgType.ERROR)
        logging.critical(
            "Vital information is not present in the metadata", exc_info=e)
        sys.exit(4)
    # Run the script
    # Build the docker image
    network_access: bool = True
    subprocess.run(["docker", "build", "-t", "repro-experiment", str(directory)], check=True)
    # Run the docker image
    docker_args = ["--rm"]
    if not network_access:
        docker_cmd.extend(("--network", "none"))
    subprocess.run(["docker", *docker_args, "repro-experiment"], check=True)


# TODO: add optional --out path
def reproduce_command(metadata: "TextIO", **kwargs) -> int:
    data = __load_metadata(metadata)
    with tempfile.TemporaryDirectory() as tmpdir:
        log_message(
            f"Switched working directory to {tmpdir}", FormatMsgType.OK)
        with __download_code(data, Path(tmpdir)) as _:
            __configure_docker_container(data, Path(tmpdir))
            __run_experiment(data, Path(tmpdir))
    # Each subroutine will sys.exit() with their individual error code upon error such that exit values other than 0 are
    # still possible
    return 0


def main(outdir: Path) -> int:
    # TODO implement
    # This function reads the irmetadata from outdir / "irmetadata.yaml" (you can find an example in ./out/irmetadata.yaml)
    # and does the following:
    with (outdir / "irmetadata.yaml").open() as f:
        reproduce_command(f)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Illegal number of arguments, exactly one expected")
        exit(1)
    exit(main(Path(sys.argv[1])))
