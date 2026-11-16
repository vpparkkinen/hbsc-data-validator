import ast
import math
import re
from pathlib import Path

import yaml
import numpy as np
import pandas

SCHEMA_VERSION = 1
TYPES = ("integer", "float", "string")
KINDS = ("nominal", "ordinal", "continuous")
ROLES = ("id", "weight", "design", "open_text", "date")
SOURCES = ("protocol", "reference")
CATEGORIES = {
    "missing_columns": "issue",
    "missing_required": "issue",
    "duplicate_columns": "issue",
    "non_canonical_name": "issue",
    "type_mismatch": "issue",
    "out_of_range": "issue",
    "invalid_labels": "issue",
    "missing_not_allowed": "issue",
    "not_unique": "issue",
    "not_nested": "issue",
    "national_deviation": "deviation",
    "unknown_columns": "note",
    "documented_not_found": "note",
    "file_error": "issue",
}
SCHEMA_FILE = Path(__file__).with_name("hbsc_model.schema.yaml")
RULE_NAMESPACE = ("pd", "np")


def num(x):
    f = float(x)
    return int(f) if f.is_integer() else f


def label_key(k):
    if isinstance(k, (bool, np.bool_)):
        return str(int(k))
    if isinstance(k, str):
        try:
            k = float(k)
        except ValueError:
            return k
    if isinstance(k, (int, float, np.integer, np.floating)):
        f = float(k)
        return str(int(f)) if f.is_integer() else str(f)
    return str(k)


def plain(v, numeric=False):
    if isinstance(v, np.generic):
        v = v.item()
    if numeric and isinstance(v, str):
        try:
            f = float(v)
        except ValueError:
            return v
        return int(f) if math.isfinite(f) and f.is_integer() else v
    if isinstance(v, float) and math.isfinite(v) and v.is_integer():
        return int(v)
    return v


def normalize_missing(spec):
    if not spec:
        return {}
    out = {}
    values = spec.get("values") or []
    ranges = spec.get("ranges") or []
    if values:
        out["values"] = [num(v) if not isinstance(v, str) else v for v in values]
    if ranges:
        out["ranges"] = [{"min": num(r["min"]), "max": num(r["max"])} for r in ranges]
    return out


class HBSC:
    """HBSC data model: edit, save and validate data against it.

    Wraps a model file (YAML) held in `data`. Provides editing
    of variables, aliases and rules, `check_model()` for the model itself,
    and `validate()` / `validate_file()` for data. Rules are stored and
    checked but not evaluated yet.

    Parameters
    ----------
    path : str or pathlib.Path
        Model file, also the target of `save()`. A missing file gives an
        empty model.
    load : bool, default True
        If false, start from an empty model and do not read `path`.
    """

    def __init__(self, path, load=True):
        self.path = path
        self.data = self._load() if load else {}
        self.data.setdefault("schema_version", SCHEMA_VERSION)
        self.data.setdefault("missing_default", {})
        self.data.setdefault("variables", {})
        self.data.setdefault("rules", {})
        if not isinstance(self.data["variables"], dict) or not isinstance(self.data["rules"], dict):
            raise ValueError("variables and rules must be mappings keyed by name")

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            return {}

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            yaml.dump(self.data, f, sort_keys=False, allow_unicode=True)

    # METADATA

    def set_metadata(self, **kwargs):
        self.data.update(kwargs)

    def set_missing_default(self, spec):
        self.data["missing_default"] = normalize_missing(spec)

    def set_national_variant(self, separator=None, code=None):
        """Set or clear the naming convention for national variants of variables.

        Parameters
        ----------
        separator : str, optional
            Text between the variable name and the code. Give both
            arguments, or neither to remove the convention.
        code : str, optional
            Regular expression the whole code part must match, case-sensitive.
            Written without anchors or named groups.
        """
        if separator is None and code is None:
            self.data.pop("national_variant", None)
            return
        if not isinstance(separator, str) or not separator or not isinstance(code, str) or not code:
            raise ValueError("separator and code must both be non-empty strings")
        try:
            re.compile(code)
        except re.error as e:
            raise ValueError(f"code is not a valid regular expression: {e}")
        self.data["national_variant"] = {"separator": separator, "code": code}

    # VARIABLES

    def _prepare_variable(self, variable):
        if "type" in variable and variable["type"] not in TYPES:
            raise ValueError(f"type must be one of {TYPES}")
        if "kind" in variable and variable["kind"] not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}")
        if "role" in variable and variable["role"] not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        if "source" in variable and variable["source"] not in SOURCES:
            raise ValueError(f"source must be one of {SOURCES}")
        for flag in ("missing_allowed", "unique"):
            if flag in variable and not isinstance(variable[flag], bool):
                raise ValueError(f"{flag} must be a boolean")
        if "nested_in" in variable and not isinstance(variable["nested_in"], str):
            raise ValueError("nested_in must be a variable name")
        if "aliases" in variable:
            raise ValueError("use add_alias to set aliases")
        if "labels" in variable:
            variable["labels"] = self._normalize_labels(variable["labels"])
        if "missing" in variable:
            variable["missing"] = normalize_missing(variable["missing"])
        return variable

    def add_variable(self, name, spec):
        if name in self.data["variables"]:
            raise ValueError(f"Variable '{name}' already exists")
        self.data["variables"][name] = self._prepare_variable(dict(spec))

    def get_variable(self, name):
        try:
            return self.data["variables"][name]
        except KeyError:
            raise ValueError(f"Variable '{name}' not found") from None

    def update_variable(self, name, updates):
        var = self.get_variable(name)
        updates = self._prepare_variable(dict(updates))
        for key, value in updates.items():
            if key == "range" and isinstance(value, tuple):
                var["range"] = {"min": value[0], "max": value[1]}
            else:
                var[key] = value

    def rename_variable(self, old, new):
        self.get_variable(old)
        if new in self.data["variables"]:
            raise ValueError(f"Variable '{new}' already exists")
        self.data["variables"] = {
            (new if k == old else k): v for k, v in self.data["variables"].items()
        }
        for var in self.data["variables"].values():
            if var.get("nested_in") == old:
                var["nested_in"] = new

    def alias_map(self):
        return {
            alias: name
            for name, var in self.data["variables"].items()
            for alias in var.get("aliases", {})
        }

    def add_alias(self, variable, alias, source, note=None):
        if source not in SOURCES:
            raise ValueError(f"source must be one of {SOURCES}")
        var = self.get_variable(variable)
        if alias in self.data["variables"] or alias in self.alias_map():
            raise ValueError(f"Name '{alias}' already in use")
        entry = {"source": source}
        if note:
            entry["note"] = note
        var.setdefault("aliases", {})[alias] = entry

    def set_note(self, variable, note):
        var = self.get_variable(variable)
        if note:
            var["note"] = note
        else:
            var.pop("note", None)

    def remove_alias(self, variable, alias):
        aliases = self.get_variable(variable).get("aliases", {})
        if alias not in aliases:
            raise ValueError(f"Alias '{alias}' not found on '{variable}'")
        del aliases[alias]
        if not aliases:
            del self.data["variables"][variable]["aliases"]

    def remove_variable(self, name):
        self.get_variable(name)
        del self.data["variables"][name]

    # LABEL HELPERS

    def set_labels(self, variable_name, labels):
        self.update_variable(variable_name, {"labels": labels})

    def get_labels(self, variable_name):
        return self.get_variable(variable_name).get("labels", {})

    def _normalize_labels(self, labels):
        return {label_key(k): v for k, v in labels.items()}

    # VALIDATION

    def missing_spec(self, var):
        if "missing" in var:
            return var["missing"]
        return self.data.get("missing_default") or {}

    def missing_mask(self, series, var):
        spec = self.missing_spec(var)
        mask = series.isna()
        values = spec.get("values")
        if values:
            mask |= series.isin(values)
            if not pandas.api.types.is_numeric_dtype(series):
                keys = {label_key(v) for v in values}
                mask |= series.map(lambda x: pandas.notna(x) and label_key(x) in keys).astype(bool)
        ranges = spec.get("ranges")
        if ranges:
            numeric = pandas.to_numeric(series, errors="coerce")
            for r in ranges:
                mask |= numeric.between(r["min"], r["max"])
        if var.get("type") == "string":
            mask |= series.astype(str).str.strip().eq("") & series.notna()
        return mask

    @staticmethod
    def _violations(bad, numeric=False):
        return [{"row": int(idx), "value": plain(value, numeric)} for idx, value in bad.items()]

    def split_variant(self, column):
        spec = self.data.get("national_variant")
        if not isinstance(spec, dict):
            return None
        separator, pattern = spec.get("separator"), spec.get("code")
        if not isinstance(separator, str) or not separator or not isinstance(pattern, str):
            return None
        base, found, code = str(column).rpartition(separator)
        if not found or not base:
            return None
        try:
            if not re.fullmatch(pattern, code):
                return None
        except re.error:
            return None
        return base, code

    def deviation_of(self, column, country=None):
        split = self.split_variant(column)
        if not split or split[0] not in self.data["variables"]:
            return None
        base, code = split
        if country is not None and code.upper() != str(country).upper():
            return None
        return base, code

    def validate_dataframe(self, df, country=None, documented=None):
        """Check a dataframe against the model and collect findings.

        Never mutates the input and never raises for problems in the data:
        every mismatch between df and a model is recorded as a finding, 
        grouped by issue type.
        Missing values (NaN and user-missing codes) are skipped by the type,
        range and value-label checks. A duplicated column name is reported
        and its values are not checked. Use `validate()` for the standard
        result with an `ok` flag.

        Parameters
        ----------
        df : pandas.DataFrame
            Data to check.
        country : str, optional
            ISO 3166 code, case-insensitive. Restricts which
            column name suffixes count as national deviations.
        documented : list of str, optional
            Names of columns with expected and already documented deviations.
            Names not found in `df` become `documented_not_found`.

        Returns
        -------
        dict
            Issue type to list of findings, with every issue type present
            (empty list if no findings). Entries are variable or column
            names for `missing_columns`, `missing_required`,
            `duplicate_columns`, `unknown_columns` and `documented_not_found`,
            and dicts for the others. `file_error` is always empty here, it
            is only filled by `validate_file()`. For entry fields and issue
            categories (`issue`, `deviation`, `note`) see SPEC.md section 8.

        See Also
        --------
        validate : Wraps this with `ok` and `country`.
        validate_file : Loads a .sav or .csv file first.
        """

        issues = {
            "missing_columns": [],
            "missing_required": [],
            "duplicate_columns": [],
            "non_canonical_name": [],
            "unknown_columns": [],
            "documented_not_found": [],
            "file_error": [],
            "national_deviation": [],
            "type_mismatch": [],
            "out_of_range": [],
            "invalid_labels": [],
            "missing_not_allowed": [],
            "not_unique": [],
            "not_nested": [],
        }

        documented = set(documented or [])
        variables = self.data["variables"]
        aliases = self.alias_map()
        canonical_folded = {n.casefold(): n for n in variables}
        deviation_bases = set()
        issues["duplicate_columns"] = list(dict.fromkeys(df.columns[df.columns.duplicated()]))
        dup_cols = set(issues["duplicate_columns"])
        for col in dict.fromkeys(df.columns):
            if col in variables:
                continue
            deviation = self.deviation_of(col, country)
            if col in aliases:
                issues["non_canonical_name"].append(
                    {"column": col, "expected": aliases[col], "reason": "alias"}
                )
            elif deviation:
                base, code = deviation
                deviation_bases.add(base)
                issues["national_deviation"].append({
                    "column": col, "variable": base, "code": code,
                    "base_present": base in df.columns,
                    "base_required": bool(variables[base].get("required")),
                    "documented": col in documented,
                })
            elif str(col).casefold() in canonical_folded:
                issues["non_canonical_name"].append(
                    {"column": col, "expected": canonical_folded[str(col).casefold()], "reason": "case"}
                )
            else:
                issues["unknown_columns"].append(col)

        issues["documented_not_found"] = sorted(n for n in documented if n not in df.columns)

        for name, var in variables.items():
            if name not in df.columns:
                if var.get("required") and name not in deviation_bases:
                    issues["missing_columns"].append(name)
                continue
            if name in dup_cols:
                continue

            series = df[name]
            numeric_type = var.get("type") in ("integer", "float")
            miss = self.missing_mask(series, var)

            if var.get("required") and len(series) > 0 and miss.all():
                issues["missing_required"].append(name)

            if var.get("missing_allowed") is False and miss.any():
                issues["missing_not_allowed"].append({
                    "variable": name,
                    "n_checked": int(len(series)),
                    "count": int(miss.sum()),
                    "violations": self._violations(series[miss], numeric_type),
                })

            present = series[~miss]
            if present.empty:
                continue

            if var.get("unique"):
                keys = present.map(label_key)
                dup = keys.duplicated(keep=False)
                if dup.any():
                    issues["not_unique"].append({
                        "variable": name,
                        "n_checked": int(len(present)),
                        "count": int(dup.sum()),
                        "violations": self._violations(present[dup], numeric_type),
                    })

            parent = var.get("nested_in")
            if parent and parent in variables and parent in df.columns and parent not in dup_cols:
                pmiss = self.missing_mask(df[parent], variables[parent])
                both = ~miss & ~pmiss
                child = df.loc[both, name].map(label_key)
                par = df.loc[both, parent].map(label_key)
                spread = par.groupby(child).transform("nunique") > 1
                if spread.any():
                    bad = child[spread]
                    issues["not_nested"].append({
                        "variable": name,
                        "parent": parent,
                        "n_checked": int(both.sum()),
                        "count": int(spread.sum()),
                        "n_values": int(bad.nunique()),
                        "violations": [
                            {"row": int(idx), "value": plain(df.at[idx, name], numeric_type),
                             "parent_value": plain(df.at[idx, parent], variables[parent].get("type") in ("integer", "float"))}
                            for idx in bad.index
                        ],
                    })

            vtype = var.get("type")
            numeric = None

            if vtype in ("integer", "float"):
                numeric = pandas.to_numeric(present, errors="coerce")
                bad_mask = numeric.isna()
                if vtype == "integer":
                    bad_mask |= numeric.notna() & (numeric % 1 != 0)
                if bad_mask.any():
                    issues["type_mismatch"].append({
                        "variable": name,
                        "expected": vtype,
                        "n_checked": int(len(present)),
                        "count": int(bad_mask.sum()),
                        "violations": self._violations(present[bad_mask], numeric_type),
                    })
                    numeric = numeric[~bad_mask]
            elif vtype == "string":
                bad_mask = present.map(lambda x: not isinstance(x, str))
                if bad_mask.any():
                    issues["type_mismatch"].append({
                        "variable": name,
                        "expected": vtype,
                        "n_checked": int(len(present)),
                        "count": int(bad_mask.sum()),
                        "violations": self._violations(present[bad_mask], numeric_type),
                    })

            rng = var.get("range")
            if rng and numeric is not None:
                minimum = rng.get("min")
                maximum = rng.get("max")
                outside = pandas.Series(False, index=numeric.index)
                if minimum is not None:
                    outside |= numeric < minimum
                if maximum is not None:
                    outside |= numeric > maximum
                if outside.any():
                    issues["out_of_range"].append({
                        "variable": name,
                        "legal min": minimum,
                        "legal max": maximum,
                        "n_checked": int(len(numeric)),
                        "count": int(outside.sum()),
                        "violations": self._violations(series.loc[outside.index[outside]], numeric_type),
                    })

            labels = var.get("labels")
            if labels and var.get("kind") != "continuous":
                allowed = {label_key(k) for k in labels}
                keys = present.map(label_key)
                bad_mask = ~keys.isin(allowed)
                if bad_mask.any():
                    issues["invalid_labels"].append({
                        "variable": name,
                        "allowed": sorted(allowed),
                        "n_checked": int(len(present)),
                        "count": int(bad_mask.sum()),
                        "violations": self._violations(present[bad_mask], numeric_type),
                    })

        return issues

    def validate(self, df, country=None, documented=None):
        """Check a dataframe against the model and return the standard result.

        Runs `validate_dataframe()` and adds an overall `ok` flag. Never
        mutates the input and never raises for problems in the data. `ok` is
        true when there are no findings in the category `issue`. Findings in
        the categories `deviation` and `note` do not affect it.

        Parameters
        ----------
        df : pandas.DataFrame
            Data to check.
        country : str, optional
            ISO 3166 code of the submitter, case-insensitive. Restricts which
            column name suffixes count as national deviations.
        documented : list of str, optional
            Names of columns with expected and already documented deviations.
            Names not found in `df` become `documented_not_found`.

        Returns
        -------
        dict
            ``{"ok": bool, "country": country as given, "issues": {...}}``.
            `issues` is the mapping from `validate_dataframe()`: issue type to
            list of findings, every type present. Entry fields and issue
            categories: SPEC.md section 8.

        See Also
        --------
        validate_dataframe : The checks, without `ok`.
        validate_file : Loads a .sav or .csv file first, adds `file`.
        """
        issues =self.validate_dataframe(df, country=country, documented=documented)
        return {
            "ok": not any(v for k, v in issues.items() if CATEGORIES.get(k, "issue") == "issue"),
            "country": country,
            "issues": issues,
        }

    @staticmethod
    def load_file(path, **read_kwargs):
        suffix = Path(path).suffix.lower()
        if suffix in (".sav", ".zsav"):
            import pyreadstat
            df, _ = pyreadstat.read_sav(str(path), user_missing=True, **read_kwargs)
            return df
        if suffix in (".csv", ".txt"):
            kwargs = {"dtype": str, "sep": None, "engine": "python", "encoding": "utf-8-sig"}
            kwargs.update(read_kwargs)
            return pandas.read_csv(path, **kwargs)
        raise ValueError(f"unsupported file type '{suffix}' (expected .sav, .zsav or .csv)")

    def validate_file(self, path, country=None, documented=None, **read_kwargs):
        """Load a .sav or .csv file and check it against the model.

        Reads the file with `load_file()` and passes the data to `validate()`.
        A file that cannot be read (missing, unsupported type, parse error,
        bad `read_kwargs`) is reported as a `file_error` finding and no other
        checks run. Never raises for problems in the file.

        Parameters
        ----------
        path : str or pathlib.Path
            File to check. `.sav` and `.zsav` are read with pyreadstat with
            user-missing codes kept (`user_missing=True`). `.csv` and `.txt`
            are read as text without type conversion, separator detected,
            UTF-8.
        country : str, optional
            ISO 3166 code of the submitter, case-insensitive. Restricts which
            column name suffixes count as national deviations.
        documented : list of str, optional
            Names of columns with expected and already documented deviations.
            Names not found in the data become `documented_not_found`.
        **read_kwargs
            Passed on to `pyreadstat.read_sav` or `pandas.read_csv`. For CSV
            they override the defaults above.

        Returns
        -------
        dict
            The result of `validate()` plus ``"file"``, the file name without
            its directory. On a read failure ``ok`` is false and ``issues``
            holds only a `file_error` entry ``{"path", "message"}``, every
            other issue type empty.

        Notes
        -----
        Row numbers in findings start at 0 for the first data row. For CSV
        the spreadsheet row is that number plus 2.

        See Also
        --------
        load_file : The reader alone.
        validate : Check a dataframe already in memory.
        """
        try:
            df = self.load_file(path, **read_kwargs)
        except Exception as e:
            issues = {k: [] for k in CATEGORIES}
            issues["file_error"].append({"path": str(path), "message": f"{type(e).__name__}: {e}"})
            return {"ok": False, "country": country, "file": Path(path).name, "issues": issues}
        result = self.validate(df, country=country, documented=documented)
        result["file"] = Path(path).name
        return result

    # MODEL CHECKS

    def check_model(self, schema_path=None):
        import jsonschema

        with open(schema_path or SCHEMA_FILE, "r", encoding="utf-8") as f:
            schema = yaml.safe_load(f)
        issues = {"schema_error": [], "reference_error": [], "rule_error": [], "name_clash": []}

        def add(group, path, message):
            issues[group].append({"path": ".".join(str(p) for p in path), "message": message})

        errors = jsonschema.Draft202012Validator(schema).iter_errors(self.data)
        for e in sorted(errors, key=lambda e: [str(p) for p in e.absolute_path]):
            add("schema_error", e.absolute_path, e.message)

        raw_vars = self.data.get("variables")
        raw_rules = self.data.get("rules")
        variables = {k: v for k, v in raw_vars.items() if isinstance(v, dict)} if isinstance(raw_vars, dict) else {}
        rules = {k: v for k, v in raw_rules.items() if isinstance(v, dict)} if isinstance(raw_rules, dict) else {}

        def check_ranges(path, spec):
            for i, r in enumerate((spec or {}).get("ranges") or []):
                if isinstance(r, dict) and _is_num(r.get("min")) and _is_num(r.get("max")) and r["min"] > r["max"]:
                    add("reference_error", path + ["ranges", i], "min is greater than max")

        def _is_num(x):
            return isinstance(x, (int, float)) and not isinstance(x, bool)

        if isinstance(self.data.get("missing_default"), dict):
            check_ranges(["missing_default"], self.data["missing_default"])

        nv = self.data.get("national_variant")
        if isinstance(nv, dict) and isinstance(nv.get("code"), str):
            try:
                re.compile(nv["code"])
            except re.error as e:
                add("reference_error", ["national_variant", "code"], f"not a valid regular expression: {e}")

        owners = {}
        for name, var in variables.items():
            where = ["variables", name]
            parent = var.get("nested_in")
            if isinstance(parent, str):
                if parent == name:
                    add("reference_error", where + ["nested_in"], "variable is nested in itself")
                elif parent not in variables:
                    add("reference_error", where + ["nested_in"], f"'{parent}' is not a variable of the model")
                else:
                    seen, cur = {name}, parent
                    while cur is not None and cur in variables:
                        if cur in seen:
                            add("reference_error", where + ["nested_in"], "nested_in chain is circular")
                            break
                        seen.add(cur)
                        cur = variables[cur].get("nested_in")
            aliases = var.get("aliases")
            if isinstance(aliases, dict):
                for alias in aliases:
                    if alias in variables:
                        add("reference_error", where + ["aliases", alias], "alias equals a variable name")
                    elif alias in owners:
                        add("reference_error", where + ["aliases", alias], f"alias already used by '{owners[alias]}'")
                    else:
                        owners[alias] = name
            rng = var.get("range")
            if isinstance(rng, dict):
                if var.get("kind") != "continuous":
                    add("reference_error", where + ["range"], "range is only allowed for kind continuous")
                if _is_num(rng.get("min")) and _is_num(rng.get("max")) and rng["min"] > rng["max"]:
                    add("reference_error", where + ["range"], "min is greater than max")
            if isinstance(var.get("missing"), dict):
                check_ranges(where + ["missing"], var["missing"])
            labels = var.get("labels")
            if isinstance(labels, dict):
                for key in labels:
                    if label_key(key) != key:
                        add("reference_error", where + ["labels", key],
                            f"label key is not canonical, expected '{label_key(key)}'")
            split = self.split_variant(name)
            if split and split[0] in variables:
                add("name_clash", where,
                    f"name reads as national variant '{split[1]}' of '{split[0]}'")

        for name, rule in rules.items():
            for field in ("if", "assert"):
                expr = rule.get(field)
                if not isinstance(expr, str):
                    continue
                path = ["rules", name, field]
                try:
                    tree = ast.parse(expr.strip(), mode="eval")
                except (SyntaxError, ValueError, RecursionError, MemoryError) as e:
                    add("rule_error", path, f"not a valid expression: {type(e).__name__}")
                    continue
                used = sorted({n.id for n in ast.walk(tree) if isinstance(n, ast.Name)})
                for ident in used:
                    if ident not in variables and ident not in RULE_NAMESPACE:
                        add("rule_error", path, f"'{ident}' is not a variable of the model")

        ok = not any(issues[k] for k in ("schema_error", "reference_error", "rule_error"))
        return {"ok": ok, "issues": issues}

    # RULES

    def add_rule(self, name, spec):
        if name in self.data["rules"]:
            raise ValueError(f"Rule '{name}' already exists")
        rule = dict(spec)
        rule.setdefault("severity", "error")
        rule.setdefault("enabled", True)
        self.data["rules"][name] = rule

    def get_rule(self, name):
        try:
            return self.data["rules"][name]
        except KeyError:
            raise ValueError(f"Rule '{name}' not found") from None

    def update_rule(self, name, updates):
        self.get_rule(name).update(dict(updates))

    def remove_rule(self, name):
        self.get_rule(name)
        del self.data["rules"][name]
