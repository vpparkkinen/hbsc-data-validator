# Survey data model specification, schema version 1

The model is a YAML file that describes the variables of a survey data file and custom validation rules. It is the source of truth for validating incoming data. It does not depend on SPSS, Python, R or any other tool: everything an implementation needs is in the model file, [hbsc_model.schema.yaml](hbsc_model.schema.yaml) (model structure), and in this document.

- **Structure**: `hbsc_model.schema.yaml` is a JSON Schema (draft 2020-12) written in YAML. It lists the fields, their types, the allowed values and a description of each field.
- **Meaning**: this document defines what the fields mean and how a validator must treat them. Rules that a JSON Schema cannot express (references between variables, uniqueness across the model) are in the section "Model checks".
- **Reference implementation**: `HBSC` in `HBSC_class.py`. `HBSC.check_model()` checks a model file, `HBSC.validate()` and `HBSC.validate_file()` check data (pandas df and .sav/.csv, respectively).

## 1. Model file

Top-level keys:

| Key | Required | Meaning |
| --- | --- | --- |
| `schema_version` | yes | Always `1` for this specification. |
| `source` | no | Source for the model, e.g. `spss:<file name>`. Free text. |
| `missing_default` | no | Missing-value specification for variables without their own `missing`. See section 4. |
| `national_variant` | no | Naming convention for national variants of variables, `{separator, code}`. See section 6. |
| `variables` | yes | Mapping, canonical column name to variable definition. |
| `rules` | no | Mapping, rule name to rule. See section 7. |

No other top-level keys are allowed.

## 2. Variables

A variable is a mapping. Only `type` is required.

| Field | Values | Meaning |
| --- | --- | --- |
| `type` | `integer`, `float`, `string` | Storage type. `integer` allows whole numbers only: 2.5 is a type error, 2.0 is fine. SPSS format F.0 gives integer. |
| `kind` | `nominal`, `ordinal`, `continuous` | Measurement type, conceptually. Independent of `type`. `continuous` means interval or ratio scale regardless of storage type, so integer counts and whole-number measurements (e.g. a number of siblings, a height in whole centimetres) are continuous. Only `type` decides whether decimals are legal. Initialised from the SPSS measure if the source is a .sav file ("scale" gives continuous) and may be overridden. |
| `role` | `id`, `weight`, `design`, `open_text`, `date` | Function in the dataset. Omitted for ordinary survey items. |
| `required` | boolean | Whether or not a variable is mandatory. A mandatory column must be present and not missing in every row. |
| `label` | text | Variable label. |
| `labels` | mapping, code to text | Value labels. Keys are canonical strings. |
| `range` | `{min, max}` | Legal numeric interval, bounds inclusive. Only for `kind: continuous`. |
| `missing` | missing specification | Variable-specific user-missing codes. Replaces `missing_default`. |
| `missing_allowed` | boolean, default true | When false, validator flags any missing value as a finding. |
| `unique` | boolean | Non-missing values must not repeat across rows. |
| `nested_in` | variable name | Each value must coincide
with a single value of the named parent variable. |
| `source` | `protocol`, `reference` | Where the definition comes from: `protocol` is the authoritative survey specification, `reference` a reference data file. Only when it differs from the model-level `source`. |
| `note` | text | Free text recording of a decision or discrepancy. |
| `aliases` | mapping | Alternative names, section 3. |
| `spss` | `{format, measure}` | Raw SPSS metadata when
source is a reference .sav. A validator reads `type` and `kind`, never `spss`, so this field is included mostly
just to help spot errors/confusions in the SPSS metadata file, if one is used as a source for the model. |

If `kind` and `spss.measure` do not follow the usual mapping, someone decided so. The model builder applies such decisions from an overrides file (section 10).

## 3. Names

- The key under `variables` is the canonical name, with the capitalisation used in the model.
- An incoming column that equals an alias, or equals a canonical name except for capitalisation, is a `non_canonical_name` finding. A validator never renames columns.
- `aliases` maps an alias name to `{source: protocol|reference, note}`. It records naming variants between the two sources of the model (`protocol`, `reference`) only, never country-specific names. Alias names are unique across the model and never equal to a variable name.
- A variable name must not look like a national variant of another variable (section 6). `HBSC.check_model()` reports such names as `name_clash`. 

## 4. Missing values

- A missing specification is `{values: [codes], ranges: [{min, max}]}`, both optional. Ranges are inclusive.
- `NaN` (system-missing) is always missing. A blank string is missing in a string variable.
- A variable's `missing` replaces `missing_default`. The two are never combined.
- Missing values are skipped by the type, range and value-label checks.
- User-missing codes are read from the .sav when it is loaded (`user_missing=True`), so they reach this logic and are not turned into `NaN` by the reader. A model that defines no missing codes treats only `NaN` (and blank strings in string variables) as missing.
- In CSV input every value is text. A code such as `99` matches the text `"99"`.

## 5. Value checks

Applied per variable, to the non-missing values of columns that are present.

1. **Type.** `integer` and `float`: the value must convert to a number. `integer`: it must also be an exact whole number (`value % 1 == 0`, no tolerance, so `2.5` fails and `2.0` passes). `string`: it must be text. Findings: `type_mismatch`.
2. **Range.** If `range` is set and the type is numeric, a value below `min` or above `max` is `out_of_range`.
3. **Value labels.** If `labels` is set and `kind` is not `continuous`, the value must be one of the label keys, else `invalid_labels`. Keys and data values are compared as canonical strings: integral numbers without decimals, so `1`, `1.0` and `"1"` all become `"1"`.
4. **Missing not allowed.** `missing_allowed: false` and a missing value: `missing_not_allowed`.
5. **Unique.** `unique: true` and a repeated value: `not_unique`. Every row that shares a repeated value is reported.
6. **Nested.** `nested_in: P` and a value that occurs with more than one value of `P`in a pair of observations -> `P`: `not_nested`. Rows where either value is missing are skipped. Every row of an affected value is reported, because the data does not say which side is wrong.
7. **Duplicates.** A column name that occurs more than once is `duplicate_columns`. The column counts as present, but its values are not checked (nor used as `nested_in` parent), because the data does not say which copy is meant.
8. **Presence.** A `required` variable with no column is `missing_columns`. A `required` variable whose values are all missing is `missing_required`.

Values in findings are normalised for display: an integral number from a numeric-typed variable is shown without decimals.

## 6. National variants

A country may rename a variable that deviates from the international version. The naming convention is part of the model, key `national_variant`:

```
national_variant:
  separator: "_"
  code: "[A-Z]{2}"
```

- `separator` is the text between the variable name and the code. `code` is a regular expression that the whole code must match. It is written without anchors and named groups, and matched case-sensitively. A model written for a different convention changes these two values and nothing else.
- A column name is split at the last occurrence of `separator`. If the part before it is not empty and the part after it matches `code`, the column is a national variant of the variable named by the first part. 
- A column that equals a variable name exactly is always that variable, never a variant. This matters when a variable name itself ends in a code-like suffix.
- Without `national_variant`, no column is a national variant: every column that is not in the model is `unknown_columns`.
- A column that is a variant of a variable of the model is a `national_deviation` finding. It counts as the variable being present (no `missing_columns`), and its values are not checked.
- The national variant replaces the international variable. The international variable is not expected in the file.
- If the validator is given the submitter's `country`, only a column whose code equals it, compared case-insensitively, matches. Other columns become `unknown_columns`.
- If the validator is given a list of `documented` column names, the matching deviations are marked `documented: true`. A listed name that is not a column of the data is `documented_not_found`.
- Each deviation entry carries `base_present` (the international variable is in the file) and `base_required` (it is mandatory).
- Any other column that is not in the model is `unknown_columns`. Items that exist only in one country have no naming rule.

## 7. Rules

A rule is a mapping with `assert` (required), `if`, `description`, `severity` (`error` or `warning`, default `error`) and `enabled` (default true).

- `if` and `assert` are Python expression strings, evaluated vectorised over the data, each returning a boolean per row. Variables are referenced by column name. `if` selects the rows, `assert` must be true for the selected rows. A selected row where `assert` is false is a violation.
- Keep expressions simple: comparisons, `&`, `|`, `~`, `.isna()`, `.isin()`. A later port to a declarative form should be mechanical. This is a temporary choice, tool independence of rules is deferred.
- Evaluation uses `eval` with `{"__builtins__": {}}` and only the data columns plus `pd` and `np`. Never evaluate the rules of an untrusted model.
- An invalid expression, or a reference to a column that is not in the data, is reported as a rule error and must not stop validation.
- Missing values: the expression sees `NaN` for system-missing and the raw code for user-missing codes. Rules that must ignore user-missing codes have to say so explicitly.
- Status: rules are stored and checked by `check_model()`, but the evaluator is not implemented yet.

## 8. Validator output

`validate(df, country=None, documented=None)` and `validate_file(path, ...)` return a mapping:

```
{"ok": bool, "country": ..., "issues": {<issue type>: [...]}}
```

`validate_file` also returns `file`, the file name. Validators never change the input data or the model, and report problems as findings, not exceptions. A file that cannot be read gives a `file_error`.

Each issue type belongs to a category. `ok` is true when there are no findings in the category `issue`.

| Issue type | Category | Entries |
| --- | --- | --- |
| `missing_columns`, `missing_required` | issue | list of variable names |
| `duplicate_columns` | issue | list of column names that occur more than once |
| `non_canonical_name` | issue | `{column, expected, reason}` |
| `type_mismatch`, `out_of_range`, `invalid_labels`, `missing_not_allowed`, `not_unique`, `not_nested` | issue | `{variable, n_checked, count, violations: [{row, value}]}` plus type-specific fields |
| `file_error` | issue | `{path, message}` |
| `national_deviation` | deviation | `{column, variable, code, base_present, base_required, documented}` |
| `unknown_columns`, `documented_not_found` | note | list of names |

Row numbers are the index of the loaded table. For files loaded by `validate_file` they start at 0 (the first data row is 0, for a CSV the spreadsheet row is that number plus 2). A final convention is not decided
and likely cannot be, as indexing (of iterables)
varies between R, SPSS, Python, other tools.

## 9. Model checks

`HBSC.check_model()` returns `{"ok": bool, "issues": {...}}` and never raises for a faulty model. Groups:

- `schema_error`: the model does not match `hbsc_model.schema.yaml`.
- `reference_error`: a reference inside the model is wrong. `national_variant.code` is not a valid regular expression. `nested_in` names no variable, is circular or points at itself. An alias equals a variable name or is used twice. `range` on a variable whose `kind` is not `continuous`. `min` greater than `max` in a range or missing range. A label key that is not canonical.
- `rule_error`: an `if` or `assert` is not a valid expression, or names something that is not a variable of the model (or `pd`, `np`). The expressions are parsed, never evaluated.
- `name_clash`: a variable name that looks like a national deviation of another variable (section 3). Does not affect `ok`.

`ok` is true when `schema_error`, `reference_error` and `rule_error` are all empty. Entries are `{path, message}`, with the path in dotted form, e.g. `variables.id2.nested_in`.

## 10. Building and editing

- `spss2model()` (`spss2model.py`) builds a model from a reference .sav: names, types, labels, SPSS formats and measures, user-missing codes. The list of mandatory variables and the `national_variant` setting are passed in.
- Human decisions (notes, aliases, source, role, kind, id constraints) are kept in a separate overrides file and applied after the import, so regenerating the model keeps them. Edit decisions there, not in the generated model.
- `HBSC` offers `add/get/update/remove/rename_variable`, `add_alias`, `remove_alias`, `set_note`, `set_labels`, `set_national_variant`, and `add/get/update/remove_rule`. Fields set through these are validated against the allowed values before they are stored.
