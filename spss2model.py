import os
import re
import pyreadstat
from HBSC_class import HBSC, SCHEMA_VERSION, num

MEASURE_TO_KIND = {"nominal": "nominal", "ordinal": "ordinal", "scale": "continuous"}

FORMAT_RE = re.compile(r"^([A-Za-z]+)(\d+)(?:\.(\d+))?$")


def infer_type(spss_format, dtype):
    m = FORMAT_RE.match(spss_format or "")
    if m:
        fmt, _, dec = m.groups()
        if fmt.upper().startswith("A"):
            return "string"
        if fmt.upper() == "F":
            return "float" if dec and int(dec) > 0 else "integer"
    if "int" in dtype:
        return "integer"
    if "float" in dtype:
        return "float"
    return "string"


def extract_missing(meta, var_name):
    values = []
    ranges = []
    for r in (getattr(meta, "missing_ranges", None) or {}).get(var_name, []):
        lo, hi = r["lo"], r["hi"]
        if lo == hi:
            values.append(lo)
        else:
            ranges.append({"min": lo, "max": hi})
    for v in (getattr(meta, "missing_user_values", None) or {}).get(var_name, []):
        if v not in values:
            values.append(v)
    out = {}
    if values:
        out["values"] = values
    if ranges:
        out["ranges"] = ranges
    return out


def spss2model(sav_path, yaml_path, required=None, overrides=None, save=True, national_variant=None):
    df, meta = pyreadstat.read_sav(sav_path, user_missing=True)

    model = HBSC(yaml_path, load=False)
    model.data = {
        "schema_version": SCHEMA_VERSION,
        "source": f"spss:{os.path.basename(sav_path)}",
        "missing_default": {},
        "variables": {},
        "rules": {},
    }

    original_types = getattr(meta, "original_variable_types", {})
    measures = getattr(meta, "variable_measure", {})

    for var_name in meta.column_names:
        spss_format = original_types.get(var_name)
        var_type = infer_type(spss_format, str(df[var_name].dtype))

        var_dict = {"type": var_type, "required": False}

        measure = measures.get(var_name)
        if measure in MEASURE_TO_KIND:
            var_dict["kind"] = MEASURE_TO_KIND[measure]

        label = meta.column_names_to_labels.get(var_name, "")
        if label:
            var_dict["label"] = label

        raw_labels = meta.variable_value_labels.get(var_name)
        if raw_labels:
            var_dict["labels"] = raw_labels

            if var_dict.get("kind") == "continuous" and var_type != "string":
                keys = [float(k) for k in raw_labels]
                var_dict["range"] = {"min": num(min(keys)), "max": num(max(keys))}

        missing = extract_missing(meta, var_name)
        if missing:
            var_dict["missing"] = missing

        spss_info = {}
        if spss_format:
            spss_info["format"] = spss_format
        if measure in MEASURE_TO_KIND:
            spss_info["measure"] = measure
        if spss_info:
            var_dict["spss"] = spss_info

        model.add_variable(var_name, var_dict)

    for var_name in required or []:
        model.update_variable(var_name, {"required": True})

    for var_name, spec in (overrides or {}).items():
        spec = dict(spec)
        aliases = spec.pop("aliases", {})
        if spec:
            model.update_variable(var_name, spec)
        for alias, info in aliases.items():
            model.add_alias(var_name, alias, source=info["source"], note=info.get("note"))

    if national_variant:
        model.set_national_variant(national_variant["separator"], national_variant["code"])

    if save:
        model.save()
    return model
