#!/usr/bin/env python3
# Copyright (C) 2020 Checkmk GmbH - License: GNU General Public License v2
# This file is part of Checkmk (https://checkmk.com). It is subject to the terms and
# conditions defined in the file COPYING, which is part of this source code package.

from __future__ import annotations

import ast
import os
import pickle
import time
from multiprocessing.pool import Pool
from pathlib import Path
from typing import TypedDict

import psutil
from redis import Redis

from cmk.ccc import store
from cmk.ccc.exceptions import MKGeneralException
from cmk.ccc.i18n import _

from cmk.utils.log import logger
from cmk.utils.paths import default_config_dir
from cmk.utils.redis import get_redis_client

from cmk.bi.aggregation import BIAggregation
from cmk.bi.data_fetcher import BIStructureFetcher, get_cache_dir, SiteProgramStart
from cmk.bi.lib import SitesCallback
from cmk.bi.packs import BIAggregationPacks
from cmk.bi.searcher import BISearcher
from cmk.bi.trees import BICompiledAggregation, BICompiledRule, FrozenBIInfo
from cmk.bi.type_defs import frozen_aggregations_dir

_LOGGER = logger.getChild("web.bi.compilation")
_MAX_MULTIPROCESSING_POOL_SIZE = 8
_AVAILABLE_MEMORY_RATIO = 0.75


class ConfigStatus(TypedDict):
    configfile_timestamp: float
    known_sites: set[SiteProgramStart]
    online_sites: set[SiteProgramStart]


path_compiled_aggregations = Path(get_cache_dir(), "compiled_aggregations")


class BICompiler:
    def __init__(self, bi_configuration_file: str, sites_callback: SitesCallback) -> None:
        self._sites_callback = sites_callback
        self._bi_configuration_file = bi_configuration_file

        self._compiled_aggregations: dict[str, BICompiledAggregation] = {}
        self._path_compilation_lock = Path(get_cache_dir(), "compilation.LOCK")
        self._path_compilation_timestamp = Path(get_cache_dir(), "last_compilation")
        path_compiled_aggregations.mkdir(parents=True, exist_ok=True)

        self._redis_client: Redis[str] | None = None

        self._bi_packs = BIAggregationPacks(self._bi_configuration_file)
        self._bi_structure_fetcher = BIStructureFetcher(self._sites_callback)
        self.bi_searcher = BISearcher()

    @property
    def compiled_aggregations(self) -> dict[str, BICompiledAggregation]:
        return self._compiled_aggregations

    def get_aggregation_by_name(
        self, aggr_name: str
    ) -> tuple[BICompiledAggregation, BICompiledRule] | None:
        for _name, compiled_aggregation in self._compiled_aggregations.items():
            for branch in compiled_aggregation.branches:
                if branch.properties.title == aggr_name:
                    return compiled_aggregation, branch
        return None

    def load_compiled_aggregations(self) -> None:
        try:
            self._check_compilation_status()
        finally:
            self._load_compiled_aggregations()

    def get_frozen_aggr_id(self, frozen_info: FrozenBIInfo) -> str:
        return f"frozen_{frozen_info.based_on_aggregation_id}_{frozen_info.based_on_branch_title}"

    def _frozen_branch_file(self, branch_name: str) -> Path:
        return frozen_aggregations_dir / branch_name

    def _frozen_aggr_hint_path(self, aggr_id: str) -> Path:
        return frozen_aggregations_dir / f"origin_hints_{aggr_id}"

    def _freeze_new_branches(self, compiled_aggregation: BICompiledAggregation) -> bool:
        new_branch_found = False
        for branch in list(compiled_aggregation.branches):
            if self._frozen_branch_file(branch.properties.title).exists():
                continue
            new_branch_found = True
            self.freeze_branch(branch.properties.title)
        return new_branch_found

    def freeze_branch(self, branch_name: str) -> None:
        # Creates a frozen aggregation in the frozen_aggregations_dir
        # And an additional hint-file in an aggregation sub-folder, so that we know
        # where the frozen aggregation branch initially came from

        result = self.get_aggregation_by_name(aggr_name=branch_name)
        if not result:
            raise MKGeneralException(f"Unknown aggregation {branch_name}")
        aggregation, branch = result

        # Prepare a single frozen configuration specifically for this branch
        # This includes the aggregation configuration and the frozen branch
        if frozen_info := aggregation.frozen_info:
            aggr_id = frozen_info.based_on_aggregation_id
        else:
            aggr_id = aggregation.id

        aggr_hint_path = self._frozen_aggr_hint_path(aggr_id)
        aggr_hint_path.mkdir(exist_ok=True, parents=True)
        (aggr_hint_path / branch_name).touch()

        original_branches = aggregation.branches
        original_id = aggregation.id
        try:
            aggregation.branches = [branch]
            aggregation.id = self.get_frozen_aggr_id(FrozenBIInfo(aggr_id, branch_name))
            store.save_object_to_file(
                self._frozen_branch_file(branch_name), aggregation.serialize()
            )
        finally:
            aggregation.branches = original_branches
            aggregation.id = original_id

    def _unfreeze_all_branches(self, aggr_id: str) -> None:
        aggr_hint_path = self._frozen_aggr_hint_path(aggr_id)
        if not aggr_hint_path.exists():
            return
        for filename in aggr_hint_path.iterdir():
            filename.unlink(missing_ok=True)
            branch_file = frozen_aggregations_dir / filename.name
            branch_file.unlink(missing_ok=True)

        aggr_hint_path.rmdir()

    def _manage_frozen_branches(
        self, compiled_aggregations: dict[str, BICompiledAggregation]
    ) -> dict[str, BICompiledAggregation]:
        updated_aggregations = {}

        frozen_aggregations_dir.mkdir(exist_ok=True)
        computed_new_frozen_branch = False
        for aggr_id, compiled_aggregation in compiled_aggregations.items():
            updated_aggregations[aggr_id] = compiled_aggregation
            if compiled_aggregation.frozen_info is not None:
                # Already frozen
                continue

            if not compiled_aggregation.computation_options.freeze_aggregations:
                self._unfreeze_all_branches(aggr_id)
                continue

            computed_new_frozen_branch = (
                self._freeze_new_branches(compiled_aggregation) or computed_new_frozen_branch
            )
            frozen_branch_names = set(os.listdir(frozen_aggregations_dir))

            # Read frozen branches. Each branch gets a separate aggregation ID since
            # the computation time may differ, which also means possibly changed computation options
            for branch in list(compiled_aggregation.branches):
                if branch.properties.title in frozen_branch_names:
                    frozen_aggregation = BIAggregation.create_trees_from_schema(
                        ast.literal_eval(
                            (frozen_aggregations_dir / branch.properties.title).read_text()
                        )
                    )
                    frozen_aggregation.frozen_info = FrozenBIInfo(
                        compiled_aggregation.id, branch.properties.title
                    )
                    updated_aggregations[
                        self.get_frozen_aggr_id(frozen_aggregation.frozen_info)
                    ] = frozen_aggregation

            # Remove all branches from the original aggregation, since all of them are now frozen
            compiled_aggregation.branches = []

        if computed_new_frozen_branch:
            self._generate_part_of_aggregation_lookup(updated_aggregations)

        return updated_aggregations

    def _load_compiled_aggregations(self) -> None:
        for path_object in path_compiled_aggregations.iterdir():
            if path_object.is_dir():
                continue
            aggr_id = path_object.name
            if aggr_id.endswith(".new") or aggr_id in self._compiled_aggregations:
                continue

            _LOGGER.debug("Loading %s aggregation from cache.", aggr_id)
            if not (data := store.load_object_from_pickle_file(path_object, default={})):
                _LOGGER.warning("Unable to load compiled aggregation from: %s", path_object)
                continue
            self._compiled_aggregations[aggr_id] = BIAggregation.create_trees_from_schema(data)

        self._compiled_aggregations = self._manage_frozen_branches(self._compiled_aggregations)

    def _check_compilation_status(self) -> None:
        current_configstatus = self.compute_current_configstatus()
        if not self._compilation_required(current_configstatus):
            _LOGGER.debug("No compilation required.")
            return

        with store.locked(self._path_compilation_lock):
            # Re-check compilation required after lock has been required
            # Another apache might have done the job
            current_configstatus = self.compute_current_configstatus()
            if not self._compilation_required(current_configstatus):
                _LOGGER.debug("No compilation required. Another process already compiled it.")
                return

            self.prepare_for_compilation(current_configstatus["online_sites"])

            if aggregations := self._bi_packs.get_all_aggregations():
                with self._get_multiprocessing_pool(len(aggregations)) as pool:
                    compiled_aggregations = pool.imap_unordered(_process_compilation, aggregations)
                    for compiled_aggregation in compiled_aggregations:
                        self._compiled_aggregations[compiled_aggregation.id] = compiled_aggregation

            self._verify_aggregation_title_uniqueness(self._compiled_aggregations)

            for compiled_aggregation in self._compiled_aggregations.values():
                self._store_compiled_aggregation(compiled_aggregation)

            self._compiled_aggregations = self._manage_frozen_branches(self._compiled_aggregations)
            self._generate_part_of_aggregation_lookup(self._compiled_aggregations)

        known_sites = {kv[0]: kv[1] for kv in current_configstatus.get("known_sites", set())}
        self._cleanup_vanished_aggregations()
        self._bi_structure_fetcher.cleanup_orphaned_files(known_sites)
        store.save_text_to_file(
            str(self._path_compilation_timestamp), str(current_configstatus["configfile_timestamp"])
        )

    def _get_multiprocessing_pool(self, aggregation_count: int) -> Pool:
        # HACK: due to known constraints with multiprocessing in Python, this is a simple way to
        # "inject" the BI searcher dependency to our separate processes. An alternative approach
        # would be to move this object to a global variable. However, we prefer the attribute based
        # approach on the process function as it better encapsulates the logic. The underlying issue
        # has to do with the implicit pickling of all objects in process function which is slow and
        # sometimes fails when the object isn't "pickleable".
        def initializer(function) -> None:  # type: ignore[no-untyped-def]
            function.searcher = self.bi_searcher

        return Pool(
            processes=_get_multiprocessing_pool_size(aggregation_count),
            initializer=initializer,
            initargs=(_process_compilation,),
        )

    def _store_compiled_aggregation(self, compiled_aggregation: BICompiledAggregation) -> None:
        start = time.perf_counter()
        compiled_aggregation_path = path_compiled_aggregations / compiled_aggregation.id
        self._save_data(compiled_aggregation_path, compiled_aggregation.serialize())
        end = time.perf_counter()
        _LOGGER.debug(
            "Schema dump of %s (%d branches) took: %fs"
            % (compiled_aggregation.id, len(compiled_aggregation.branches), end - start)
        )

    def _cleanup_vanished_aggregations(self) -> None:
        valid_aggregations = self._compiled_aggregations.keys()
        for path_object in path_compiled_aggregations.iterdir():
            if path_object.is_dir():
                continue
            if path_object.name not in valid_aggregations:
                path_object.unlink(missing_ok=True)
                self._unfreeze_all_branches(path_object.name)

    def _verify_aggregation_title_uniqueness(
        self, compiled_aggregations: dict[str, BICompiledAggregation]
    ) -> None:
        used_titles: dict[str, str] = {}
        for aggr_id, bi_aggregation in compiled_aggregations.items():
            for bi_branch in bi_aggregation.branches:
                branch_title = bi_branch.properties.title
                if branch_title in used_titles:
                    raise MKGeneralException(
                        _(
                            'The aggregation titles are not unique. "%s" is created '
                            "by aggregation <b>%s</b> and <b>%s</b>"
                        )
                        % (branch_title, aggr_id, used_titles[branch_title])
                    )
                used_titles[branch_title] = aggr_id

    def prepare_for_compilation(self, online_sites: set[SiteProgramStart]) -> None:
        self._bi_packs.load_config()
        self._bi_structure_fetcher.update_data(online_sites)
        self.bi_searcher.set_hosts(self._bi_structure_fetcher.hosts)

    def compile_aggregation_result(self, aggr_id: str, title: str) -> BICompiledAggregation | None:
        """Allows to compile a single aggregation with a given title. Does not save any results to disk"""
        current_configstatus = self.compute_current_configstatus()
        self.prepare_for_compilation(current_configstatus["online_sites"])
        aggregation = self._bi_packs.get_aggregation(aggr_id)
        if not aggregation:
            return None

        try:
            aggregation.node.restrict_rule_title = title
            return aggregation.compile(self.bi_searcher)
        finally:
            aggregation.node.restrict_rule_title = None

    def _compilation_required(self, current_configstatus: ConfigStatus) -> bool:
        # Check monitoring core changes
        if self._site_status_changed(current_configstatus["online_sites"]):
            return True

        # Check BI configuration changes
        return current_configstatus["configfile_timestamp"] > self._get_compilation_timestamp()

    def _get_compilation_timestamp(self) -> float:
        compilation_timestamp = 0.0
        try:
            # I prefer Path.read_text
            # The corresponding cmk.ccc.store has some "this function needs to die!" comment
            if self._path_compilation_timestamp.exists():
                compilation_timestamp = float(self._path_compilation_timestamp.read_text())
        except (FileNotFoundError, ValueError) as e:
            _LOGGER.warning("Unable to determine compilation timestamp. Error: %s", str(e))
        return compilation_timestamp

    def _site_status_changed(self, required_program_starts: set[SiteProgramStart]) -> bool:
        # The cached data may include more data than the currently required_program_starts
        # Empty branches are simply not shown during computation
        cached_program_starts = self._bi_structure_fetcher.get_cached_program_starts()
        return len(required_program_starts - cached_program_starts) > 0

    def compute_current_configstatus(self) -> ConfigStatus:
        current_configstatus: ConfigStatus = {
            "configfile_timestamp": self._get_last_configuration_change(),
            "online_sites": set(),
            "known_sites": set(),
        }

        # The get status message also checks if the remote site is still alive
        result = self._sites_callback.query("GET status\nColumns: program_start\nCache: reload")
        program_start_times = {row[0]: int(row[1]) for row in result}

        for site_id, site_is_online in self._sites_callback.all_sites_with_id_and_online():
            start_time = program_start_times.get(site_id, 0)
            current_configstatus["known_sites"].add((site_id, start_time))
            if site_is_online:
                current_configstatus["online_sites"].add((site_id, start_time))

        return current_configstatus

    def _get_last_configuration_change(self) -> float:
        conf_dir = f"{default_config_dir}/multisite.d"
        latest_timestamp = 0.0
        wato_config = Path(conf_dir, "wato", self._bi_configuration_file)
        if wato_config.exists():
            latest_timestamp = max(latest_timestamp, wato_config.stat().st_mtime)

        for path_object in Path(conf_dir).iterdir():
            if path_object.is_dir():
                continue
            latest_timestamp = max(latest_timestamp, path_object.stat().st_mtime)

        return latest_timestamp

    def _save_data(self, filepath: Path, data: dict) -> None:
        store.save_bytes_to_file(filepath, pickle.dumps(data))

    def _get_redis_client(self) -> Redis[str]:
        if self._redis_client is None:
            self._redis_client = get_redis_client()
        return self._redis_client

    def is_part_of_aggregation(self, host_name: str, service_description: str) -> bool:
        self._check_redis_lookup_integrity()
        return bool(
            self._get_redis_client().exists(
                f"bi:aggregation_lookup:{host_name}:{service_description}"
            )
        )

    def _check_redis_lookup_integrity(self):
        client = self._get_redis_client()
        if client.exists("bi:aggregation_lookup"):
            return True

        # The following scenario only happens if the redis daemon loses its data
        # In the normal workflow the lookup cache is updated after the compilation phase
        # What happens if multiple apache process want to read the cache at the same time:
        # - One apache gets the lock, updates the cache
        # - The other apache wait till the cache has been updated
        lookup_lock = client.lock("bi:aggregation_lookup_lock")
        try:
            lookup_lock.acquire()
            if not client.exists("bi:aggregation_lookup"):
                self.load_compiled_aggregations()
                self._generate_part_of_aggregation_lookup(self._compiled_aggregations)
            return None
        finally:
            if lookup_lock.owned():
                lookup_lock.release()

    def _generate_part_of_aggregation_lookup(self, compiled_aggregations):
        part_of_aggregation_map: dict[str, list[str]] = {}
        for aggr_id, compiled_aggregation in compiled_aggregations.items():
            for branch in compiled_aggregation.branches:
                for _site, host_name, service_description in branch.required_elements():
                    # This information can be used to selectively load the relevant compiled
                    # aggregation for any host/service. Right now it is only an indicator if this
                    # host/service is part of an aggregation
                    key = f"bi:aggregation_lookup:{host_name}:{service_description}"
                    part_of_aggregation_map.setdefault(key, []).append(
                        f"{aggr_id}\t{branch.properties.title}"
                    )

        client = self._get_redis_client()

        # The main task here is to add/update/remove keys without causing other processes
        # to wait for the updated data. There is no tempfile -> live mechanism.
        # Updates are done on the live data via pipeline, using transactions.

        # Fetch existing keys
        existing_keys = set(client.scan_iter("bi:aggregation_lookup:*"))

        # Update keys
        pipeline = client.pipeline()
        for key, values in part_of_aggregation_map.items():
            pipeline.sadd(key, *values)
        pipeline.set("bi:aggregation_lookup", "1")

        if obsolete_keys := existing_keys - set(part_of_aggregation_map.keys()):
            pipeline.delete(*obsolete_keys)

        pipeline.execute()


def _get_multiprocessing_pool_size(aggregation_count: int) -> int:
    current_process = psutil.Process(os.getpid())

    available_memory = _AVAILABLE_MEMORY_RATIO * psutil.virtual_memory().available
    current_process_memory = current_process.memory_info().rss
    potential_pool_size = int(available_memory // current_process_memory)

    return min(potential_pool_size, _MAX_MULTIPROCESSING_POOL_SIZE, aggregation_count)


def _process_compilation(aggregation: BIAggregation) -> BICompiledAggregation:
    start = time.perf_counter()
    compiled_aggregation = aggregation.compile(_process_compilation.searcher)  # type: ignore[attr-defined]
    end = time.perf_counter()
    _LOGGER.debug("Compilation of %s took: %fs", aggregation.id, end - start)
    return compiled_aggregation
