# Contribution: Integration Tests

This directory hosts a collection of integration tests which verify if we can
install the Python dependencies on different distributions. It is **not**
intended to be integrated into our CI, but rather used as an investigation tool
to see why someone may be having issues following our
[external contribution guide](../../doc/contributing/external.md).

## support

There are currently checks for the following distributions:

- [ubuntu](./check-ubuntu)
- [debian](./check-debian)
- [fedora](./check-fedora)

## usage

Imagine a ticket gets opened, saying that someone couldn't install the Python
`python-active-directory` dependency. We can then ask them what operating system
they are using (imagine they respond with `Debian 12`). Using the debian check, you
could investigate the issue by running:

```console
./tests/contribution/check-debian 12
```

Which will:

- build a test image based on Debian 12 with `uv` installed.
- install defined system dependencies, i.e.`python3-dev`, `build-essential`, etc.
- initialize a virtual environment with our current Python version.
- try and install the Python dependencies defined in our `requirements.txt`.

After running the script, you find an error complaining about some C library
that's not installed. You search online, and discover that in order to install
`python-active-directory` on debian, `libkrb5-dev` also needs to be installed.

We can then verify it by adding it to the `check-debian` script and
rerun. Now that we know the cause of the issue, we can promptly respond to the
issuer with a solution, and improve the contributing guideline to let future
Debian users know that they need to have `libkrb5-dev` installed.

## tag argument

From the example above we passed the docker tag as a positional argument (`12`).
However, you can also trigger the scripts with no tag argument:

```console
./tests/contribution/check-debian
```

This will pull down the latest available image to run the test.

This can be a nice tool to catch issues early before bumping versions.

## extensibility

The `Docker` + `check-<distro>` pattern is extensible as many popular linux
distributions provide public base images like _Alpine_, _Arch_, or _NixOS_. So
if in the future we want to provide sanity checks for additional distributions,
simply follow the existing pattern.
