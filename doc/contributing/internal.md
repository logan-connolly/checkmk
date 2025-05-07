# Internal contributing

## Environment setup

We are developing Checkmk on **Ubuntu Linux** systems. We support these
versions:

* Current LTS
* Previous LTS
* Current non-LTS (If you want bleeding edge, then you get it. We won't support the previous non-LTS)

Anything that deviates from it can not be supported.

1. Install development dependencies

    Before you can start working on Checkmk, you will have to install some additional software, like tools for development and testing.
    Execute this in the project directory:

    ```console
    $ make setup
    ```

    > This is optimized for Ubuntu, but you may also get all the required programs on other platforms.

    After the dependencies have been installed, you could execute the shipped tests to ensure everything is working fine before start making changes to Checkmk.
    If you like to do this, please have a look at the [How to execute tests?](#how-to-execute-tests) chapter.

2. Install pre-commit checks

    In order to keep your commits to our standard we provide a [pre-commit](https://pre-commit.com/) configuration and some custom-made checking scripts.
    You can install it like this:

    > Warning: Python3 is required for pre-commit!
    > Installing it with Python 2 will break your environment and leave you unable to use pip due to a backports module clash!

    ```console
    $ pip3 install pre-commit
    ```

    After successful installation, hook it up to your git-repository by issuing the following command inside your git repository:

    ```console
    $ pre-commit install --allow-missing-config
    ```

    The `--allow-missing-config` parameter is needed so that branches of older versions of Checkmk which don't support this feature and are missing the configuration file won't throw errors.

    Afterwards your commits will automatically be checked for conformity by `pre-commit`.
    If you know a check (like mypy for example) would find an issue, but you don't want to fix it right away you can skip execution of the checkers with `git commit -n`.
    Please don't push unchecked changes as this will introduce delays and additional work.

    Additional helpers can be found in `scripts/`.
    One notable one is `scripts/check-current-commit` which checks your commit *after* it has been made.
    You can then fix errors and amend or squash your commit.
    You can also use this script in a rebase like such:

    ```console
    $ git rebase --exec scripts/check-current-commit
    ```

    This will rebase your current changes and check each commit for errors.
    After fixing them you can then continue rebasing.

Once done, you are ready for the next chapter.

## Executing tests

The public repository of [Checkmk](https://github.com/Checkmk/checkmk) is integrated with Github Actions CI.
Each time a Pull request is submitted, Github Actions will have a look at the changes.

**⚠ Important:** We only review PRs that are confirmed to be OK by Github Actions.
If a check failed, please fix it and update the PR.
PRs will be considered stale if the author didn't respond for at least 14 days.
It will be automatically closed after 60 days, if there is still no reply.

It is recommended to run all tests locally before submitting a PR.
If you want to execute the full test suite, you can do this by executing these commands in the project base directory:

```console
$ make -C tests test-ruff
$ make -C tests test-bandit
$ make -C tests test-unit
$ make -C tests test-format-python
$ make -C tests test-mypy-raw
```

> We highly recommend integrating ruff and mypy into the editor you work with.
> Most editors will notify you about issues the moment you edit the code.

You could also push your changes to your forked repository and wait for Github Actions to execute the tests for you, but that takes several minutes for each try.

### Code formatting

* We supply an `.editorconfig` file, which is used to automatically configure your editor to adhere to the most basic formatting style, like indents or line-lengths.
  If your editor doesn't already come with Editorconfig support, install [one of the available plugins](https://editorconfig.org/#download).
* We use [`ruff`](https://docs.astral.sh/ruff/) for automatic formatting of the Python code.
  Have a look [below](#automatic-formatting) for further information.
* We use also `ruff` for automatic sorting of imports in Python code.

### Automatic formatting/sorting with ruff

The `ruff` configuration file(s), `pyproject.toml`, live in the corresponding directories of the project repository, where `ruff` will pick it up automatically.
`ruff` itself lives in a virtualenv managed by bazel/uv in `check_mk/.venv`, you can run it with `make format-python`.

This make target will then format your code base as well as sort the import statements.

*NOTE*: You will also find other `pyproject.toml` files in our code base (at the time of writing, e.g. under `packges/cmk-*`).
Those are individual project settings for our own python packages and may differ from the top-level `pyproject.toml`.

#### Manual ruff formatting invocation: Single file

```console
$ ruff format [the_file.py]
```

#### Manual ruff linting invocation (also import sorting): Single file

```console
$ ruff check --fix [the_file.py]
```

#### Integration with CI

Our CI executes `ruff` formatting/sorting test on the whole code base:

```console
$ make -C tests test-format-python
```

Our review tests jobs prevent un-formatted code from being added to the repository.

#### Editor integration with ruff:

[Ruff editor integration](https://docs.astral.sh/ruff/editors/)

### Type checking: mypy

Code can be checked manually with `make -C tests test-mypy`.

The configuration file is `mypy.ini` and lives in the root directory of the Checkmk repository.
For info about how to type hint refer to [mypy docs - Type hints cheat sheet (Python 2)](https://mypy.readthedocs.io/en/latest/cheat_sheet.html#type-hints-cheat-sheet-python-2).
