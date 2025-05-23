#!/usr/bin/env python3
# Copyright (C) 2021 Checkmk GmbH - License: GNU General Public License v2
# This file is part of Checkmk (https://checkmk.com). It is subject to the terms and
# conditions defined in the file COPYING, which is part of this source code package.
import hashlib
import warnings
from collections.abc import Callable, Sequence
from typing import Any, cast, ClassVar

import apispec
from apispec import APISpec
from pydantic import TypeAdapter
from pydantic.json_schema import GenerateJsonSchema, JsonSchemaValue
from pydantic_core import core_schema, PydanticSerializationError

from cmk.gui.openapi.framework.model.omitted import ApiOmitted


def _get_json_schema(spec: APISpec, adapter: TypeAdapter) -> dict[str, object]:
    json_schema = adapter.json_schema(
        by_alias=True,
        ref_template="#/components/schemas/{model}",
        schema_generator=CheckmkGenerateJsonSchema,
        mode="serialization",
    )

    # The schema names must be unique, otherwise an error will be raised on registration. This is
    # good, because we don't want to have references to the wrong schema elsewhere. The solution
    # should be to rename the classes so that they are unique, not to suppress the error.
    # It is possible that a (different) plugin modifies the schema after registration, which would
    # cause the newly generated schema to be different from the one that was registered. This
    # shouldn't be a problem from a spec perspective, but would mean we somehow need to know that
    # they came from the same type adapter.

    if defs := json_schema.pop("$defs", None):
        assert isinstance(defs, dict)
        for k, v in defs.items():
            if spec.components.schemas.get(k) == v:
                continue
            spec.components.schema(k, v)

    name = json_schema.get("title")
    assert isinstance(name, str)
    if spec.components.schemas.get(name) != json_schema:
        spec.components.schema(name, json_schema)

    return json_schema


class CheckmkGenerateJsonSchema(GenerateJsonSchema):
    """Customized JSON schema generator.

    In order to generate the correct schema, we need to:
     * mark fields as optional if they contain `ApiOmitted` as an option
     * update default handling, by:
       * supporting `default_factory`
       * handling `ApiOmitted` as a default value
    """

    def _contains_omitted(self, schema: core_schema.CoreSchema) -> bool:
        match schema["type"]:
            case "is-instance":
                return schema["cls"] is ApiOmitted
            case "default" | "nullable":
                return self._contains_omitted(schema["schema"])
            case "union":
                return any(self._contains_omitted(inner) for inner in schema["choices"])
            case "tagged-union":
                return any(self._contains_omitted(inner) for inner in schema["choices"].values())

        return False

    def field_is_required(
        self,
        field: core_schema.ModelField | core_schema.DataclassField | core_schema.TypedDictField,
        total: bool,
    ) -> bool:
        if self._contains_omitted(field["schema"]):
            if field["schema"]["type"] != "default":
                # This only really matters for inputs, but there is no way to know for what this
                # will be used. So we just forbid it completely.
                raise ValueError(f"Omittable field without default value: {field}")

            return False

        return super().field_is_required(field, total)

    def default_schema(self, schema: core_schema.WithDefaultSchema) -> JsonSchemaValue:
        """Generates a JSON schema that matches a schema with a default value.

        This is mostly copied from the base class, changes are marked with comments."""
        json_schema = self.generate_inner(schema["schema"])

        # changed: we also check default_factory
        if "default" in schema:
            default = schema["default"]
        elif "default_factory" in schema:
            if schema.get("default_factory_takes_data"):
                default = cast(Callable[[dict[str, Any]], Any], schema["default_factory"])({})
            else:
                default = cast(Callable[[], Any], schema["default_factory"])()
        else:
            return json_schema

        # changed: we return early if the default is ApiOmitted, as it cannot be serialized
        if isinstance(default, ApiOmitted):
            return json_schema

        # we reflect the application of custom plain, no-info serializers to defaults for
        # JSON Schemas viewed in serialization mode:
        if (
            self.mode == "serialization"
            and (ser_schema := schema["schema"].get("serialization"))
            and (ser_func := ser_schema.get("function"))
            and ser_schema.get("type") == "function-plain"
            and not ser_schema.get("info_arg")
            and not (
                default is None
                and ser_schema.get("when_used") in ("unless-none", "json-unless-none")
            )
        ):
            try:
                default = ser_func(default)
            except Exception:
                # It might be that the provided default needs to be validated (read: parsed) first
                # (assuming `validate_default` is enabled). However, we can't perform
                # such validation during JSON Schema generation so we don't support
                # this pattern for now.
                # (One example is when using `foo: ByteSize = '1MB'`, which validates and
                # serializes as an int. In this case, `ser_func` is `int` and `int('1MB')` fails).
                self.emit_warning(
                    "non-serializable-default",
                    f"Unable to serialize value {default!r} with the plain serializer; excluding default from JSON schema",
                )
                return json_schema

        try:
            encoded_default = self.encode_default(default)
        except PydanticSerializationError:
            self.emit_warning(
                "non-serializable-default",
                f"Default value {default} is not JSON serializable; excluding default from JSON schema",
            )
            # Return the inner schema, as though there was no default
            return json_schema

        json_schema["default"] = encoded_default
        return json_schema


class CheckmkPydanticResolver:
    """SchemaResolver is responsible for modifying a schema.

    This class relies heavily on the fact that dictionaries are mutable,
    so rather than catching a return value, we can often modify the object without
    a return statement.
    """

    # TypeAdapter id -> (schema_name, schema)
    refs: ClassVar[dict[int, tuple[str, dict[str, object]]]] = {}

    def __init__(self, spec: apispec.APISpec) -> None:
        self.spec = spec

    def resolve_nested_schema(self, maybe_adapter: TypeAdapter | object) -> object:
        if isinstance(maybe_adapter, TypeAdapter):
            schema_name, _ = self.get_cached_adapter_schema(adapter=maybe_adapter)
            return {"$ref": f"#/components/schemas/{schema_name}"}

        # do not touch other cases, as they should in most cases be Marshmallow schemas
        return maybe_adapter

    def get_cached_adapter_schema(self, adapter: TypeAdapter) -> tuple[str, dict[str, object]]:
        key = id(adapter)
        if key not in self.refs:
            json_schema = _get_json_schema(self.spec, adapter)
            if "title" in json_schema:
                title = json_schema["title"]
                assert isinstance(title, str)
                schema_name = title
            else:
                sha = hashlib.sha256()
                sha.update(str(json_schema).encode("utf-8"))
                schema_name = sha.hexdigest()
                warnings.warn("Pydantic plugin got schema without title, using hash of schema")

            self.refs[key] = schema_name, json_schema

        return self.refs[key]

    def resolve_schema(self, data: dict[str, Any] | Any) -> None:
        """Resolves a Pydantic model in an OpenAPI component or header.

        This method modifies the input dictionary, data, to translate
        Pydantic models to OpenAPI schema objects or reference objects.

        Args:
            data (Any): _description_
        """
        if not isinstance(data, dict):
            return

        # OAS 2 component or OAS 3 parameter or header
        if "schema" in data:
            data["schema"] = self.resolve_schema_dict(data["schema"])

        # OAS 3 component except header
        if self.spec.openapi_version.major >= 3 and "content" in data:
            for content in data["content"].values():
                if "schema" in content:
                    content["schema"] = self.resolve_schema_dict(content["schema"])

    def resolve_operations(
        self,
        operations: dict[str, object] | None,
        **kwargs: Any,
    ) -> None:
        """Resolves an operations dictionary into an OpenAPI operations object.

        https://spec.openapis.org/oas/v3.1.0#operation-object

        Args:
            operations (dict[str, Any] | None): The operations for a specific route,
                if documented.

                Example:
                {
                    'get': {
                        'description': 'Create a network quiet time announcement',
                        'tags': ['Announcements'],
                        'requestBody': {
                            'description': 'The details of the Network Quiet Time',
                            'content': {
                                'application/json': {
                                    'schema': 'CreateNetworkQuietTimeRequest'
                                }
                            }
                        },
                        'responses': {
                            '200': {
                                'description': 'Announcement successfully created.',
                                'content': {
                                    'application/json': {
                                        'schema': 'SerializedAnnouncement'
                                    }
                                }
                            },
                            '400': {
                                'description': 'An invalid request was received.',
                                'content': {'application/json': { 'schema': 'Problem'}}
                            },
                            '403': {
                                'description': 'The user was not authorized to perform this action.',
                                'content': {'application/json': {'schema': 'Problem'}}
                            },
                            '500': {
                                'description': 'An unexpected error occurred while retrieving the announcements',
                                'content': {'application/json': {'schema': 'Problem'}}
                            }
                        }
                    }
                }
        """
        if operations is None:
            return

        for operation in operations.values():
            if not isinstance(operation, dict):
                continue

            if "parameters" in operation:
                operation["parameters"] = self.resolve_parameters(operation["parameters"])
            if self.spec.openapi_version.major >= 3:
                self.resolve_callback(operation.get("callbacks", {}))
                if "requestBody" in operation:
                    self.resolve_schema(operation["requestBody"])
            for response in operation.get("responses", {}).values():
                self.resolve_response(response)

    def resolve_parameters(
        self, parameters: Sequence[dict[str, object]]
    ) -> Sequence[dict[str, object]]:
        for parameter in parameters:
            if "schema" in parameter:
                schema = parameter["schema"]
                if isinstance(schema, TypeAdapter):
                    _, parameter["schema"] = self.get_cached_adapter_schema(schema)

            # TODO: might need to do this, when we remove the marshmallow plugin
            #       but while we still have marshmallow this might break the plugin
            # wrap object parameters in content.application/json to keep them as str/json in swagger
            # see: https://swagger.io/docs/specification/describing-parameters/#schema-vs-content
            # if "type" not in parameter["schema"]:
            #     content = parameter.setdefault("content", {}).setdefault("application/json", {})
            #     content["schema"] = parameter.pop("schema")

        return parameters

    def resolve_callback(self, callbacks: Any) -> None:
        for callback in callbacks.values():
            if isinstance(callback, dict):
                for path in callback.values():
                    self.resolve_operations(path)

    def resolve_response(self, response: Any) -> None:
        self.resolve_schema(response)
        if "headers" in response:
            for header in response["headers"].values():
                self.resolve_schema(header)

    def resolve_schema_dict(self, schema: dict | TypeAdapter | object) -> object:
        """Resolve the schemas and ignore anything which is not related to the Pydantic plugin
        such as Marshmallow schemas, etc.
        """
        if not isinstance(schema, dict):
            return self.resolve_nested_schema(schema)

        if schema.get("type") == "array" and "items" in schema:
            schema["items"] = self.resolve_schema_dict(schema["items"])
        if schema.get("type") == "object" and "properties" in schema:
            schema["properties"] = {
                k: self.resolve_schema_dict(v) for k, v in schema["properties"].items()
            }
        for keyword in ("oneOf", "anyOf", "allOf"):
            if keyword in schema:
                schema[keyword] = [self.resolve_schema_dict(s) for s in schema[keyword]]
        if "not" in schema:
            schema["not"] = self.resolve_schema_dict(schema["not"])
        return schema


class CheckmkPydanticPlugin(apispec.BasePlugin):
    """APISpec plugin for translating pydantic models to OpenAPI/JSONSchema format."""

    spec: apispec.APISpec | None
    resolver: CheckmkPydanticResolver | None

    def __init__(self) -> None:
        self.spec = None
        self.resolver = None

    def init_spec(self, spec: apispec.APISpec) -> None:
        """Initialize plugin with APISpec object

        Args:
            spec: APISpec object this plugin instance is attached to
        """
        super().init_spec(spec=spec)
        self.spec = spec
        self.resolver = CheckmkPydanticResolver(spec=self.spec)

    def operation_helper(
        self,
        path: str | None = None,
        operations: dict[str, object] | None = None,
        **kwargs: Any,
    ) -> None:
        if self.resolver is None:
            raise ValueError("SchemaResolver was not initialized")
        self.resolver.resolve_operations(operations=operations, kwargs=kwargs)
