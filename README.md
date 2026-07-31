# passport-to-uml

**Extract functional UML component diagrams from technical passport PDFs.**

Parses technical documentation (ГОСТ, ТУ, паспорта изделий), extracts
components, connections, and control logic, then renders a colored
UML-style diagram via Graphviz.

---

## Status: v1 — Proof of Concept

This version uses rule-based extraction with a domain seed for
a specific document type. A different document will likely produce
incomplete results.

**v2 goal:** Replace the fragile pattern matching with an LLM agent
that reads the text semantically — understands components, connections,
and control algorithms — and feeds structured data to the renderer.

---

## How It Works

```
Input: passport PDF (ГОСТ / standard)
  │
  ▼ pdfplumber
Extract text + sectionize by headers
  │
  ▼ pattern matching + domain seed
Extract components, connections, control flow
  │
  ▼ Graphviz (dot engine)
Build UML component diagram with color-coded subsystems
  │
  ▼
Output: PNG + PDF
```

### Diagram features
- Color-coded categories (airflow, hydronic, control, electrical, etc.)
- Logical grouping by subsystem (clusters with dashed borders)
- Labeled connections with flow direction
- Legend
- Russian labels, Arial font

---

## Installation

```bash
git clone https://github.com/kostyk348/passport-to-uml.git
cd passport-to-uml
pip install -e .

# Requires Graphviz system binary:
#   Windows: winget install Graphviz.Graphviz
#   Linux:   apt install graphviz
#   macOS:   brew install graphviz
```

## Usage

```bash
# Parse passport and generate diagram
python -m passport_to_uml.engine input.pdf output_stem --verbose
```

### Python API

```python
from passport_to_uml import parse_passport, build_diagram

model = parse_passport("document.pdf")
png, pdf = build_diagram(model, "diagram")
print(f"Generated: {png}, {pdf}")
```

---

## Architecture

### Current (v1 — rule-based)

```
PDF → text → sections → keyword match → seed components → DOT → PNG+PDF
```

Limitations:
- Component extraction relies on a hardcoded seed
- Connections are manually defined, not extracted from text
- Different document = new seed needed

### Planned (v2 — LLM agent)

```
PDF → text → sections → LLM extracts structured model → DOT → PNG+PDF
```

The LLM agent would:
1. Read each section and understand what it describes
2. Identify all named components with their types and roles
3. Extract connections from natural language
4. Determine control flow: modes, transitions, algorithms
5. Handle any technical documentation without retraining

---

## License

Apache 2.0

## See Also

- [pdf-spec-parser](https://github.com/kostyk348/pdf-spec-parser) — procurement spec table parser & obfuscator
