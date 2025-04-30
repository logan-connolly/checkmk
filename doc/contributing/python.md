# python setup

This guide is focused on getting external contributors set up with Python and
its required dependencies to contribute to our Python code. Unlike the main
[contributing](../../CONTRIBUTING.md) page which is tailored towards _internal
development_ at Checkmk, this guide should get you set up to develop and check
your changes locally before submitting a PR.

> [!TIP]
> Scripts that you find under the `./scripts/contrib` directory are intended
> solely to aid external contributors. They should make little assumptions on
> your underlying operating system or development environment.

## requirements

The following packages are required for installation:

- [uv](https://docs.astral.sh/uv/getting-started/installation/): python package
  management.
- [postgresql](https://www.postgresql.org/download/): required to install the
  `psycopg2-binary` package.

## bootstrap

Now that the requirements are installed, you now need to run the bootstrapping
script:

```console
./scripts/contrib/bootstrap-python-env
```

This script will check if the requirements are installed, instantiate a virtual
environment (`.venv`), and install local & external libraries.

## activate

At this point, everything that is needed should be installed on your system and
in the virtual environment. To activate the environment, run:

```console
source .venv/bin/activate
```

To verify this, run `which python` in your shell. The output should point to the
`.venv/` directory in the `check_mk` repository.

## check changes

The goal of this guide is to allow you to check changes that you made locally
before submitting a pull request. Concretely, we'll assume that you made some
changes to the `gerrit` plugin and want to verify that the code is valid.

### testing

#### unit

You can test an entire package by running:

```console
pytest tests/unit/cmk/plugins/gerrit
```

You can also drill down to a single module from within the package with:

```console
pytest tests/unit/cmk/plugins/gerrit/lib/test_agent.py
```

Or drill down to individual tests with the `-k` flag:

```console
pytest tests/unit/cmk/plugins/gerrit/lib/test_agent.py -k test_fetch_sections_data
```

If you want to test the entire unit test suite in parallel, run:

```console
pytest --numprocesses=4 tests/unit
```

However, this may take awhile and cause unexpected failures on your machine.
It's better to let the CI handle these large scale checks.

#### integration

> [!NOTE]
> This section is still in development.

#### end-2-end

> [!NOTE]
> This section is still in development.

### lint and format

For linting and formatting Python code, we use [ruff](https://docs.astral.sh/ruff/).

To check for linting errors and fix them run:

```console
ruff check --fix cmk/plugins/gerrit tests/unit/cmk/plugins/gerrit
```

To make sure that the code is properly formatted run:

```console
ruff format cmk/plugins/gerrit tests/unit/cmk/plugins/gerrit
```

Unlike the unit tests, these checks are quite cheap. So, you could alternatively
run the checks on the entire repository with:

```console
ruff check --fix && ruff format
```

### type checking

We use [mypy](https://mypy-lang.org/) for type checking. It is not as quick as `ruff`, so we recommend to specify the package or module when invoking the check:

```console
mypy cmk/plugins/gerrit tests/unit/cmk/plugins/gerrit
```

### helper script

To make your life easier, we've provided a helper script that performs the checks from above on your local branch diff compared to `origin/master`:

```console
./scripts/contrib/validate-local-changes
```

The script assumes `origin` remote, but you can also specify it explicitly like
so:

```console
./scripts/contrib/validate-local-changes upstream/master
```

## wrap up

That's about all you need to get started with contributing to our Python code.
This guide is by no means all encompassing, but it should satisfy the majority
of our contributor's needs. If we can improve the guide in anyway, please send
us your feedback!
