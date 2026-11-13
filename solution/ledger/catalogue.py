"""Schema catalogue: the workflow lead schemas and disposition codes from the schemas directory."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

from ledger.errors import DataError


@dataclass(frozen=True)
class Field:
    name: str
    type: str
    required: bool
    pii: bool
    reference: bool
    aliases: tuple[str, ...] = ()
    allowed_values: tuple[str, ...] = ()  # `enum` fields only
    default: str | None = None  # applied on read, never stored (ADR-0006)


@dataclass(frozen=True)
class WorkflowSchema:
    workflow_id: str
    fields: tuple[Field, ...]  # in schema order, which decides which rejection reason wins

    @property
    def accepted_headers(self) -> dict[str, tuple[str, ...]]:
        """Return each field's name and aliases, in schema order, for header mapping."""
        return {f.name: (f.name, *f.aliases) for f in self.fields}

    @property
    def reference_field(self) -> Field:
        return next(f for f in self.fields if f.reference)

    @property
    def phone_field(self) -> Field:
        return next(f for f in self.fields if f.type == "phone")

    @property
    def name_field(self) -> Field | None:
        """Return the customer name field (the PII field besides the phone), if the schema has one."""
        return next(iter(self.other_pii_fields), None)

    @property
    def other_pii_fields(self) -> tuple[Field, ...]:
        """Return the PII fields besides the phone; loading allows at most one (the name)."""
        return tuple(f for f in self.fields if f.pii and f.type != "phone")


@dataclass(frozen=True)
class Disposition:
    workflow_id: str
    code: str
    is_terminal: bool
    is_success: bool


@dataclass(frozen=True)
class Catalogue:
    workflows: dict[str, WorkflowSchema]
    dispositions: tuple[Disposition, ...] = field(default=())

    def schema(self, workflow_id: str) -> WorkflowSchema:
        try:
            return self.workflows[workflow_id]
        except KeyError:
            raise DataError(f"no lead schema for workflow {workflow_id!r}") from None


def load_catalogue(schemas_dir: Path) -> Catalogue:
    """Load every `*.json` lead schema and `dispositions.csv` from `schemas_dir`."""
    workflows = {}
    for path in sorted(Path(schemas_dir).glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        fields = tuple(
            Field(
                name=f["name"],
                type=f["type"],
                required=bool(f.get("required", False)),
                pii=bool(f.get("pii", False)),
                reference=bool(f.get("reference", False)),
                aliases=tuple(f.get("aliases", ())),
                allowed_values=tuple(f.get("values", ())),
                default=f.get("default"),
            )
            for f in raw["fields"]
        )
        schema = WorkflowSchema(raw["workflow_id"], fields)
        _check_identity_fields(path, schema)
        workflows[schema.workflow_id] = schema
    return Catalogue(workflows, _load_dispositions(Path(schemas_dir) / "dispositions.csv"))


_DISPOSITION_COLUMNS = ("workflow_id", "code", "is_terminal", "is_success")


def _load_dispositions(path: Path) -> tuple[Disposition, ...]:
    """Load each workflow's disposition codes and whether each is terminal and/or a success."""
    if not path.exists():
        raise DataError(f"disposition catalogue not found: {path}")
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in _DISPOSITION_COLUMNS if c not in (reader.fieldnames or ())]
        if missing:
            raise DataError(f"{path}: missing columns {', '.join(missing)}")
        dispositions = []
        for line, row in enumerate(reader, start=2):
            flags = [row[c].strip().lower() for c in ("is_terminal", "is_success")]
            if any(flag not in ("true", "false") for flag in flags) or not row["code"].strip():
                raise DataError(f"{path}: line {line}: expected a code and true/false flags")
            dispositions.append(
                Disposition(
                    row["workflow_id"].strip(), row["code"].strip(), flags[0] == "true", flags[1] == "true"
                )
            )
    return tuple(dispositions)


def _check_identity_fields(path: Path, schema: WorkflowSchema) -> None:
    """Refuse a schema the pipeline cannot store.

    Every lead is identified by its phone and an external reference, so each must be
    exactly one required field. At most one other field may be PII, because the store
    has a single encrypted column for it (the customer name).
    """
    for kind, matches in (
        ("phone", [f for f in schema.fields if f.type == "phone"]),
        ("reference", [f for f in schema.fields if f.reference]),
    ):
        if len(matches) != 1 or not matches[0].required:
            raise DataError(f"{path}: schema must have exactly one required {kind} field")
    if len(schema.other_pii_fields) > 1:
        raise DataError(f"{path}: schema may have at most one PII field besides the phone (the name)")
