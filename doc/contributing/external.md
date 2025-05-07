# External contributing

This guide is focused on getting external contributors easily set up with a
Python environment. It's optimized for minimizing the dependencies needed to
test, lint and verify code changes locally. The ultimate validation will be
performed in the CI using our infrastructure, but the hope is that this setup
will give you more confidence in your change before publishing a pull request
(PR) on GitHub.

> [!WARNING]
> This guide is intended for light Python development for external contributors
> who do not meet the system requirements to use our [internal](internal.md)
> contributing guide. There are no guarantees that this will work for all
> systems. See the [appendix](#appendix) for Linux distributions that we are
> actively trying to support.

## Environment setup

### requirements

All distributions need
[uv](https://docs.astral.sh/uv/getting-started/installation/) installed.

System dependency requirements for the following systems:

- [Debian based](#debian-based): Ubuntu, Debian, Mint, etc.
- [Red Hat based](#red-hat-based): Fedora, Red Hat, etc.

### bootstrap

Now run the [bootstrapping script](../../scripts/external/bootstrap-python-env):

```console
./scripts/external/bootstrap-python-env
```

This will initialize a virtual environment under `./.venv` and install
local & external Python dependencies.

### activate

At this point, everything that is needed should be installed on your system and
in the virtual environment. To activate the environment, run:

```console
source .venv/bin/activate
```

## Executing tests

The goal of this guide is to allow you to check changes that you made locally
before submitting a pull request. Concretely, we'll assume that you made some
changes to the `gerrit` plugin and now want to verify that the code is valid.

> [!WARNING]
> If you are making changes to a Python package under `./packages/*`, it's best
> practice to change into that directory and run the checks. That way you can be
> sure that you validating against the rules defined in that project's scope.

### unit tests

You can test an entire package by running:

```console
pytest tests/unit/cmk/plugins/gerrit
```

> [!TIP]
> If you are getting a `command not found: pytest` error, make sure that the
> environment is activated: `source .venv/bin/activate`

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

## wrap up

That's about all you need to get started with contributing to our Python code.
This guide is by no means all encompassing, but it should satisfy the majority
of our contributor's needs. If we can improve the guide in anyway, please send
us your feedback!

# Appendix

## Debian based

The following packages must be installed from `aptitude`:

- `build-essential`: required for building from source.
- `python3-dev`: required for building from source.
- `libldap-dev`: required by `python-ldap`
- `libsasl2-dev`: required by `python-ldap`
- `libkrb5-dev`: required by `python-active-directory`

Run:

```console
sudo apt install build-essential python3-dev libldap-dev libsasl2-dev libkrb5-dev
```

## Red Hat based

The following packages must be installed from `dnf`:

- `python3-devel`: required for building from source.
- `openldap-devel`: required by `python-ldap`
- `krb5-devel`: required by `python-active-directory`

Run:

```console
dnf group install development-tools
dnf install python3-devel openldap-devel krb5-devel
```
