# hbsc-data-validator

Tools for describing a survey data set in a YAML data model and checking data files against it. Developed for HBSC, but not constrained to working
with HBSC data.

The model file lists the variables (type, labels, legal range, missing codes, mandatory flag, nesting and so on). It does not depend on SPSS, R, Python/pandas or any other tool: the model structure is in [hbsc_model.schema.yaml](hbsc_model.schema.yaml) (JSON Schema) and its meaning in [SPEC.md](SPEC.md). A validator can be written in any language from these.

**This repository contains no HBSC data, variable lists, model files, or other information about the HBSC study.**
The code and the schema are generic: you supply the model for your own data.

## What it does

- **Edit a model:** `HBSC` (in [HBSC_class.py](HBSC_class.py)) creates, loads and saves a model, and adds, updates, renames and removes variables, aliases and rules.
- **Check a model:** `check_model()` reports a model that breaks the schema or refers to things that do not exist.
- **Validate data:** `validate()` checks a pandas DataFrame and `validate_file()` checks a `.sav` or `.csv` file. Findings come back as a structured result, not exceptions.

Checks on the data:

- mandatory columns present and not entirely empty
- value type, legal range, and value labels (values that are not among the labels)
- constraints: unique column values, no missings allowed, or nested variables
- duplicate column names
- column names that are aliases or case variants of a model name
- national variants of variable names (the naming convention is the `national_variant` setting of the model), and column names the model does not know

Not implemented yet: custom `rules`. They can be stored in a model and are checked for valid syntax, but they are not evaluated against data.

## Install

Python 3.11 or later is needed.

```
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On Windows, activate with `.venv\Scripts\activate` instead. Activate the environment again in each new shell before running the code below.

## Quick start

Create a model, save it and check it:

```python
from HBSC_class import HBSC

model = HBSC("my_model.yaml", load=False)
model.add_variable("id", {"type": "integer", "required": True, "unique": True})
model.add_variable("age", {"type": "integer", "kind": "continuous", "range": {"min": 5, "max": 100}})
model.add_variable("smoker", {"type": "integer", "kind": "nominal", "labels": {"1": "yes", "2": "no"}})
model.save()

assert model.check_model()["ok"]
```

Load it later and check a data file. With this `data.csv`:

```
id,age,smoker
1,12,1
2,200,2
```

```python
model = HBSC("my_model.yaml")
result = model.validate_file("data.csv")
result["ok"]
result["issues"]["out_of_range"]
```

`result` is `{"ok", "country", "file", "issues"}`. `issues` maps each issue type to a list of findings. A finding names the variable, how many values were checked and how many failed, and lists each failing row index and value. For example, `out_of_range` gives:

```
{"variable": "age", "legal min": 5, "legal max": 100, "n_checked": 2, "count": 1,
 "violations": [{"row": 1, "value": 200}]}
```

Row numbers start at 0, the first data row. Every issue type is always present, with an empty list when nothing was found. The types and their fields are in [SPEC.md](SPEC.md) section 8.

## Missing values

`NaN` is always missing. For `.sav` files, user-defined missing codes are kept as values and matched against the `missing` specification of the model, so they are not silently turned into `NaN`. CSV files are read as text and converted per variable type, and conversion failures are reported as `type_mismatch`. Details: [SPEC.md](SPEC.md) section 4.

## Models and rules from untrusted sources

Custom rules are Python expression strings. When the evaluator exists, it will (likely) use `eval` with a restricted namespace, which limits but does not remove risk. Do not evaluate the rules of a model that comes from an
untrusted source.

## Further documentation

- [SPEC.md](SPEC.md): what the model fields mean and what a validator must do.
- [hbsc_model.schema.yaml](hbsc_model.schema.yaml): the structure of a model file.
- Docstrings of `HBSC`, `validate` and `validate_file` in [HBSC_class.py](HBSC_class.py).
