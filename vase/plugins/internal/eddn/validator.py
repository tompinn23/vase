from enum import IntEnum
from importlib.resources import read_binary

import xxjson
from jsonschema import FormatChecker, validate, ValidationError, Validator

from . import schema

EDDN_SCHEMAS: dict[str, str] = {
    "https://eddn.edcd.io/schemas/commodity/3": "commodity-v3.0.json",
    "https://eddn.edcd.io/schemas/commodity/3/test": "commodity-v3.0.json",
    "https://eddn.edcd.io/schemas/shipyard/2": "shipyard-v2.0.json",
    "https://eddn.edcd.io/schemas/shipyard/2/test": "shipyard-v2.0.json",
    "https://eddn.edcd.io/schemas/outfitting/2": "outfitting-v2.0.json",
    "https://eddn.edcd.io/schemas/outfitting/2/test": "outfitting-v2.0.json",
    "https://eddn.edcd.io/schemas/blackmarket/1": "blackmarket-v1.0.json",
    "https://eddn.edcd.io/schemas/blackmarket/1/test": "blackmarket-v1.0.json",
    "https://eddn.edcd.io/schemas/journal/1": "journal-v1.0.json",
    "https://eddn.edcd.io/schemas/journal/1/test": "journal-v1.0.json",
    "https://eddn.edcd.io/schemas/scanbarycentre/1": "scanbarycentre-v1.0.json",
    "https://eddn.edcd.io/schemas/scanbarycentre/1/test": "scanbarycentre-v1.0.json",
    "https://eddn.edcd.io/schemas/fssdiscoveryscan/1": "fssdiscoveryscan-v1.0.json",
    "https://eddn.edcd.io/schemas/fssdiscoveryscan/1/test": "fssdiscoveryscan-v1.0.json",
    "https://eddn.edcd.io/schemas/codexentry/1": "codexentry-v1.0.json",
    "https://eddn.edcd.io/schemas/codexentry/1/test": "codexentry-v1.0.json",
    "https://eddn.edcd.io/schemas/navbeaconscan/1": "navbeaconscan-v1.0.json",
    "https://eddn.edcd.io/schemas/navbeaconscan/1/test": "navbeaconscan-v1.0.json",
    "https://eddn.edcd.io/schemas/navroute/1": "navroute-v1.0.json",
    "https://eddn.edcd.io/schemas/navroute/1/test": "navroute-v1.0.json",
    "https://eddn.edcd.io/schemas/approachsettlement/1": "approachsettlement-v1.0.json",
    "https://eddn.edcd.io/schemas/approachsettlement/1/test": "approachsettlement-v1.0.json",
    "https://eddn.edcd.io/schemas/fssallbodiesfound/1": "fssallbodiesfound-v1.0.json",
    "https://eddn.edcd.io/schemas/fssallbodiesfound/1/test": "fssallbodiesfound-v1.0.json",
    "https://eddn.edcd.io/schemas/fssbodysignals/1": "fssbodysignals-v1.0.json",
    "https://eddn.edcd.io/schemas/fssbodysignals/1/test": "fssbodysignals-v1.0.json",
    "https://eddn.edcd.io/schemas/fsssignaldiscovered/1": "fsssignaldiscovered-v1.0.json",
    "https://eddn.edcd.io/schemas/fsssignaldiscovered/1/test": "fsssignaldiscovered-v1.0.json",
    "https://eddn.edcd.io/schemas/fcmaterials_journal/1": "fcmaterials_journal-v1.0.json",
    "https://eddn.edcd.io/schemas/fcmaterials_journal/1/test": "fcmaterials_journal-v1.0.json",
    "https://eddn.edcd.io/schemas/fcmaterials_capi/1": "fcmaterials_capi-v1.0.json",
    "https://eddn.edcd.io/schemas/fcmaterials_capi/1/test": "fcmaterials_capi-v1.0.json",
    "https://eddn.edcd.io/schemas/dockinggranted/1": "dockinggranted-v1.0.json",
    "https://eddn.edcd.io/schemas/dockinggranted/1/test": "dockinggranted-v1.0.json",
    "https://eddn.edcd.io/schemas/dockingdenied/1": "dockingdenied-v1.0.json",
    "https://eddn.edcd.io/schemas/dockingdenied/1/test": "dockingdenied-v1.0.json",
}


def default_validator() -> Validator:
    validator = Validator()
    for ref, fname in EDDN_SCHEMAS.items():
        validator.add_schema(ref, fname)
    return validator


class Validator:
    schemas = {}

    def add_schema(self, schemaRef: str, filename: str) -> None:
        if schemaRef in self.schemas.keys():
            raise Exception(f"Schema {schemaRef} already exists")

        try:
            data = read_binary(schema, filename)
            self.schemas[schemaRef] = xxjson.loads(data)
        except ValueError:
            raise Exception(f"Failed to load {schemaRef}")

    def validate(self, json):
        results = ValidationResults()
        if "$schemaRef" not in json:
            results.add(
                ValidationSeverity.FATAL,
                JsonValidationException("No $schemaRef found, unable to validate"),
            )
            return results

        schemaRef = json["$schemaRef"]
        if schemaRef not in self.schemas.keys():
            results.add(
                ValidationSeverity.FATAL,
                JsonValidationException("Unknown $schemaRef, unable to validate"),
            )
            return results

        schema = self.schemas[schemaRef]
        try:
            validate(json, schema, format_checker=FormatChecker())
        except ValidationError as e:
            results.add(ValidationSeverity.ERROR, e)

        return results


class ValidationSeverity(IntEnum):
    OK = (0,)
    WARN = (1,)
    ERROR = (2,)
    FATAL = 3


class ValidationResults:
    def __init__(self):
        self.severity = ValidationSeverity.OK
        self.messages = []

    def add(self, severity, exception):
        self.severity = max(severity, self.severity)
        self.messages.append(exception)


class JsonValidationException(Exception):
    pass
