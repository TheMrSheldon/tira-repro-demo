#!/usr/bin/env python3
from __future__ import annotations

import abc
import re
import json
import enum
from typing import Iterable

from rich.markdown import Markdown
from rich.console import Console
from rich.table import Table
from tirex_tracker import fetch_info, Measure


class Result(enum.IntEnum):
    SUCCESS = enum.auto()
    FAIL = enum.auto()


Hint = tuple[str, str] | None
SubCheckResult = tuple[str, Hint, str, Result]
CheckResult = tuple[list[SubCheckResult], Result]


NO_HINT_NEEDED: Hint = None


class Check(abc.ABC):
    """
    Abstract base class for performing checks with subchecks.

    This class defines the interface for a check that can be decomposed into multiple subchecks. Each check has a name
    and produces a result indicating overall success or failure based on all its subchecks.
    """

    def name(self) -> str:
        """Returns the name of the check."""
        ...

    def subchecks(self) -> Iterable[SubCheckResult]:
        ...

    def __call__(self) -> CheckResult:
        """
        Executes all subchecks and returns a tuple containing:
        - A list of all subcheck results
        - A boolean indicating if all subchecks succeeded

        Returns True only if all subchecks have succeeded.
        """
        results = list(self.subchecks())
        return results, all(result == Result.SUCCESS for _, _, _, result in results)


GIT_REPO_HINT: Hint = (
    "Use Git", "Run `git init` from your code's directory to initialize a git repository.")
UNCOMMITTED_CHANGES_HINT: Hint = (
    "Commit all changes",
    "Some of your files contain changes that are not yet committed. You can list these files using `git status`. If "
    "one of those files should not be committed (e.g., because it is created by the program and should not be checked "
    "in into the repository), then add it to your `.gitignore` file."
)


class GitCheck(Check):
    def name(self) -> str:
        return "Git Repository"

    def subchecks(self) -> Iterable[SubCheckResult]:
        gitinfo = fetch_info(measures=[
            Measure.GIT_IS_REPO,
            Measure.GIT_LAST_COMMIT_HASH,
            Measure.GIT_BRANCH,
            Measure.GIT_BRANCH_UPSTREAM,
            Measure.GIT_TAGS,
            Measure.GIT_REMOTE_ORIGIN,
            Measure.GIT_UNCOMMITTED_CHANGES,
            Measure.GIT_UNPUSHED_CHANGES,
            Measure.GIT_UNCHECKED_FILES,
            Measure.GIT_ROOT,
            Measure.GIT_ARCHIVE_PATH,
        ])
        isrepo = (gitinfo[Measure.GIT_IS_REPO].value == b"1")
        msg = gitinfo[Measure.GIT_ROOT].value.decode(
        ) if isrepo else "Not a git repository"
        yield "Repository", GIT_REPO_HINT, msg, Result.SUCCESS if isrepo else Result.FAIL
        if not isrepo:
            return

        remote_origin = gitinfo[Measure.GIT_REMOTE_ORIGIN].value.decode()
        yield "Remote origin", ("TODO", "<TODO: hint>"), remote_origin, (Result.SUCCESS if remote_origin else Result.FAIL)

        branch_local = gitinfo[Measure.GIT_BRANCH].value.decode() or "detached"
        branch_remote = gitinfo[Measure.GIT_BRANCH_UPSTREAM].value.decode(
        ) or "detached"
        yield "Branch", NO_HINT_NEEDED, f"{branch_local} (local) -> {branch_remote} (remote)", Result.SUCCESS

        commit = gitinfo[Measure.GIT_LAST_COMMIT_HASH].value.decode()
        yield "Commit", NO_HINT_NEEDED, commit, Result.SUCCESS

        uncommitted_changes = int(
            gitinfo[Measure.GIT_UNCOMMITTED_CHANGES].value.decode())
        msg = f"{uncommitted_changes} files with changes have not been committed or ignored by the .gitignore" if uncommitted_changes else "No uncommitted changes"
        yield "Uncommitted changes", UNCOMMITTED_CHANGES_HINT, msg, (Result.SUCCESS if uncommitted_changes == 0 else Result.FAIL)

        unpushed_changes = int(
            gitinfo[Measure.GIT_UNPUSHED_CHANGES].value.decode())
        yield "Unpushed changes", ("TODO", "<TODO: hint>"), unpushed_changes or "Every commit that you have locally is also pushed", (Result.SUCCESS if unpushed_changes == 0 else Result.FAIL)


CONFIGURE_DEV_CONTAINER_HINT: Hint = (
    "Configure and use a dev container",
    "For VSCode follow: [underline]https://code.visualstudio.com/docs/devcontainers/create-dev-container[/underline]\n"
    "For PyCharm: [underline]https://www.jetbrains.com/help/pycharm/connect-to-devcontainer.html[/underline]\n"
    "General information: [underline]https://containers.dev/[/underline]"
)


class DevContainerCheck(Check):
    def name(self) -> str:
        return "Dev Container Configuration"

    def subchecks(self) -> Iterable[SubCheckResult]:
        info = fetch_info(measures=[Measure.DEVCONTAINER_CONF_PATHS])
        devconfigs: list[str] = json.loads(
            info[Measure.DEVCONTAINER_CONF_PATHS].value)

        if not devconfigs:
            yield "Find Dev Container Configuration", CONFIGURE_DEV_CONTAINER_HINT, "", Result.FAIL
            return

        config_path = devconfigs[0]
        details = [f"Configuration file: {config_path}"]

        with open(config_path, "r") as f:
            content = f.read()

        # Remove JSONC comments (lines starting with //)
        content = re.sub(r'//.*?$', '', content, flags=re.MULTILINE)
        # Remove trailing commas (not valid JSON)
        content = re.sub(r',(\s*[}\]])', r'\1', content)

        config: dict = json.loads(content)

        name = config.get("name", "unnamed")
        details.append(f"Container name: {name}")

        image = config.get("image")
        dockerfile = build.get("dockerfile") if (
            build := config.get("build")) else None
        if not image and not dockerfile:
            yield "Base image or Dockerfile", ("TODO", "<TODO: hint>"), "", Result.FAIL
        else:
            if image:
                yield "Base image", NO_HINT_NEEDED, image or "<not set>", Result.SUCCESS
            if dockerfile:
                yield "Dockerfile", NO_HINT_NEEDED, dockerfile or "<not set>", Result.SUCCESS

        post_create = config.get("postCreateCommand")
        yield "Post-create command", NO_HINT_NEEDED, post_create or "<not set>", Result.SUCCESS


def main() -> int:
    console = Console(record=True)
    hints: list[tuple[str, str]] = []
    for check in (GitCheck(), DevContainerCheck()):
        subchecks, status = check()
        status = "[[green]PASS[/green]]" if status == Result.SUCCESS else "[[red]FAIL[/red]]"
        dots = "·" * (console.width-7-len(check.name())-2)
        console.print(
            f"[bold]{check.name()}[/bold] [dim]{dots}[/dim] {status} ")
        for name, hint, value, substatus in subchecks:
            statmsg = "[green]✓[/green]" if substatus == Result.SUCCESS else "[red]✗[/red]"
            console.print(
                f"  {statmsg} {name:<25} [italic][dim]{value}[/dim][/italic]")
            if substatus != Result.SUCCESS and hint is not NO_HINT_NEEDED:
                hints.append(hint)
    if hints == []:
        console.print("\n[green]All good. Nothing left to do![/green]")
        return 0
    console.print(f"\n[bold][red]{len(hints)} actionable item(s)[/red][/bold]")

    table = Table(show_header=False, show_lines=False,
                  box=None, pad_edge=False)
    table.add_column("", style="bold", no_wrap=True)
    table.add_column("", style="dim", overflow="fold")

    for title, description in hints:
        table.add_row(title, Markdown(description))
    console.print(table)
    console.save_svg("./screenshot.svg", title="repro-check.py")
    return 1


if __name__ == "__main__":
    exit(main())
