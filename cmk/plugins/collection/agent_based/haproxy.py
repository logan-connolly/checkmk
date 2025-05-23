#!/usr/bin/env python3
# Copyright (C) 2019 Checkmk GmbH - License: GNU General Public License v2
# This file is part of Checkmk (https://checkmk.com). It is subject to the terms and
# conditions defined in the file COPYING, which is part of this source code package.

from collections.abc import Mapping
from enum import Enum
from time import time
from typing import Any, NamedTuple

from cmk.agent_based.v1 import check_levels as check_levels_v1
from cmk.agent_based.v2 import (
    AgentSection,
    CheckPlugin,
    CheckResult,
    DiscoveryResult,
    get_rate,
    get_value_store,
    render,
    Result,
    Service,
    State,
    StringTable,
)


class HAProxyFrontendStatus(Enum):
    OPEN = "OPEN"
    STOP = "STOP"


class HAProxyServerStatus(Enum):
    """
    https://www.haproxy.com/documentation/haproxy-configuration-manual/2-5r1/management/

    Notes:
        * MAINT (resolution) and MAINT (via) are listed explicitly as states in the linked
        documentation, therefore including them in the enum instead of treating them as a partial
        status.
    """

    UP = "UP"
    DOWN = "DOWN"
    NOLB = "NOLB"
    MAINT = "MAINT"
    MAINT_RES = "MAINT (resolution)"
    MAINT_VIA = "MAINT (via)"
    DRAIN = "DRAIN"
    NO_CHECK = "no check"


class Frontend(NamedTuple):
    status: str
    stot: int | None


class Server(NamedTuple):
    status: str
    layer_check: str
    uptime: int | None
    active: int | None
    backup: int | None


class Section(NamedTuple):
    frontends: dict[str, Frontend]
    servers: dict[str, Server]


def parse_int(val):
    try:
        return int(val)
    except ValueError:
        return None


def status_result(status: str, params: Mapping[str, Any]) -> CheckResult:
    """
    Yield the proper Result based on the available statuses in the params.
    State.WARN if status not in params.
    """
    if status in params:
        yield Result(state=State(params[status]), summary=f"Status: {status}")
    else:
        # covers partial statuses like DOWN 1/2
        yield Result(
            state=State.WARN,
            summary=f"Status: {status}",
        )


def parse_haproxy(string_table: StringTable) -> Section:
    frontends = {}
    servers = {}
    for line in string_table:
        if len(line) <= 32 or line[32] not in ("0", "2"):
            continue

        status = line[17]

        if line[32] == "0":
            name = line[0]
            try:
                stot = int(line[7])
            except ValueError:
                continue
            frontends[name] = Frontend(status=status, stot=stot)

        elif line[32] == "2":
            name = f"{line[0]}/{line[1]}"
            layer_check = line[36]
            uptime = parse_int(line[23])
            active = parse_int(line[19])
            backup = parse_int(line[20])

            servers[name] = Server(
                status=status, layer_check=layer_check, uptime=uptime, active=active, backup=backup
            )

    return Section(frontends=frontends, servers=servers)


agent_section_haproxy = AgentSection(
    name="haproxy",
    parse_function=parse_haproxy,
)


def discover_haproxy_frontend(section: Section) -> DiscoveryResult:
    for key in section.frontends.keys():
        yield Service(item=key)


def check_haproxy_frontend(item: str, params: Mapping[str, Any], section: Section) -> CheckResult:
    data = section.frontends.get(item)
    if data is None:
        return

    status = data.status
    yield from status_result(status, params)

    stot = data.stot
    if stot is not None:
        value_store = get_value_store()
        session_rate = get_rate(value_store, f"sessions.{item}", time(), stot)
        yield from check_levels_v1(
            value=session_rate, metric_name="session_rate", label="Session Rate"
        )


check_plugin_haproxy_frontend = CheckPlugin(
    name="haproxy_frontend",
    sections=["haproxy"],
    service_name="HAProxy Frontend %s",
    discovery_function=discover_haproxy_frontend,
    check_function=check_haproxy_frontend,
    check_ruleset_name="haproxy_frontend",
    check_default_parameters={
        HAProxyFrontendStatus.OPEN.value: State.OK.value,
        HAProxyFrontendStatus.STOP.value: State.CRIT.value,
    },
)


def discover_haproxy_server(section: Section) -> DiscoveryResult:
    for key in section.servers.keys():
        yield Service(item=key)


def check_haproxy_server(item: str, params: Mapping[str, Any], section: Section) -> CheckResult:
    data = section.servers.get(item)
    if data is None:
        return

    status = data.status
    yield from status_result(status, params)

    if data.active:
        yield Result(state=State.OK, summary="Active")
    elif data.backup:
        yield Result(state=State.OK, summary="Backup")
    else:
        yield Result(state=State.CRIT, summary="Neither active nor backup")

    yield Result(state=State.OK, summary=f"Layer Check: {data.layer_check}")

    uptime = data.uptime
    if uptime is not None:
        yield Result(state=State.OK, summary=f"Up since {render.timespan(uptime)}")


check_plugin_haproxy_server = CheckPlugin(
    name="haproxy_server",
    sections=["haproxy"],
    service_name="HAProxy Server %s",
    discovery_function=discover_haproxy_server,
    check_function=check_haproxy_server,
    check_ruleset_name="haproxy_server",
    check_default_parameters={
        HAProxyServerStatus.UP.value: State.OK.value,
        HAProxyServerStatus.DOWN.value: State.CRIT.value,
        HAProxyServerStatus.NOLB.value: State.CRIT.value,
        HAProxyServerStatus.MAINT.value: State.CRIT.value,
        HAProxyServerStatus.MAINT_VIA.value: State.WARN.value,
        HAProxyServerStatus.MAINT_RES.value: State.WARN.value,
        HAProxyServerStatus.DRAIN.value: State.CRIT.value,
        HAProxyServerStatus.NO_CHECK.value: State.CRIT.value,
    },
)
