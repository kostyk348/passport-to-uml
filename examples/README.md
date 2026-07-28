# Examples

## Basic usage

```bash
python -m passport_to_uml.engine "document.pdf" "diagram" -v
```

Generates a component diagram with subsystem groups and labeled connections.

## Python API

```python
from passport_to_uml import parse_passport, build_diagram

model = parse_passport("document.pdf", verbose=True)

print(f"Found {len(model.components)} components")
print(f"Found {len(model.relations)} connections")

for r in model.relations:
    c1 = model.components[r.from_id].name
    c2 = model.components[r.to_id].name
    print(f"  {c1} → {c2} [{r.label}]")

build_diagram(model, "diagram")
```
