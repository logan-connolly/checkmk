#!/usr/bin/env python3
# Copyright (C) 2019 Checkmk GmbH - License: GNU General Public License v2
# This file is part of Checkmk (https://checkmk.com). It is subject to the terms and
# conditions defined in the file COPYING, which is part of this source code package.

# <<<graylog_nodes>>>
# {"a56db164-78a6-4dc8-bec9-418b9edf9067": {"inputstates": {"message_input":
# {"node": "a56db164-78a6-4dc8-bec9-418b9edf9067", "name": "Syslog TCP",
# "title": "syslog test", "created_at": "2019-09-30T07:11:19.932Z", "global":
# false, "content_pack": null, "attributes": {"tls_key_file": "", "tls_enable":
# false, "store_full_message": false, "tcp_keepalive": false,
# "tls_key_password": "", "tls_cert_file": "", "allow_override_date": true,
# "recv_buffer_size": 1048576, "port": 514, "max_message_size": 2097152,
# "number_worker_threads": 8, "bind_address": "0.0.0.0",
# "expand_structured_data": false, "tls_client_auth_cert_file": "",
# "tls_client_auth": "disabled", "use_null_delimiter": false, "force_rdns":
# false, "override_source": null}, "creator_user_id": "admin", "static_fields":
# {}, "type": "org.graylog2.inputs.syslog.tcp.SyslogTCPInput", "id":
# "5d91aa97dedfc2061e233e86"}, "state": "FAILED", "started_at":
# "2019-09-30T07:11:20.720Z", "detailed_message": "bind(..) failed: Keine
# Berechtigung.", "id": "5d91aa97dedfc2061e233e86"}, "lb_status": "alive",
# "operating_system": "Linux 4.15.0-1056-oem", "version": "3.1.2+9e96b08",
# "facility": "graylog-server", "hostname": "klappclub", "node_id":
# "a56db164-78a6-4dc8-bec9-418b9edf9067", "cluster_id":
# "d19bbcf9-9aaf-4812-a829-ba7cc4672ac9", "timezone": "Europe/Berlin",
# "codename": "Quantum Dog", "started_at": "2019-09-30T05:53:17.699Z",
# "lifecycle": "running", "is_processing": true}}


# mypy: disable-error-code="var-annotated"

import json

from cmk.agent_based.legacy.v0_unstable import check_levels, LegacyCheckDefinition

check_info = {}


def parse_graylog_nodes(string_table):
    parsed = {}

    for line in string_table:
        node_details = json.loads(line[0])

        for node, detail in node_details.items():
            try:
                parsed.setdefault(node, []).append(detail)
            except KeyError:
                pass

    return parsed


def inventory_graylog_nodes(parsed):
    for node in parsed:
        yield node, {}


def check_graylog_nodes(item, params, parsed):
    if parsed is None:
        return

    if item not in parsed:
        yield 2, "Missing in agent output (graylog service running?)"
        return

    for node_name, details in parsed.items():
        if item != node_name:
            continue

        for node_info in details:
            for key, infotext, levels in [
                ("lb_status", "Load balancer state", "lb_"),
                ("lifecycle", "Lifecycle is", "lc_"),
                ("is_processing", "Is processing", "ps_"),
            ]:
                value = node_info.get(key)
                if value is None:
                    continue

                state = params.get(f"{levels}{str(value).lower()}", 1)

                yield (
                    state,
                    "{}: {}".format(
                        infotext,
                        str(value).replace("True", "yes").replace("False", "no"),
                    ),
                )

            long_output = []
            value_inputstates = node_info.get("inputstates")
            if value_inputstates is None:
                continue

            for inputstate in value_inputstates:
                long_output_str = ""

                value_input_message = inputstate.get("message_input")
                if value_input_message is not None:
                    value_name = value_input_message.get("name")
                    if value_name is not None:
                        long_output_str += "Name: %s, " % value_name

                    value_title = value_input_message.get("title")
                    if value_title is not None:
                        long_output_str += "Title: %s, " % value_title.title()

                value_input_state = inputstate.get("state")
                if value_input_state is not None:
                    state_of_input = 0
                    if value_input_state != "RUNNING":
                        state_of_input = params["input_state"]
                    long_output_str += "Status: %s" % value_input_state

                long_output.append((state_of_input, long_output_str))

        input_nr_levels = params.get("input_count_upper", (None, None))
        input_nr_levels_lower = params.get("input_count_lower", (None, None))
        yield check_levels(
            len(value_inputstates),
            "num_input",
            input_nr_levels + input_nr_levels_lower,
            human_readable_func=int,
            infoname="Inputs",
        )

        max_state = 0
        if long_output:
            long_output_info = ""
            max_state = max(state for state, _infotext in long_output)
            if max_state:
                long_output_info += "One or more inputs not in state running, "

            long_output_info += "see long output for more details"

            yield max_state, long_output_info

            for state, line in sorted(long_output):
                yield state, "\n%s" % line


check_info["graylog_nodes"] = LegacyCheckDefinition(
    name="graylog_nodes",
    parse_function=parse_graylog_nodes,
    service_name="Graylog Node %s",
    discovery_function=inventory_graylog_nodes,
    check_function=check_graylog_nodes,
    check_ruleset_name="graylog_nodes",
    check_default_parameters={
        "lb_throttled": 2,
        "lb_alive": 0,
        "lb_dead": 2,
        "lc_uninitialized": 1,
        "lc_paused": 1,
        "lc_running": 0,
        "lc_failed": 2,
        "lc_halting": 1,
        "lc_throttled": 2,
        "lc_starting": 1,
        "lc_override_lb_alive": 0,
        "lc_override_lb_dead": 1,
        "lc_override_lb_throttled": 1,
        "ps_true": 0,
        "ps_false": 2,
        "input_state": 1,
    },
)
